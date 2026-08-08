"""crappy bird: extortion edition — the web app.

Serves the game in a shell that occasionally demands tribute on death,
takes pay-what-you-want money via Stripe Checkout, sells idea-submission
slots (floor(dollars) ideas per payment), keeps the war-chest ledger, and
wakes the AI developer (a GitHub Actions workflow) when the pot crosses
the funding threshold.
"""

import hmac
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response

from . import db

log = logging.getLogger("crappy")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# ------------------------------------------------------------------ config

APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8080").rstrip("/")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")          # "owner/repo"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
FUND_THRESHOLD_CENTS = int(os.environ.get("FUND_THRESHOLD_CENTS", "1000"))
BLOCK_PROBABILITY = float(os.environ.get("BLOCK_PROBABILITY", "0.35"))
MIN_PAYMENT_CENTS = 100
MAX_PAYMENT_CENTS = 50_000  # $500. if someone tries to pay more, they need help, not features.

DEV_MODE = not STRIPE_SECRET_KEY  # no Stripe key -> local playground with fake payments

ROOT = Path(__file__).resolve().parent.parent
GAMES_DIR = ROOT / "games"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# CSP for the game document itself: whatever future versions try to do,
# they cannot phone home. Inline everything, data: URIs ok, zero network.
GAME_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data:; media-src data:; font-src data:; connect-src 'none'; "
    "form-action 'none'; base-uri 'none'"
)

app = FastAPI(title="crappy bird: extortion edition", docs_url=None, redoc_url=None)
db.init_db()

if not AGENT_TOKEN:
    AGENT_TOKEN = secrets.token_hex(32)
    log.warning("AGENT_TOKEN not set — generated an ephemeral one; agent endpoints "
                "will not be reachable across restarts. Set AGENT_TOKEN in the environment.")
if DEV_MODE:
    log.warning("STRIPE_SECRET_KEY not set — DEV MODE is on: /api/dev/pay simulates payments.")


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


async def current_version() -> int:
    text = await _fetch_game_text("latest.json")
    try:
        return int(json.loads(text)["version"])
    except (TypeError, ValueError, KeyError):
        return 1


def bust_game_cache() -> None:
    _cache.clear()


# ------------------------------------------------------------------- pages

def _static(name: str) -> FileResponse:
    return FileResponse(STATIC_DIR / name, media_type="text/html")


@app.get("/", response_class=HTMLResponse)
async def shell():
    return _static("index.html")


@app.get("/thanks", response_class=HTMLResponse)
async def thanks():
    return _static("thanks.html")


@app.get("/ideas", response_class=HTMLResponse)
async def ideas_page():
    return _static("ideas.html")


@app.get("/changelog", response_class=HTMLResponse)
async def changelog_page():
    return _static("changelog.html")


@app.get("/play/latest", response_class=HTMLResponse)
async def play_latest():
    v = await current_version()
    return await play_version(v)


@app.get("/play/v{version}", response_class=HTMLResponse)
async def play_version(version: int):
    if not 1 <= version <= 100_000:
        raise HTTPException(404)
    text = await _fetch_game_text(f"index.v{version}.html")
    if text is None:
        raise HTTPException(404, "that version of the bird does not exist")
    return HTMLResponse(text, headers={"Content-Security-Policy": GAME_CSP})


