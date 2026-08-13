"""crappy bird — the web app.

The whole operation is a production and this file is the stage crew: it serves
the one live version of the game, injects management (the overlay) at serve
time, files incident reports (telemetry), counts stamps and votes, spins the
wheel on every death, and — when the wheel says so and the capacity ledger
allows it — wakes the developer (a GitHub Actions workflow).

No money moves through here, in any direction, ever.
"""

import hmac
import json
import logging
import os
import random
import re
import secrets
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from . import db

log = logging.getLogger("crappy")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# ------------------------------------------------------------------ config

APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8080").rstrip("/")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")          # "owner/repo"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
GITHUB_PAT = os.environ.get("GITHUB_PAT", "")

# the developer's metabolism (mirrors Claude Pro reality, conservatively;
# the ledger learns the truth from collisions)
WINDOW_HOURS = float(os.environ.get("WINDOW_HOURS", "5"))
RUNS_PER_WINDOW = int(os.environ.get("RUNS_PER_WINDOW", "1"))
RUNS_PER_WEEK = int(os.environ.get("RUNS_PER_WEEK", "8"))
MIN_SAMPLE = int(os.environ.get("MIN_SAMPLE", "30"))
PLAYS_PER_DAY = int(os.environ.get("PLAYS_PER_DAY", "1000"))
MAX_PIPES_PER_SECOND = 2.0   # server-side plausibility ceiling on reported runs

DEV_MODE = not (GITHUB_REPO and GITHUB_PAT)  # no repo/PAT -> summons are simulated

ROOT = Path(__file__).resolve().parent.parent
GAMES_DIR = ROOT / "games"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# CSP for the game document: future versions can do whatever they want except
# leave the building. connect-src 'self' exists solely so the injected overlay
# can file reports with the front desk. Zero external egress.
GAME_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data:; media-src data:; font-src data:; connect-src 'self'; "
    "form-action 'none'; base-uri 'none'"
)

app = FastAPI(title="crappy bird", docs_url=None, redoc_url=None)
db.init_db()

if not AGENT_TOKEN:
    AGENT_TOKEN = secrets.token_hex(32)
    log.warning("AGENT_TOKEN not set — generated an ephemeral one; agent endpoints "
                "will not be reachable across restarts. Set AGENT_TOKEN in the environment.")
if DEV_MODE:
    log.warning("GITHUB_REPO/GITHUB_PAT not set — DEV MODE: summons are simulated, "
                "the developer is imaginary.")


# --------------------------------------------------------------- seed state

def _local_latest_version() -> int:
    try:
        return int(json.loads((GAMES_DIR / "latest.json").read_text())["version"])
    except (OSError, ValueError, KeyError):
        return 1


# names for versions that shipped before versions had names. everything after
# this arrives through /api/agent/complete with a name attached.
FOUNDING_VERSIONS = [
    (1, "the primordial bird", "a bird that flaps, craps, and dies. the death screen files a report."),
    (2, "the mains pressure incident", "the pipes are loaded and return fire. cosmetically. a turd that kills you is a bug."),
    (3, "the paperwork update", "every death now files complete paperwork: pipes, duration, flaps, cause."),
]

for _v, _name, _summary in FOUNDING_VERSIONS:
    if (GAMES_DIR / f"index.v{_v}.html").is_file():
        db.seed_version(_v, _name, _summary)
db.seed_live_slot(_local_latest_version())


# ------------------------------------------------- game source (GitHub raw)
# In production the repo is the source of truth for game files, so the agent's
# commits go live without redeploying the app. Locally we serve games/ directly.

_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 60.0


async def _fetch_game_text(relpath: str) -> str | None:
    """Game file text from GitHub raw (cached 60s), falling back to local games/."""
    now = time.time()
    hit = _cache.get(relpath)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    text = None
    if GITHUB_REPO:
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/games/{relpath}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    text = r.text
        except httpx.HTTPError as e:
            log.warning("github raw fetch failed for %s: %s", relpath, e)
    if text is None:
        local = GAMES_DIR / relpath
        if local.is_file():
            text = local.read_text()
    if text is not None:
        _cache[relpath] = (now, text)
    return text


