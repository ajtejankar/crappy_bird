"""SQLite layer. One file, no ORM, no migrations framework — the schema is the migration.

Post-money era: no payments, no pot. The tables model preference (votes, stamps),
telemetry (plays), governance (versions, live_slot, config), and the developer's
metabolism (runs, ledger).
"""

import json
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "data/crappy.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS plays (               -- one row per death. the instrument.
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version INTEGER NOT NULL,
  pipes INTEGER NOT NULL,
  duration_ms INTEGER,
  flaps INTEGER,
  cause TEXT,
  session TEXT,
  viewport TEXT,
  qualified INTEGER NOT NULL DEFAULT 0,          -- earned a vote (threshold + plausibility)
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS stamps (              -- one stamp per incident report
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  play_id INTEGER UNIQUE NOT NULL REFERENCES plays(id),
  version INTEGER NOT NULL,
  sentiment TEXT NOT NULL CHECK (sentiment IN ('delight','indifference','contempt')),
  label TEXT NOT NULL,                           -- the words on the stamp when it was used
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS votes (               -- one vote per qualifying run, spent at the death screen
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  play_id INTEGER UNIQUE NOT NULL REFERENCES plays(id),
  kind TEXT NOT NULL CHECK (kind IN ('version','idea_new','idea_up')),
  version INTEGER,
  idea_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ideas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',        -- pending | implemented | declined
  version_implemented INTEGER,
  declined_reason TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS versions (            -- the lineage. every release has a name.
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  summary TEXT,
  shipped_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS live_slot (           -- exactly one row. the throne.
  id INTEGER PRIMARY KEY CHECK (id = 1),
  flagship INTEGER NOT NULL,
  rerun_version INTEGER,
  rerun_until TEXT,
  last_rerun_at TEXT
);
CREATE TABLE IF NOT EXISTS slot_log (            -- reign history: who held the slot, when
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('flagship','rerun')),
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  ended_at TEXT
);
CREATE TABLE IF NOT EXISTS config (              -- the agent's standing policy
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_log (          -- append-only. policy has no offstage.
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT NOT NULL,
  source TEXT NOT NULL,                          -- 'founding charter' | 'run #N'
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS runs (                -- the developer's work history + metabolism
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  status TEXT NOT NULL DEFAULT 'triggered',      -- triggered | success | failed | capacity_exhausted
  action TEXT,                                   -- release | polish | rollback | retune | decline
  version INTEGER,
  name TEXT,
  idea_id INTEGER,
  hypothesis TEXT,
  summary TEXT,
  turns INTEGER,
  tokens INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS ledger (              -- exactly one row. learned capacity state.
  id INTEGER PRIMARY KEY CHECK (id = 1),
  exhausted_until TEXT
);
CREATE TABLE IF NOT EXISTS rate_limits (
  ip TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (ip, day, kind)
);
"""

# ------------------------------------------------- policy knobs and clamps
# Defaults are launch values; the agent retunes within clamps via
# /api/agent/complete. Every change lands in config_log. There is no silent act.

CONFIG_DEFAULTS: dict[str, str] = {
    "wheel_nothing": "0.50",
    "wheel_rerun": "0.30",
    "wheel_summon": "0.20",
    "smoothing_alpha": "1.0",
    "gamma": "1.0",
    "vote_pipe_threshold": "10",
    "rerun_minutes": "120",
    "rerun_cooldown_hours": "4",
    "stamp_label_delight": "WOULD DIE AGAIN",
    "stamp_label_indifference": "NOTED",
    "stamp_label_contempt": "FORMAL COMPLAINT",
    "pile_cap": "25",
    "ideas_per_day": "3",
    "votes_per_day": "20",
    "reactions_per_day": "50",
}

# (lo, hi, cast) for numeric knobs; ("label",) for stamp labels (ascii, 1..40 chars)
CONFIG_CLAMPS: dict[str, tuple] = {
    "wheel_nothing": (0.05, 0.90, float),
    "wheel_rerun": (0.05, 0.90, float),
    "wheel_summon": (0.05, 0.90, float),
    "smoothing_alpha": (0.25, 10.0, float),
    "gamma": (0.5, 2.0, float),
    "vote_pipe_threshold": (3, 30, int),
    "rerun_minutes": (30, 480, int),
    "rerun_cooldown_hours": (1, 48, int),
    "stamp_label_delight": ("label",),
    "stamp_label_indifference": ("label",),
    "stamp_label_contempt": ("label",),
    "pile_cap": (10, 100, int),
    "ideas_per_day": (1, 10, int),
    "votes_per_day": (5, 100, int),
    "reactions_per_day": (10, 200, int),
}


def init_db() -> None:
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    with connect() as db:
        _migrate_money_era(db)
        db.executescript(SCHEMA)
        _seed_config(db)
        _copy_forward_money_era_ideas(db)


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    try:
        yield db
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------- migration

def _table_columns(db, table: str) -> list[str]:
    return [r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]


def _migrate_money_era(db) -> None:
    """One-way exit from the extortion edition. Money-era ideas/runs are kept
    under *_money_era for the public record; the payments table is dropped —
    Stripe already has the receipts and we want nothing to do with them."""
    if "payment_id" in _table_columns(db, "ideas"):
        db.execute("ALTER TABLE ideas RENAME TO ideas_money_era")
    if "spend_cents" in _table_columns(db, "runs"):
        db.execute("ALTER TABLE runs RENAME TO runs_money_era")
    db.execute("DROP TABLE IF EXISTS payments")


def _copy_forward_money_era_ideas(db) -> None:
    """Pending money-era ideas were bought fair and square; they enter the new
    pile once (tracked via a config marker so restarts don't duplicate them)."""
    done = db.execute("SELECT value FROM config WHERE key = '_money_era_ideas_copied'").fetchone()
    if done:
        return
    if "ideas_money_era" in [r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
        for r in db.execute("SELECT text, created_at FROM ideas_money_era "
                            "WHERE status = 'pending' ORDER BY id").fetchall():
            db.execute("INSERT INTO ideas (text, created_at) VALUES (?, ?)",
                       (r["text"], r["created_at"]))
    db.execute("INSERT INTO config (key, value) VALUES ('_money_era_ideas_copied', '1')")


def _seed_config(db) -> None:
    for key, value in CONFIG_DEFAULTS.items():
        cur = db.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (key, value))
        if cur.rowcount == 1:
            db.execute(
                "INSERT INTO config_log (key, old_value, new_value, source, note) "
                "VALUES (?, NULL, ?, 'founding charter', 'launch default')",
                (key, value),
            )
    db.execute("INSERT OR IGNORE INTO ledger (id, exhausted_until) VALUES (1, NULL)")


def seed_version(version: int, name: str, summary: str | None = None,
                 shipped_at: str | None = None) -> None:
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO versions (version, name, summary, shipped_at) "
            "VALUES (?, ?, ?, COALESCE(?, datetime('now')))",
            (version, name, summary, shipped_at),
        )


def seed_live_slot(flagship: int) -> None:
    with connect() as db:
        cur = db.execute("INSERT OR IGNORE INTO live_slot (id, flagship) VALUES (1, ?)", (flagship,))
        if cur.rowcount == 1:
            db.execute("INSERT INTO slot_log (version, kind) VALUES (?, 'flagship')", (flagship,))


# ------------------------------------------------------------------ config

def get_config() -> dict:
    """Typed view of the standing policy."""
    with connect() as db:
        raw = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM config")}
    out: dict = {}
    for key, default in CONFIG_DEFAULTS.items():
        val = raw.get(key, default)
        clamp = CONFIG_CLAMPS[key]
        out[key] = clamp[2](val) if len(clamp) == 3 else val
    return out


def set_config(changes: dict[str, str], source: str, note: str | None = None) -> None:
    """Apply pre-validated changes and log every one. Caller clamps first."""
    with connect() as db:
        for key, new in changes.items():
            old = db.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
            old_val = old["value"] if old else None
            if old_val == str(new):
                continue
            db.execute(
                "INSERT INTO config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(new)),
            )
            db.execute(
                "INSERT INTO config_log (key, old_value, new_value, source, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, old_val, str(new), source, note),
            )


def config_log(n: int = 20):
    with connect() as db:
        return db.execute(
            "SELECT key, old_value, new_value, source, note, created_at "
            "FROM config_log WHERE key NOT LIKE '\\_%' ESCAPE '\\' "
            "ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()


# ------------------------------------------------------------------- plays

def record_play(version: int, pipes: int, duration_ms, flaps, cause: str,
                session: str, viewport: str, qualified: bool) -> int:
    with connect() as db:
        cur = db.execute(
            "INSERT INTO plays (version, pipes, duration_ms, flaps, cause, session, viewport, qualified) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (version, pipes, duration_ms, flaps, cause, session, viewport, int(qualified)),
        )
        return cur.lastrowid


def play_by_id(play_id: int):
    with connect() as db:
        return db.execute("SELECT * FROM plays WHERE id = ?", (play_id,)).fetchone()


def version_play_stats(version: int) -> dict:
    """Median pipes + count for the management assessment."""
    with connect() as db:
        rows = db.execute(
            "SELECT pipes FROM plays WHERE version = ? ORDER BY pipes", (version,)
        ).fetchall()
    n = len(rows)
    median = rows[n // 2]["pipes"] if n else 0
    return {"plays": n, "median_pipes": median}


def percentile_of(version: int, pipes: int) -> int | None:
    """Share of plays on this version that died at or before `pipes`. 0-100."""
    with connect() as db:
        total = db.execute("SELECT COUNT(*) AS n FROM plays WHERE version = ?", (version,)).fetchone()["n"]
        if not total:
            return None
        at_or_below = db.execute(
            "SELECT COUNT(*) AS n FROM plays WHERE version = ? AND pipes <= ?", (version, pipes)
        ).fetchone()["n"]
    return round(at_or_below / total * 100)


# ------------------------------------------------------------ stamps/votes

def add_stamp(play_id: int, version: int, sentiment: str, label: str) -> bool:
    with connect() as db:
        cur = db.execute(
            "INSERT OR IGNORE INTO stamps (play_id, version, sentiment, label) VALUES (?, ?, ?, ?)",
            (play_id, version, sentiment, label),
        )
        return cur.rowcount == 1


def add_vote(play_id: int, kind: str, version=None, idea_id=None) -> bool:
    with connect() as db:
        cur = db.execute(
            "INSERT OR IGNORE INTO votes (play_id, kind, version, idea_id) VALUES (?, ?, ?, ?)",
            (play_id, kind, version, idea_id),
        )
        return cur.rowcount == 1


def vote_for_play(play_id: int):
    with connect() as db:
        return db.execute("SELECT * FROM votes WHERE play_id = ?", (play_id,)).fetchone()


def version_votes() -> dict[int, int]:
    with connect() as db:
        return {
            r["version"]: r["n"]
            for r in db.execute(
                "SELECT version, COUNT(*) AS n FROM votes "
                "WHERE kind = 'version' AND version IS NOT NULL GROUP BY version"
            ).fetchall()
        }


def stamp_shares(version: int) -> dict:
    with connect() as db:
        rows = db.execute(
            "SELECT sentiment, COUNT(*) AS n FROM stamps WHERE version = ? GROUP BY sentiment",
            (version,),
        ).fetchall()
    counts = {"delight": 0, "indifference": 0, "contempt": 0}
    for r in rows:
        counts[r["sentiment"]] = r["n"]
    counts["total"] = sum(counts.values())
    return counts


# ------------------------------------------------------------------- ideas

def add_idea(text: str) -> int:
    with connect() as db:
        cur = db.execute("INSERT INTO ideas (text) VALUES (?)", (text,))
        return cur.lastrowid


def idea_by_id(idea_id: int):
    with connect() as db:
        return db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()


def pending_idea_count() -> int:
    with connect() as db:
        return db.execute("SELECT COUNT(*) AS n FROM ideas WHERE status = 'pending'").fetchone()["n"]


def ideas_with_votes(status: str | None = None):
    """Ideas plus their vote mass (submission counts as the first vote)."""
    q = (
        "SELECT i.id, i.text, i.status, i.version_implemented, i.declined_reason, i.created_at, "
        "  (SELECT COUNT(*) FROM votes v WHERE v.idea_id = i.id) AS votes "
        "FROM ideas i "
    )
    args: tuple = ()
    if status:
        q += "WHERE i.status = ? "
        args = (status,)
    q += "ORDER BY votes DESC, i.id ASC LIMIT 500"
    with connect() as db:
        return db.execute(q, args).fetchall()


def mark_idea_implemented(idea_id: int, version: int) -> None:
    with connect() as db:
        db.execute(
            "UPDATE ideas SET status = 'implemented', version_implemented = ? WHERE id = ?",
            (version, idea_id),
        )


def decline_idea(idea_id: int, reason: str) -> None:
    with connect() as db:
        db.execute(
            "UPDATE ideas SET status = 'declined', declined_reason = ? WHERE id = ? AND status = 'pending'",
            (reason, idea_id),
        )


# --------------------------------------------------------------- versions

def all_versions():
    with connect() as db:
        return db.execute("SELECT * FROM versions ORDER BY version").fetchall()


def version_row(version: int):
    with connect() as db:
        return db.execute("SELECT * FROM versions WHERE version = ?", (version,)).fetchone()


def add_version(version: int, name: str, summary: str | None) -> None:
    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO versions (version, name, summary) VALUES (?, ?, ?)",
            (version, name, summary),
        )


# -------------------------------------------------------------- live slot

def get_live_slot():
    with connect() as db:
        return db.execute("SELECT * FROM live_slot WHERE id = 1").fetchone()


def set_flagship(version: int) -> None:
    with connect() as db:
        db.execute(
            "UPDATE slot_log SET ended_at = datetime('now') "
            "WHERE kind = 'flagship' AND ended_at IS NULL"
        )
        db.execute("INSERT INTO slot_log (version, kind) VALUES (?, 'flagship')", (version,))
        db.execute("UPDATE live_slot SET flagship = ? WHERE id = 1", (version,))


def start_rerun(version: int, minutes: int) -> None:
    with connect() as db:
        db.execute(
            "UPDATE live_slot SET rerun_version = ?, "
            "rerun_until = datetime('now', ?), last_rerun_at = datetime('now') WHERE id = 1",
            (version, f"+{int(minutes)} minutes"),
        )
        db.execute("INSERT INTO slot_log (version, kind) VALUES (?, 'rerun')", (version,))


def end_rerun_if_expired() -> None:
    with connect() as db:
        slot = db.execute("SELECT * FROM live_slot WHERE id = 1").fetchone()
        if slot and slot["rerun_version"] is not None and slot["rerun_until"] <= _now(db):
            db.execute(
                "UPDATE slot_log SET ended_at = datetime('now') "
                "WHERE kind = 'rerun' AND ended_at IS NULL"
            )
            db.execute("UPDATE live_slot SET rerun_version = NULL, rerun_until = NULL WHERE id = 1")


def rerun_active() -> bool:
    with connect() as db:
        slot = db.execute("SELECT * FROM live_slot WHERE id = 1").fetchone()
        return bool(slot and slot["rerun_version"] is not None and slot["rerun_until"] > _now(db))


def rerun_cooldown_active(cooldown_hours: int) -> bool:
    with connect() as db:
        slot = db.execute("SELECT * FROM live_slot WHERE id = 1").fetchone()
        if not slot or not slot["last_rerun_at"]:
            return False
        gate_end = db.execute(
            "SELECT datetime(?, ?) AS t", (slot["last_rerun_at"], f"+{int(cooldown_hours)} hours")
        ).fetchone()["t"]
        return gate_end > _now(db)


def reigns(version: int) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT kind, started_at, ended_at FROM slot_log WHERE version = ? ORDER BY id",
            (version,),
        ).fetchall()
    return [dict(r) for r in rows]


def _now(db) -> str:
    return db.execute("SELECT datetime('now') AS t").fetchone()["t"]


# -------------------------------------------------------------------- runs

def active_run():
    """A run that was triggered and hasn't reported back yet (within 2h — stale ones unblock)."""
    with connect() as db:
        return db.execute(
            "SELECT * FROM runs WHERE status = 'triggered' "
            "AND created_at > datetime('now', '-2 hours') ORDER BY id DESC LIMIT 1"
        ).fetchone()


def create_run() -> int:
    with connect() as db:
        cur = db.execute("INSERT INTO runs (status) VALUES ('triggered')")
        return cur.lastrowid


def complete_run(status: str, action, version, name, idea_id, hypothesis,
                 summary: str, turns, tokens) -> int | None:
    """Close the newest in-flight run (or record an orphan report). Returns run id."""
    with connect() as db:
        row = db.execute(
            "SELECT id FROM runs WHERE status = 'triggered' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            db.execute(
                "UPDATE runs SET status = ?, action = ?, version = ?, name = ?, idea_id = ?, "
                "hypothesis = ?, summary = ?, turns = ?, tokens = ?, finished_at = datetime('now') "
                "WHERE id = ?",
                (status, action, version, name, idea_id, hypothesis, summary, turns, tokens, row["id"]),
            )
            return row["id"]
        cur = db.execute(
            "INSERT INTO runs (status, action, version, name, idea_id, hypothesis, summary, "
            "turns, tokens, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (status, action, version, name, idea_id, hypothesis, summary, turns, tokens),
        )
        return cur.lastrowid


def last_runs(n: int = 10):
    with connect() as db:
        return db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (n,)).fetchall()


def last_finished_run():
    with connect() as db:
        return db.execute(
            "SELECT * FROM runs WHERE status != 'triggered' ORDER BY id DESC LIMIT 1"
        ).fetchone()


# ------------------------------------------------------------------ ledger

def runs_started_since(hours: float) -> int:
    with connect() as db:
        return db.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE created_at > datetime('now', ?)",
            (f"-{hours} hours",),
        ).fetchone()["n"]


def oldest_run_in_window(hours: float):
    with connect() as db:
        return db.execute(
            "SELECT created_at FROM runs WHERE created_at > datetime('now', ?) "
            "ORDER BY created_at ASC LIMIT 1",
            (f"-{hours} hours",),
        ).fetchone()


def ledger_exhausted_until() -> str | None:
    with connect() as db:
        row = db.execute("SELECT exhausted_until FROM ledger WHERE id = 1").fetchone()
        if row and row["exhausted_until"] and row["exhausted_until"] > _now(db):
            return row["exhausted_until"]
        return None


def mark_exhausted_until(until_expr: str) -> None:
    """until_expr is an SQLite datetime modifier applied to now, e.g. '+5 hours'."""
    with connect() as db:
        db.execute(
            "UPDATE ledger SET exhausted_until = datetime('now', ?) WHERE id = 1", (until_expr,)
        )


def mark_exhausted_until_absolute(when: str) -> None:
    with connect() as db:
        db.execute("UPDATE ledger SET exhausted_until = ? WHERE id = 1", (when,))


# ------------------------------------------------------------- rate limits

def bump_rate(ip: str, kind: str, cap: int) -> bool:
    """Increment today's counter; False when the cap is already spent."""
    with connect() as db:
        day = db.execute("SELECT date('now') AS d").fetchone()["d"]
        row = db.execute(
            "SELECT count FROM rate_limits WHERE ip = ? AND day = ? AND kind = ?",
            (ip, day, kind),
        ).fetchone()
        if row and row["count"] >= cap:
            return False
        db.execute(
            "INSERT INTO rate_limits (ip, day, kind, count) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(ip, day, kind) DO UPDATE SET count = count + 1",
            (ip, day, kind),
        )
        return True


# ------------------------------------------------------------ the dossier

def participation() -> dict:
    with connect() as db:
        plays = db.execute("SELECT COUNT(*) AS n FROM plays").fetchone()["n"]
        qualified = db.execute("SELECT COUNT(*) AS n FROM plays WHERE qualified = 1").fetchone()["n"]
        stamps = db.execute("SELECT COUNT(*) AS n FROM stamps").fetchone()["n"]
        votes = db.execute("SELECT COUNT(*) AS n FROM votes").fetchone()["n"]
    return {
        "plays": plays,
        "qualified_plays": qualified,
        "stamps": stamps,
        "votes_cast": votes,
        "stamp_rate": round(stamps / plays, 3) if plays else None,
        "qualification_rate": round(qualified / plays, 3) if plays else None,
        "vote_spend_rate": round(votes / qualified, 3) if qualified else None,
    }


def death_heatmap() -> dict:
    with connect() as db:
        by_cause = {
            r["cause"] or "unknown": r["n"]
            for r in db.execute("SELECT cause, COUNT(*) AS n FROM plays GROUP BY cause").fetchall()
        }
        buckets = {"0": 0, "1-3": 0, "4-9": 0, "10-19": 0, "20+": 0}
        for r in db.execute("SELECT pipes, COUNT(*) AS n FROM plays GROUP BY pipes").fetchall():
            p, n = r["pipes"], r["n"]
            key = "0" if p == 0 else "1-3" if p <= 3 else "4-9" if p <= 9 else "10-19" if p <= 19 else "20+"
            buckets[key] += n
    return {"by_cause": by_cause, "by_pipes": buckets}


def plays_per_version() -> dict[int, dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT version, COUNT(*) AS plays, "
            "  CAST(AVG(pipes) AS REAL) AS mean_pipes "
            "FROM plays GROUP BY version"
        ).fetchall()
    out = {}
    for r in rows:
        out[r["version"]] = {
            "plays": r["plays"],
            "median_pipes": version_play_stats(r["version"])["median_pipes"],
        }
    return out


def json_default(o):
    return str(o)
