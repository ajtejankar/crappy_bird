"""SQLite layer. One file, no ORM, no migrations framework — the schema is the migration."""

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "data/crappy.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stripe_session_id TEXT UNIQUE NOT NULL,
  amount_cents INTEGER NOT NULL,
  net_cents INTEGER NOT NULL,
  credits INTEGER NOT NULL,
  credits_used INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ideas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_id INTEGER REFERENCES payments(id),
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',            -- pending | implemented
  version_implemented INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  status TEXT NOT NULL DEFAULT 'triggered',          -- triggered | success | failed
  version INTEGER,
  idea_id INTEGER,
  spend_cents INTEGER NOT NULL DEFAULT 0,
  summary TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at TEXT
);
"""


def init_db() -> None:
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    with connect() as db:
        db.executescript(SCHEMA)


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


# ---------------------------------------------------------------- payments

def record_payment(session_id: str, amount_cents: int, net_cents: int, credits: int) -> bool:
    """Idempotent. Returns True if this call inserted the payment."""
    with connect() as db:
        cur = db.execute(
            "INSERT OR IGNORE INTO payments (stripe_session_id, amount_cents, net_cents, credits) "
            "VALUES (?, ?, ?, ?)",
            (session_id, amount_cents, net_cents, credits),
        )
        return cur.rowcount == 1


def payment_by_session(session_id: str):
    with connect() as db:
        return db.execute(
            "SELECT * FROM payments WHERE stripe_session_id = ?", (session_id,)
        ).fetchone()


# ------------------------------------------------------------------- ideas

def add_idea(session_id: str, text: str):
    """Consumes one credit. Returns (ok, remaining_credits | error message)."""
    with connect() as db:
        pay = db.execute(
            "SELECT * FROM payments WHERE stripe_session_id = ?", (session_id,)
        ).fetchone()
        if not pay:
            return False, "no such payment"
        remaining = pay["credits"] - pay["credits_used"]
        if remaining <= 0:
            return False, "no idea credits left on this payment"
        db.execute(
            "UPDATE payments SET credits_used = credits_used + 1 WHERE id = ?", (pay["id"],)
        )
        db.execute("INSERT INTO ideas (payment_id, text) VALUES (?, ?)", (pay["id"], text))
        return True, remaining - 1


def pending_ideas():
    with connect() as db:
        return db.execute(
            "SELECT id, text, created_at FROM ideas WHERE status = 'pending' ORDER BY id"
        ).fetchall()


def all_ideas():
    with connect() as db:
        return db.execute(
            "SELECT id, text, status, version_implemented, created_at FROM ideas ORDER BY id DESC LIMIT 500"
        ).fetchall()


def mark_idea_implemented(idea_id: int, version: int) -> None:
    with connect() as db:
        db.execute(
            "UPDATE ideas SET status = 'implemented', version_implemented = ? WHERE id = ?",
            (version, idea_id),
        )


# -------------------------------------------------------------------- runs

def pot_cents() -> int:
    with connect() as db:
        earned = db.execute("SELECT COALESCE(SUM(net_cents), 0) AS s FROM payments").fetchone()["s"]
        spent = db.execute("SELECT COALESCE(SUM(spend_cents), 0) AS s FROM runs").fetchone()["s"]
        return earned - spent


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


def complete_run(status: str, version, idea_id, spend_cents: int, summary: str) -> None:
    with connect() as db:
        row = db.execute(
            "SELECT id FROM runs WHERE status = 'triggered' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            db.execute(
                "UPDATE runs SET status = ?, version = ?, idea_id = ?, spend_cents = ?, "
                "summary = ?, finished_at = datetime('now') WHERE id = ?",
                (status, version, idea_id, spend_cents, summary, row["id"]),
            )
        else:
            # Run reported back but we have no triggered row (manual workflow_dispatch).
            db.execute(
                "INSERT INTO runs (status, version, idea_id, spend_cents, summary, finished_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (status, version, idea_id, spend_cents, summary),
            )


def last_runs(n: int = 10):
    with connect() as db:
        return db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (n,)).fetchall()


def stats():
    with connect() as db:
        pays = db.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS gross, "
            "COALESCE(SUM(net_cents), 0) AS net FROM payments"
        ).fetchone()
        pending = db.execute("SELECT COUNT(*) AS n FROM ideas WHERE status = 'pending'").fetchone()["n"]
        done = db.execute("SELECT COUNT(*) AS n FROM ideas WHERE status = 'implemented'").fetchone()["n"]
        spent = db.execute("SELECT COALESCE(SUM(spend_cents), 0) AS s FROM runs").fetchone()["s"]
        return {
            "payments": pays["n"],
            "gross_cents": pays["gross"],
            "net_cents": pays["net"],
            "spent_cents": spent,
            "pot_cents": pays["net"] - spent,
            "pending_ideas": pending,
            "implemented_ideas": done,
        }