def bust_game_cache() -> None:
    _cache.clear()


# --------------------------------------------------------------- live slot

def live_state() -> dict:
    """Who holds the throne right now. The DB owns this pointer."""
    db.end_rerun_if_expired()
    slot = db.get_live_slot()
    flagship = slot["flagship"]
    if slot["rerun_version"] is not None:
        v = slot["rerun_version"]
        row = db.version_row(v)
        return {
            "version": v,
            "name": row["name"] if row else f"v{v}",
            "is_rerun": True,
            "rerun_until": slot["rerun_until"],
            "flagship": flagship,
        }
    row = db.version_row(flagship)
    return {
        "version": flagship,
        "name": row["name"] if row else f"v{flagship}",
        "is_rerun": False,
        "rerun_until": None,
        "flagship": flagship,
    }


def _actions_url() -> str | None:
    return f"https://github.com/{GITHUB_REPO}/actions/workflows/develop.yml" if GITHUB_REPO else None


def _latest_notice() -> str | None:
    """The most recent policy change, phrased as the announcement it must be."""
    for row in db.config_log(5):
        if row["source"] == "founding charter":
            continue
        return (f"NOTICE: the developer set {row['key']} to {row['new_value']} "
                f"(was {row['old_value']}). it is not allowed to do this quietly.")
    return None


# ------------------------------------------------------------------- pages

def _static(name: str) -> FileResponse:
    return FileResponse(STATIC_DIR / name, media_type="text/html")


@app.get("/", response_class=HTMLResponse)
async def lobby():
    return _static("index.html")


@app.get("/versions", response_class=HTMLResponse)
async def versions_page():
    return _static("versions.html")


@app.get("/changelog", response_class=HTMLResponse)
async def changelog_page():
    return _static("changelog.html")


MANAGEMENT_TEMPLATE = (STATIC_DIR / "management.html").read_text()


def _inject_management(game_html: str, state: dict) -> str:
    """Append the management overlay to a game document at serve time.

    The downloadable file stays raw; only the hosted page is under management.
    """
    cfg = json.dumps({
        "version": state["version"],
        "name": state["name"],
        "is_rerun": state["is_rerun"],
        "rerun_until": state["rerun_until"],
        "flagship": state["flagship"],
        "developing": db.active_run() is not None,
        "actions_url": _actions_url(),
        "notice": _latest_notice(),
        "dev_mode": DEV_MODE,
    })
    snippet = MANAGEMENT_TEMPLATE.replace("__CFG__", cfg)
    if "</body>" in game_html:
        return game_html.replace("</body>", snippet + "\n</body>", 1)
    return game_html + snippet  # browsers execute trailing content anyway


@app.get("/play", response_class=HTMLResponse)
async def play():
    """The single live slot. There are no other doors."""
    state = live_state()
    text = await _fetch_game_text(f"index.v{state['version']}.html")
    if text is None:
        raise HTTPException(404, "the live version has gone missing. management is looking into it.")
    return HTMLResponse(_inject_management(text, state),
                        headers={"Content-Security-Policy": GAME_CSP})