@app.get("/download")
async def download():
    v = await current_version()
    text = await _fetch_game_text(f"index.v{v}.html")
    if text is None:
        raise HTTPException(404)
    return Response(
        text,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="crappy-bird-v{v}.html"'},
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# --------------------------------------------------------------------- API

@app.get("/api/state")
async def api_state():
    s = db.stats()
    runs = db.last_runs(5)
    return {
        "version": await current_version(),
        "pot_cents": s["pot_cents"],
        "threshold_cents": FUND_THRESHOLD_CENTS,
        "gross_cents": s["gross_cents"],
        "spent_cents": s["spent_cents"],
        "payments": s["payments"],
        "pending_ideas": s["pending_ideas"],
        "implemented_ideas": s["implemented_ideas"],
        "block_probability": BLOCK_PROBABILITY,
        "dev_mode": DEV_MODE,
        "developing": db.active_run() is not None,
        "last_runs": [
            {
                "status": r["status"], "version": r["version"],
                "spend_cents": r["spend_cents"], "summary": r["summary"],
                "finished_at": r["finished_at"],
            }
            for r in runs
        ],
    }


@app.get("/api/changelog", response_class=PlainTextResponse)
async def api_changelog():
    text = await _fetch_game_text("CHANGELOG.md")
    return text or "no history. suspicious."


@app.get("/api/ideas/public")
async def api_ideas_public():
    return [
        {
            "id": r["id"], "text": r["text"], "status": r["status"],
            "version": r["version_implemented"], "created_at": r["created_at"],
        }
        for r in db.all_ideas()
    ]


# ------------------------------------------------------------------ Stripe

@app.post("/api/checkout")
async def create_checkout(request: Request):
    body = await request.json()
    try:
        amount = int(body.get("amount_cents", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "amount_cents must be an integer")
    if amount < MIN_PAYMENT_CENTS:
        raise HTTPException(400, "the bird's dignity has a floor: $1 minimum")
    if amount > MAX_PAYMENT_CENTS:
        raise HTTPException(400, "that's too much. genuinely. seek help. ($500 max)")

    if DEV_MODE:
        raise HTTPException(400, "dev mode: use /api/dev/pay")

    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    ideas = amount // 100
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "quantity": 1,
            "price_data": {
                "currency": "usd",
                "unit_amount": amount,
                "product_data": {
                    "name": "crappy bird ransom",
                    "description": (
                        f"Unblocks one (1) fake 5-minute timeout and buys {ideas} "
                        f"feature idea{'s' if ideas != 1 else ''} injected directly into an "
                        "unsupervised AI developer. No refunds. No dignity."
                    ),
                },
            },
        }],
        success_url=f"{APP_BASE_URL}/thanks?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{APP_BASE_URL}/?cancelled=1",
    )
    return {"url": session.url}


def _net_cents(amount_cents: int) -> int:
    """Estimated post-Stripe-fee revenue (2.9% + 30c). Reconciled by nobody."""
    return max(0, amount_cents - round(amount_cents * 0.029) - 30)


def _register_paid_session(session_id: str, amount_cents: int) -> None:
    credits = amount_cents // 100
    inserted = db.record_payment(session_id, amount_cents, _net_cents(amount_cents), credits)
    if inserted:
        log.info("payment %s: $%.2f -> %d idea credits", session_id, amount_cents / 100, credits)
        maybe_trigger_dev_cycle()


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    if DEV_MODE:
        raise HTTPException(400, "dev mode: no stripe here")
    import stripe
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(400, "bad signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        if session.get("payment_status") == "paid":
            _register_paid_session(session["id"], int(session["amount_total"]))
    return {"received": True}


@app.get("/api/claim")
async def claim(session_id: str):
    """Called by the thanks page. Falls back to asking Stripe directly if the
    webhook hasn't landed yet, so payers are never stuck staring at a spinner."""
    pay = db.payment_by_session(session_id)
    if pay is None and not DEV_MODE and session_id.startswith("cs_"):
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.error.StripeError:
            raise HTTPException(404, "unknown payment")
        if session.get("payment_status") == "paid":
            _register_paid_session(session["id"], int(session["amount_total"]))
            pay = db.payment_by_session(session_id)
    if pay is None:
        raise HTTPException(404, "unknown payment")
    return {
        "amount_cents": pay["amount_cents"],
        "credits": pay["credits"],
        "credits_left": pay["credits"] - pay["credits_used"],
    }


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@app.post("/api/ideas")
async def submit_idea(request: Request):
    body = await request.json()
    session_id = str(body.get("session_id", ""))[:255]
    text = _CONTROL.sub("", str(body.get("text", ""))).strip()
    if not text:
        raise HTTPException(400, "an empty idea. bold, but no.")
    if len(text) > 500:
        raise HTTPException(400, "500 characters max. constraints breed creativity.")
    ok, result = db.add_idea(session_id, text)
    if not ok:
        raise HTTPException(400, str(result))
    # the pot may already be funded and waiting on its first idea
    maybe_trigger_dev_cycle()
    return {"ok": True, "credits_left": result}


# ---------------------------------------------------------------- dev mode

@app.post("/api/dev/pay")
async def dev_pay(request: Request):
    """Fake payment for local dev. Only exists when Stripe is not configured."""
    if not DEV_MODE:
        raise HTTPException(404)
    body = await request.json()
    amount = int(body.get("amount_cents", 100))
    amount = max(MIN_PAYMENT_CENTS, min(MAX_PAYMENT_CENTS, amount))
    session_id = f"dev_{secrets.token_hex(8)}"
    _register_paid_session(session_id, amount)
    # relative on purpose: dev mode must work regardless of APP_BASE_URL
    return {"url": f"/thanks?session_id={session_id}"}


# ---------------------------------------------------- the dev-cycle trigger

def maybe_trigger_dev_cycle() -> None:
    pot = db.pot_cents()
    pending = len(db.pending_ideas())
    if pot < FUND_THRESHOLD_CENTS:
        log.info("pot $%.2f < threshold $%.2f — the developer sleeps",
                 pot / 100, FUND_THRESHOLD_CENTS / 100)
        return
    if pending == 0:
        log.info("pot is full but the idea pile is empty — waiting for genius")
        return
    if db.active_run():
        log.info("a run is already in flight")
        return
    if not (GITHUB_REPO and GITHUB_PAT):
        log.warning("pot ready ($%.2f, %d ideas) but GITHUB_REPO/GITHUB_PAT unset — "
                    "cannot wake the developer", pot / 100, pending)
        return
    db.create_run()
    try:
        r = httpx.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/dispatches",
            headers={
                "Authorization": f"Bearer {GITHUB_PAT}",
                "Accept": "application/vnd.github+json",
            },
            json={"event_type": "fund-goal-reached"},
            timeout=15,
        )
        r.raise_for_status()
        log.info("THE DEVELOPER AWAKENS (pot $%.2f, %d ideas pending)", pot / 100, pending)
    except httpx.HTTPError as e:
        log.error("failed to dispatch workflow: %s", e)
        db.complete_run("failed", None, None, 0, f"dispatch failed: {e}")