@app.get("/download")
async def download():
    state = live_state()
    v = state["version"]
    text = await _fetch_game_text(f"index.v{v}.html")
    if text is None:
        raise HTTPException(404, "nothing to download. suspicious.")
    return Response(
        text,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="crappy-bird-v{v}.html"'},
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# ----------------------------------------------------------------- helpers

def _client_ip(request: Request) -> str:
    for header in ("fly-client-ip", "x-forwarded-for"):
        val = request.headers.get(header)
        if val:
            return val.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit(request: Request, kind: str, cap: int, refusal: str) -> None:
    if not db.bump_rate(_client_ip(request), kind, cap):
        raise HTTPException(429, refusal)


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(s, limit: int) -> str:
    return _CONTROL.sub("", str(s)).strip()[:limit]


def _int_or_none(v, lo: int, hi: int):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


# ---------------------------------------------------------------- the wheel

def spin_wheel() -> dict:
    """A two-level categorical sampler, spun on every death, in public.

    The wheel never lies: outcomes are sampled over the drawn slice areas, and
    a gated slice simply pays out as NOTHING — that is the renormalization,
    performed where everyone can see it.
    """
    cfg = db.get_config()
    state = live_state()

    candidates = [dict(v) for v in db.all_versions() if v["version"] != state["version"]]

    gates: dict[str, str] = {}
    if state["is_rerun"]:
        gates["rerun"] = "a rerun already holds the slot"
    elif db.rerun_cooldown_active(cfg["rerun_cooldown_hours"]):
        gates["rerun"] = "the museum is closed (cooldown)"
    elif not candidates:
        gates["rerun"] = "there is no history to rerun"

    if db.active_run():
        gates["summon"] = "the developer is already working"
    elif db.ledger_exhausted_until():
        gates["summon"] = "the developer is exhausted"
    elif db.runs_started_since(WINDOW_HOURS) >= RUNS_PER_WINDOW:
        gates["summon"] = "the developer just worked. it gets a window."
    elif db.runs_started_since(24 * 7) >= RUNS_PER_WEEK:
        gates["summon"] = "the developer is out of hours this week"

    slices = [
        {"key": "nothing", "label": "NOTHING", "weight": cfg["wheel_nothing"]},
        {"key": "rerun", "label": "RERUN", "weight": cfg["wheel_rerun"]},
        {"key": "summon", "label": "SUMMON", "weight": cfg["wheel_summon"]},
    ]
    for s in slices:
        s["gated"] = s["key"] in gates
        s["reason"] = gates.get(s["key"])

    landed = random.choices([s["key"] for s in slices],
                            weights=[s["weight"] for s in slices])[0]
    outcome, detail = landed, {}

    if landed in gates:
        outcome = "nothing"
        detail = {"landed": landed, "reason": gates[landed]}
    elif landed == "rerun":
        alpha, gamma = cfg["smoothing_alpha"], cfg["gamma"]
        votes = db.version_votes()
        weights = [(votes.get(c["version"], 0) + alpha) ** gamma for c in candidates]
        pick = random.choices(candidates, weights=weights)[0]
        db.start_rerun(pick["version"], cfg["rerun_minutes"])
        slot = db.get_live_slot()
        detail = {
            "version": pick["version"],
            "name": pick["name"],
            "minutes": cfg["rerun_minutes"],
            "until": slot["rerun_until"],
            "odds": [
                {"version": c["version"], "name": c["name"],
                 "weight": round(w / sum(weights), 3)}
                for c, w in zip(candidates, weights)
            ],
        }
    elif landed == "summon":
        run_id = db.create_run()
        dispatched = _dispatch_dev_cycle_checked(run_id)
        detail = {"run_id": run_id, "dispatched": dispatched, "actions_url": _actions_url()}

    return {"slices": slices, "landed": landed, "outcome": outcome, "detail": detail}


# ------------------------------------------------------------- the summons

def _dispatch_dev_cycle_checked(run_id: int) -> bool:
    if DEV_MODE:
        log.info("DEV MODE: summon #%s recorded, no developer to wake", run_id)
        return True
    try:
        # workflow_dispatch, not repository_dispatch: this runs on Actions: write
        # alone, so the internet-facing app holds a token that can start the
        # developer but can never write to the repo.
        r = httpx.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/develop.yml/dispatches",
            headers={
                "Authorization": f"Bearer {GITHUB_PAT}",
                "Accept": "application/vnd.github+json",
            },
            json={"ref": GITHUB_BRANCH},
            timeout=15,
        )
        r.raise_for_status()
        log.info("THE DEVELOPER IS SUMMONED (run #%s)", run_id)
        return True
    except httpx.HTTPError as e:
        log.error("failed to dispatch workflow: %s", e)
        db.complete_run("failed", None, None, None, None, None,
                        f"the summons was lost in the mail: {e}", None, None)
        return False


# -------------------------------------------------------------- assessment

def _assessment(version: int, pipes: int) -> str:
    stats = db.version_play_stats(version)
    n, median = stats["plays"], stats["median_pipes"]
    if n < MIN_SAMPLE:
        return (f"insufficient data for a verdict (n={n}). "
                "management records the number and moves on.")
    if pipes > median:
        return (f"you outlived the median player ({median} pipes, n={n}). "
                "do not let it go to your head.")
    if pipes == median:
        return f"exactly median ({median} pipes, n={n}). management admires consistency."
    if median > 0:
        rel = round((median - pipes) / median * 100)
        return f"you die {rel}% earlier than the median player (median {median}, n={n})."
    return f"everyone dies at zero on this version (n={n}). it may not be you."


def _progress_line(pipes: int, threshold: int, qualified: bool) -> str:
    target = threshold + 1
    if qualified:
        return f"{pipes}/{target} pipes — you have earned one (1) vote. spend it or lose it."
    if pipes >= threshold - 1:
        return f"{pipes}/{target} pipes — almost worth listening to."
    if pipes == 0:
        return f"0/{target} pipes. management has no notes. management has only questions."
    return f"{pipes}/{target} pipes — opinions are earned above {target}."


# --------------------------------------------------------------- public API

@app.get("/api/state")
async def api_state():
    """Everything the lobby needs. Total transparency, one endpoint."""
    state = live_state()
    cfg = db.get_config()
    flagship_row = db.version_row(state["flagship"])
    votes = db.version_votes()
    shares = db.stamp_shares(state["version"])
    stats = db.version_play_stats(state["version"])
    last = db.last_finished_run()
    exhausted = db.ledger_exhausted_until()
    window_used = db.runs_started_since(WINDOW_HOURS)
    week_used = db.runs_started_since(24 * 7)

    if db.active_run():
        mood = "the developer is working. observe."
    elif exhausted:
        mood = f"the developer is exhausted until {exhausted} UTC. the wheel knows."
    elif week_used >= RUNS_PER_WEEK:
        mood = "the developer is out of hours this week."
    elif window_used >= RUNS_PER_WINDOW:
        mood = "the developer just worked and is digesting."
    else:
        mood = "the developer is rested and summonable."

    last_run = None
    if last:
        evidence = None
        if last["version"]:
            v_shares = db.stamp_shares(last["version"])
            evidence = {
                "votes": votes.get(last["version"], 0),
                "stamps": v_shares,
                "delight_share": (round(v_shares["delight"] / v_shares["total"], 3)
                                  if v_shares["total"] else None),
                "plays": db.version_play_stats(last["version"])["plays"],
            }
        last_run = {
            "status": last["status"], "action": last["action"], "version": last["version"],
            "name": last["name"], "hypothesis": last["hypothesis"],
            "summary": last["summary"], "finished_at": last["finished_at"],
            "evidence": evidence,
        }

    return {
        "live": {**state, "flagship_name": flagship_row["name"] if flagship_row else None},
        "standing": {
            "votes": votes.get(state["version"], 0),
            "plays": stats["plays"],
            "stamps": shares,
            "delight_share": (round(shares["delight"] / shares["total"], 3)
                              if shares["total"] else None),
        },
        "pile": [
            {"id": r["id"], "text": r["text"], "status": r["status"], "votes": r["votes"],
             "version_implemented": r["version_implemented"],
             "declined_reason": r["declined_reason"]}
            for r in db.ideas_with_votes()
        ],
        "pile_cap": cfg["pile_cap"],
        "pending_ideas": db.pending_idea_count(),
        "wheel": {"nothing": cfg["wheel_nothing"], "rerun": cfg["wheel_rerun"],
                  "summon": cfg["wheel_summon"]},
        "vote_pipe_threshold": cfg["vote_pipe_threshold"],
        "dev": {
            "working": db.active_run() is not None,
            "actions_url": _actions_url(),
            "mood": mood,
            "window_slots_left": max(0, RUNS_PER_WINDOW - window_used),
            "week_slots_left": max(0, RUNS_PER_WEEK - week_used),
            "exhausted_until": exhausted,
        },
        "last_run": last_run,
        "notice": _latest_notice(),
        "dev_mode": DEV_MODE,
    }