def _check_agent_auth(authorization: str | None) -> None:
    expected = f"Bearer {AGENT_TOKEN}"
    if not (authorization and hmac.compare_digest(authorization, expected)):
        raise HTTPException(401, "no")


@app.get("/api/agent/ideas")
async def agent_ideas(authorization: str = Header(None)):
    _check_agent_auth(authorization)
    return [
        {"id": r["id"], "text": r["text"], "created_at": r["created_at"]}
        for r in db.pending_ideas()
    ]


@app.post("/api/agent/complete")
async def agent_complete(request: Request, authorization: str = Header(None)):
    _check_agent_auth(authorization)
    body = await request.json()
    status = body.get("status")
    if status not in ("success", "failed"):
        raise HTTPException(400, "status must be success|failed")
    version = body.get("version")
    idea_id = body.get("idea_id")
    spend_cents = int(body.get("spend_cents", 0))
    summary = str(body.get("summary", ""))[:2000]

    db.complete_run(status, version, idea_id, spend_cents, summary)
    if status == "success" and idea_id:
        db.mark_idea_implemented(int(idea_id), int(version))
        bust_game_cache()
        log.info("v%s SHIPPED (idea #%s, $%.2f incinerated)", version, idea_id, spend_cents / 100)
    else:
        log.info("run failed ($%.2f incinerated for nothing): %s", spend_cents / 100, summary[:200])

    # money may have kept arriving during the run — chain another release
    maybe_trigger_dev_cycle()
    return {"ok": True, "pot_cents": db.pot_cents()}


@app.post("/api/admin/trigger")
async def admin_trigger(authorization: str = Header(None)):
    """Manual kick, same auth as the agent. Ignores the pot threshold (not the idea check)."""
    _check_agent_auth(authorization)
    if not db.pending_ideas():
        raise HTTPException(400, "no pending ideas to implement")
    if db.active_run():
        raise HTTPException(409, "a run is already in flight")
    if not (GITHUB_REPO and GITHUB_PAT):
        raise HTTPException(400, "GITHUB_REPO/GITHUB_PAT not configured")
    db.create_run()
    r = httpx.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/dispatches",
        headers={"Authorization": f"Bearer {GITHUB_PAT}", "Accept": "application/vnd.github+json"},
        json={"event_type": "fund-goal-reached"},
        timeout=15,
    )
    if r.status_code >= 300:
        db.complete_run("failed", None, None, 0, f"manual dispatch failed: HTTP {r.status_code}")
        raise HTTPException(502, f"github said {r.status_code}")
    return {"ok": True}