@app.get("/api/versions")
async def api_versions():
    state = live_state()
    votes = db.version_votes()
    out = []
    for v in db.all_versions():
        shares = db.stamp_shares(v["version"])
        out.append({
            "version": v["version"], "name": v["name"], "summary": v["summary"],
            "shipped_at": v["shipped_at"],
            "votes": votes.get(v["version"], 0),
            "stamps": shares,
            "delight_share": (round(shares["delight"] / shares["total"], 3)
                              if shares["total"] else None),
            "plays": db.version_play_stats(v["version"])["plays"],
            "reigns": db.reigns(v["version"]),
            "is_flagship": v["version"] == state["flagship"],
            "is_live": v["version"] == state["version"],
        })
    return out


@app.get("/api/changelog", response_class=PlainTextResponse)
async def api_changelog():
    text = await _fetch_game_text("CHANGELOG.md")
    return text or "no history. suspicious."


@app.get("/api/config")
async def api_config():
    """The standing policy and its paper trail. Public, like everything."""
    cfg = {k: v for k, v in db.get_config().items()}
    return {
        "config": cfg,
        "log": [dict(r) for r in db.config_log(30)],
    }


@app.post("/api/death")
async def api_death(request: Request):
    """Every death files an incident report. This is the filing window."""
    _rate_limit(request, "plays", PLAYS_PER_DAY,
                "that is enough dying for one day. management reopens at midnight.")
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "the report form was illegible. management requires JSON.")

    cfg = db.get_config()
    state = live_state()

    version = _int_or_none(body.get("version"), 1, 100_000) or state["version"]
    pipes = _int_or_none(body.get("pipes"), 0, 10_000)
    if pipes is None:
        raise HTTPException(400, "a death with no pipe count. management cannot file this.")
    duration_ms = _int_or_none(body.get("durationMs"), 1, 24 * 3600 * 1000)
    flaps = _int_or_none(body.get("flaps"), 0, 1_000_000)
    cause = _clean_text(body.get("cause", "unknown"), 64) or "unknown"
    session = _clean_text(body.get("session", ""), 64)
    viewport = _clean_text(body.get("viewport", ""), 32)

    # plausibility: pipes arrive at a physical rate. faster than the ceiling
    # is not skill, it is arithmetic.
    plausible = True
    if pipes > 0:
        if duration_ms is None:
            plausible = False
        elif pipes / (duration_ms / 1000) > MAX_PIPES_PER_SECOND:
            plausible = False

    threshold = cfg["vote_pipe_threshold"]
    qualified = plausible and pipes > threshold

    play_id = db.record_play(version, pipes, duration_ms, flaps, cause,
                             session, viewport, qualified)
    version_row = db.version_row(version)

    ballot = None
    if qualified:
        votes = db.version_votes()
        ballot = {
            "versions": [
                {"version": v["version"], "name": v["name"],
                 "votes": votes.get(v["version"], 0),
                 "is_live": v["version"] == state["version"]}
                for v in db.all_versions()
            ],
            "ideas": [
                {"id": r["id"], "text": r["text"], "votes": r["votes"]}
                for r in db.ideas_with_votes("pending")
            ],
            "pile_open": db.pending_idea_count() < cfg["pile_cap"],
            "pile_cap": cfg["pile_cap"],
        }

    return {
        "play_id": play_id,
        "report_no": f"{play_id:07d}",
        "version": version,
        "version_name": version_row["name"] if version_row else f"v{version}",
        "pipes": pipes,
        "cause": cause,
        "plausible": plausible,
        "assessment": _assessment(version, pipes) if plausible else
        "this run exceeds the physical pipe rate. filed under fiction.",
        "qualified": qualified,
        "threshold": threshold,
        "progress_line": _progress_line(pipes, threshold, qualified) if plausible else
        "0 credible pipes. the vote does not exist.",
        "stamps": {
            "delight": cfg["stamp_label_delight"],
            "indifference": cfg["stamp_label_indifference"],
            "contempt": cfg["stamp_label_contempt"],
        },
        "wheel": spin_wheel(),
        "ballot": ballot,
        "dev": {"working": db.active_run() is not None, "actions_url": _actions_url()},
    }


@app.post("/api/stamp")
async def api_stamp(request: Request):
    cfg = db.get_config()
    _rate_limit(request, "reactions", cfg["reactions_per_day"],
                "out of opinions for today. management reopens at midnight.")
    body = await request.json()
    play_id = _int_or_none(body.get("play_id"), 1, 2**53)
    sentiment = str(body.get("sentiment", ""))
    if sentiment not in ("delight", "indifference", "contempt"):
        raise HTTPException(400, "that is not one of the three approved feelings.")
    play = db.play_by_id(play_id) if play_id else None
    if not play:
        raise HTTPException(404, "no such incident report. it may have been shredded.")
    label = cfg[f"stamp_label_{sentiment}"]
    if not db.add_stamp(play_id, play["version"], sentiment, label):
        raise HTTPException(409, "this report is already stamped. one opinion per death.")
    return {"ok": True, "label": label, "line": "stamped and filed. management thanks you for nothing."}


@app.post("/api/vote")
async def api_vote(request: Request):
    cfg = db.get_config()
    _rate_limit(request, "votes", cfg["votes_per_day"],
                "your voting hand is tired. management reopens at midnight.")
    body = await request.json()
    play_id = _int_or_none(body.get("play_id"), 1, 2**53)
    kind = str(body.get("kind", ""))
    play = db.play_by_id(play_id) if play_id else None
    if not play:
        raise HTTPException(404, "no such incident report. it may have been shredded.")
    if not play["qualified"]:
        raise HTTPException(403, "this run did not clear the bar. the vote does not exist.")
    if db.vote_for_play(play_id):
        raise HTTPException(409, "that vote is spent. votes do not grow back.")

    if kind == "version":
        version = _int_or_none(body.get("version"), 1, 100_000)
        if not version or not db.version_row(version):
            raise HTTPException(400, "you cannot vote for a version that does not exist. yet.")
        db.add_vote(play_id, "version", version=version)
        row = db.version_row(version)
        return {"ok": True, "line": f"one vote for v{version} — {row['name']}. counted in public."}

    if kind == "idea_up":
        idea_id = _int_or_none(body.get("idea_id"), 1, 2**53)
        idea = db.idea_by_id(idea_id) if idea_id else None
        if not idea or idea["status"] != "pending":
            raise HTTPException(400, "that idea is not on the pile. it may have been used, or refused.")
        db.add_vote(play_id, "idea_up", idea_id=idea_id)
        return {"ok": True, "line": f"idea #{idea_id} gains one vote. the pile shifts slightly."}

    if kind == "idea_new":
        _rate_limit(request, "ideas", cfg["ideas_per_day"],
                    "three ideas a day is the legal limit of genius. come back tomorrow.")
        text = _clean_text(body.get("text", ""), 500)
        if not text:
            raise HTTPException(400, "an empty idea. bold, but no.")
        if len(str(body.get("text", ""))) > 500:
            raise HTTPException(400, "500 characters max. constraints breed creativity.")
        if db.pending_idea_count() >= cfg["pile_cap"]:
            raise HTTPException(409, f"the pile is full ({cfg['pile_cap']} ideas). "
                                     "scarcity is quality control. upvote something instead.")
        idea_id = db.add_idea(text)
        db.add_vote(play_id, "idea_new", idea_id=idea_id)
        return {"ok": True, "idea_id": idea_id,
                "line": f"idea #{idea_id} enters the pile. the developer will see it. eventually."}

    raise HTTPException(400, "a vote must be one of: version, idea_up, idea_new.")


# ---------------------------------------------------------------- agent API

def _check_agent_auth(authorization: str | None) -> None:
    expected = f"Bearer {AGENT_TOKEN}"
    if not (authorization and hmac.compare_digest(authorization, expected)):
        raise HTTPException(401, "no")


@app.get("/api/agent/ideas")
async def agent_ideas(authorization: str = Header(None)):
    _check_agent_auth(authorization)
    return [
        {"id": r["id"], "text": r["text"], "votes": r["votes"], "created_at": r["created_at"]}
        for r in db.ideas_with_votes("pending")
    ]


@app.get("/api/agent/metrics")
async def agent_metrics(authorization: str = Header(None)):
    """The dossier. ~40 lines of state; sample sizes attached to everything."""
    _check_agent_auth(authorization)
    state = live_state()
    votes = db.version_votes()
    per_version = db.plays_per_version()
    cfg = db.get_config()
    exhausted = db.ledger_exhausted_until()
    window_used = db.runs_started_since(WINDOW_HOURS)
    week_used = db.runs_started_since(24 * 7)

    versions = []
    for v in db.all_versions():
        shares = db.stamp_shares(v["version"])
        pv = per_version.get(v["version"], {"plays": 0, "median_pipes": 0})
        versions.append({
            "version": v["version"], "name": v["name"],
            "votes": votes.get(v["version"], 0),
            "stamps": shares,
            "delight_share": (round(shares["delight"] / shares["total"], 3)
                              if shares["total"] else None),
            "plays": pv["plays"], "median_pipes": pv["median_pipes"],
        })

    reruns = []
    for v in db.all_versions():
        for r in db.reigns(v["version"]):
            if r["kind"] == "rerun":
                reruns.append({"version": v["version"], **r})
    reruns.sort(key=lambda r: r["started_at"], reverse=True)

    return {
        "schema": 1,
        "min_sample": MIN_SAMPLE,
        "live": state,
        "versions": versions,
        "participation": db.participation(),
        "deaths": db.death_heatmap(),
        "pile": {
            "pending": db.pending_idea_count(),
            "cap": cfg["pile_cap"],
            "ideas": [
                {"id": r["id"], "text": r["text"], "votes": r["votes"],
                 "created_at": r["created_at"]}
                for r in db.ideas_with_votes("pending")
            ],
        },
        "reruns": reruns[:10],
        "ledger": {
            "window_hours": WINDOW_HOURS,
            "runs_per_window": RUNS_PER_WINDOW,
            "runs_per_week": RUNS_PER_WEEK,
            "window_slots_left": max(0, RUNS_PER_WINDOW - window_used),
            "week_slots_left": max(0, RUNS_PER_WEEK - week_used),
            "exhausted_until": exhausted,
            "recent_runs": [
                {"status": r["status"], "action": r["action"], "version": r["version"],
                 "turns": r["turns"], "tokens": r["tokens"],
                 "summary": (r["summary"] or "")[:200], "finished_at": r["finished_at"]}
                for r in db.last_runs(5)
            ],
        },
        "config": cfg,
        "notes": [
            f"numbers with n below {MIN_SAMPLE} are gossip, not evidence.",
            "there is no negative reward. silence and rollback are the absence of preference.",
        ],
    }


def _validate_config_changes(raw: dict) -> dict[str, str]:
    """Clamp-check proposed policy changes. Rejects the whole batch on any
    out-of-range value — the agent does not get partial credit."""
    if not isinstance(raw, dict):
        raise HTTPException(400, "config must be an object of knob: value.")
    changes: dict[str, str] = {}
    for key, value in raw.items():
        clamp = db.CONFIG_CLAMPS.get(key)
        if clamp is None:
            raise HTTPException(400, f"'{key}' is not a knob. the knobs are documented.")
        if len(clamp) == 3:
            lo, hi, cast = clamp
            try:
                v = cast(value)
            except (TypeError, ValueError):
                raise HTTPException(400, f"'{key}' must be a number. this is not negotiable.")
            if not (lo <= v <= hi):
                raise HTTPException(400, f"'{key}'={v} is outside its clamp [{lo}, {hi}]. rejected.")
            changes[key] = str(v)
        else:  # stamp label
            label = _clean_text(value, 40)
            if not label or not label.isascii():
                raise HTTPException(400, f"'{key}' must be 1-40 plain ascii characters. no emoji. ever.")
            changes[key] = label
    # wheel weights must still sum to 1 after the change
    if any(k.startswith("wheel_") for k in changes):
        cfg = db.get_config()
        total = sum(float(changes.get(k, cfg[k]))
                    for k in ("wheel_nothing", "wheel_rerun", "wheel_summon"))
        if not 0.999 <= total <= 1.001:
            raise HTTPException(400, f"wheel weights sum to {total:.3f}, not 1. the wheel does not lie.")
    return changes


@app.post("/api/agent/complete")
async def agent_complete(request: Request, authorization: str = Header(None)):
    _check_agent_auth(authorization)
    body = await request.json()

    outcome = body.get("outcome") or body.get("status")
    if outcome not in ("success", "failed", "capacity_exhausted"):
        raise HTTPException(400, "outcome must be success | failed | capacity_exhausted.")
    action = body.get("action")
    if outcome == "success" and action not in ("release", "polish", "rollback", "retune", "decline"):
        raise HTTPException(400, "action must be release | polish | rollback | retune | decline.")

    version = _int_or_none(body.get("version"), 1, 100_000)
    name = _clean_text(body.get("name", ""), 80) or None
    idea_id = _int_or_none(body.get("idea_id"), 1, 2**53)
    hypothesis = _clean_text(body.get("hypothesis", ""), 500) or None
    summary = _clean_text(body.get("summary", ""), 2000)
    turns = _int_or_none(body.get("turns"), 0, 100_000)
    tokens = _int_or_none(body.get("tokens"), 0, 2**53)
    rollback_to = _int_or_none(body.get("rollback_to"), 1, 100_000)

    # validate policy changes BEFORE closing the run, so a clamp violation
    # rejects the whole report and the workflow can retry without the config
    config_changes = _validate_config_changes(body.get("config") or {})

    run_id = db.complete_run(outcome, action, version, name, idea_id,
                             hypothesis, summary, turns, tokens)

    if outcome == "success":
        if action in ("release", "polish"):
            if not version:
                raise HTTPException(400, "a release with no version number. filed under fiction.")
            db.add_version(version, name or f"v{version}", summary)
            if idea_id:
                db.mark_idea_implemented(idea_id, version)
            db.set_flagship(version)
            bust_game_cache()
            log.info("v%s '%s' SHIPPED (run #%s)", version, name, run_id)
        elif action == "rollback":
            if not rollback_to or not db.version_row(rollback_to):
                raise HTTPException(400, "cannot roll back to a version that never existed.")
            db.set_flagship(rollback_to)
            bust_game_cache()
            log.info("ROLLBACK: flagship is now v%s (run #%s)", rollback_to, run_id)

        if config_changes:
            db.set_config(config_changes, source=f"run #{run_id}",
                          note=_clean_text(body.get("config_note", ""), 200) or None)
        for d in body.get("declines") or []:
            did = _int_or_none(d.get("idea_id"), 1, 2**53)
            reason = _clean_text(d.get("reason", ""), 300) or "no reason given. noted."
            if did:
                db.decline_idea(did, reason)

    elif outcome == "capacity_exhausted":
        # learn from the collision, conservatively: weekly-cap collisions block
        # until the oldest run ages out of the trailing week; window collisions
        # block until the next window.
        if db.runs_started_since(24 * 7) >= RUNS_PER_WEEK:
            oldest = db.oldest_run_in_window(24 * 7)
            if oldest:
                with db.connect() as conn:
                    until = conn.execute(
                        "SELECT datetime(?, '+7 days') AS t", (oldest["created_at"],)
                    ).fetchone()["t"]
                db.mark_exhausted_until_absolute(until)
        else:
            db.mark_exhausted_until(f"+{int(WINDOW_HOURS)} hours")
        log.info("run #%s hit the capacity wall; ledger marked exhausted", run_id)

    return {"ok": True, "run_id": run_id}


@app.post("/api/admin/trigger")
async def admin_trigger(authorization: str = Header(None)):
    """Manual summons, same auth as the agent. Ignores the wheel, not the
    one-developer rule."""
    _check_agent_auth(authorization)
    if db.active_run():
        raise HTTPException(409, "a run is already in flight. one developer.")
    run_id = db.create_run()
    if not _dispatch_dev_cycle_checked(run_id):
        raise HTTPException(502, "github did not pick up the phone")
    return {"ok": True, "run_id": run_id}
