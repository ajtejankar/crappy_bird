# crappy bird: extortion edition

A deliberately awful browser game that funds its own AI-driven development.
Players die, are occasionally (randomly) held for a fake 5-minute ransom, pay
what they want ($1 floor) to skip it, and every whole dollar buys one feature
idea fed to an unsupervised AI developer. When the war chest hits $10, a
GitHub Actions workflow boots **Claude Code (Opus 5)**, which reads every idea,
picks the zaniest, implements it as a new version of the game, play-tests it
in a real browser, looks at screenshots of its own work, and ships — no human
in the loop. The money pays for the API tokens. That's the whole company.

```
 player dies ──► random shakedown ──► Stripe PWYW ($1+) ──► war chest + ideas
                                                                │
                          ┌─────────────────────────────────────┘ pot ≥ $10
                          ▼
             repository_dispatch ──► GitHub Actions ──► Claude Code + Opus 5
                          │                                     │
                          │        picks zaniest idea, writes index.v{N+1}.html,
                          │        plays it with Playwright, screenshots it,
                          │        verification gate (size/network/death-hook)
                          ▼                                     │
                 git push to main ◄─────────────────────────────┘
                          │
        web app serves new version from GitHub raw within ~60s
```

## Layout

| path | what |
|---|---|
| `games/index.v{N}.html` | every game version, immutable history, single files ≤100KB |
| `games/latest.json` | which version is live |
| `games/CHANGELOG.md` | the AI developer's public memory |
| `games/CONTRACT.md` | invariants every release must keep |
| `app/` | FastAPI web app: shell, Stripe, ideas, ledger, trigger |
| `agent/AGENT_PROMPT.md` | the mission briefing Claude Code runs with |
| `agent/verify_game.py` | the verification gate (Playwright) |
| `.github/workflows/develop.yml` | the entire development lifecycle |
| `index.html` | the original v1, untouched, for posterity |

## Run it locally (no accounts needed)

```sh
uv sync
uv run uvicorn app.main:app --port 8080 --reload
```

Open http://localhost:8080. With no Stripe key set, **dev mode** is on: the pay
button "charges" fake money instantly so you can test the whole loop —
die → get shaken down → pay $3 → submit 3 ideas → watch the war chest.

Run the verification gate on the current game:

```sh
uv run agent/verify_game.py install     # once, downloads chromium
uv run agent/verify_game.py verify games/index.v1.html
```

---

# Going live — full setup

You need four accounts: GitHub, Anthropic, Stripe, Fly.io. Budget ~45 minutes.

## 1. GitHub (the source of truth + the sandbox)

1. Create a repo, e.g. `you/crappy-bird`, and push this project to `main`.
2. Generate the shared secret the app and workflow use to talk:
   `openssl rand -hex 32` → this is **AGENT_TOKEN**. Keep it handy.
3. Create a **fine-grained PAT** (Settings → Developer settings → Fine-grained
   tokens) scoped to *only this repo*, with permissions:
   - **Contents: Read** (the dispatch API requires repo read)
   - **Actions: Read and write** (to dispatch the workflow)
   This is **GITHUB_PAT** — the web app uses it to wake the developer.
4. In the repo: Settings → Secrets and variables → **Actions** → add secrets:
   - `ANTHROPIC_API_KEY` — from step 2 below
   - `AGENT_TOKEN` — from 1.2
   - `APP_URL` — your app's public URL (from step 4; come back and set it)
5. Settings → Actions → General → Workflow permissions → **Read and write
   permissions** (the workflow pushes the new game version).

## 2. Anthropic (the developer's brain)

1. platform.claude.com → create an API key. This key funds the developer;
   scope it to its own workspace if you can.
2. Billing → **enable auto-reload** (e.g. reload $25 when below $5) so the
   account never runs dry mid-release. There is no API to convert Stripe money
   into credits — the web app's ledger *authorizes* spending; auto-reload
   actually *pays* for it from your card. Same money, one hop later.
3. Set a **monthly spend limit** (e.g. $50) as the blast-radius cap. A release
   costs roughly $2–6 of Opus 5 tokens; the workflow also has a 60-minute
   timeout as a backstop.

## 3. Stripe (the money tube)

1. stripe.com → create an account (sole proprietor is fine). Activate payments.
   Describe the product honestly: *"browser game; optional $1+ payment skips a
   cosmetic timeout and lets players submit feature ideas."* Honest description
   = fewer disputes = Stripe stays happy.
2. Developers → API keys → copy the **secret key** (`sk_live_...`, or
   `sk_test_...` while testing) → **STRIPE_SECRET_KEY**.
3. Developers → Webhooks → **Add endpoint**:
   - URL: `https://<your-app>/api/stripe/webhook`
   - Events: `checkout.session.completed` (that's the only one needed)
   - Copy the **signing secret** (`whsec_...`) → **STRIPE_WEBHOOK_SECRET**.
4. Test end-to-end in test mode first: card `4242 4242 4242 4242`, any future
   date, any CVC. The thanks page also polls Stripe directly, so even if the
   webhook is late the payer isn't stranded.

## 4. Fly.io (the landlord)

```sh
brew install flyctl && fly auth signup     # or fly auth login
fly launch --copy-config --no-deploy      # accept the app name or pick one
fly volumes create crappy_data --size 1   # SQLite lives here
fly secrets set \
  STRIPE_SECRET_KEY=sk_live_... \
  STRIPE_WEBHOOK_SECRET=whsec_... \
  AGENT_TOKEN=<from step 1.2> \
  GITHUB_PAT=<from step 1.3>
# non-secret config:
fly deploy
fly config env   # sanity check
```

Then set the two env values in `fly.toml` under `[env]` and redeploy:

```toml
APP_BASE_URL = "https://<your-app>.fly.dev"
GITHUB_REPO  = "you/crappy-bird"
```

Finally go back to **1.4** and set the `APP_URL` GitHub secret to the same URL.

## 5. Smoke test the whole machine

1. Open the site, die until the shakedown appears, pay $10 with the test card,
   submit a few gloriously stupid ideas.
2. Watch: the app logs `THE DEVELOPER AWAKENS`, the repo's Actions tab shows a
   `dev-cycle` run, and ~5–20 minutes later `main` has `games/index.v2.html`
   and the site serves v2 (60s cache).
3. If the run fails, the failure is *public by design*: the run log shows in
   `/api/state`, the money stays spent, and the changelog gains nothing. Check
   the Actions log and the `dev-cycle-evidence` artifact (screenshots + stderr).
4. Manual kick without waiting for money:
   `curl -X POST https://<app>/api/admin/trigger -H "Authorization: Bearer $AGENT_TOKEN"`
   (needs ≥1 pending idea), or run the workflow from the Actions tab.
5. Flip Stripe to live mode, update the two Stripe secrets, redeploy. Ship it.

## Knobs

| env | default | meaning |
|---|---|---|
| `FUND_THRESHOLD_CENTS` | `1000` | war chest level that wakes the developer |
| `BLOCK_PROBABILITY` | `0.35` | chance a death triggers the shakedown |
| `GITHUB_BRANCH` | `main` | branch game files are served from |

## Security posture (a.k.a. why paid prompt injection is fine here)

Players pay to put arbitrary text in an AI's prompt. Containment is structural,
not polite: the CI sandbox holds only an Anthropic key with a spend cap; the
gate rejects releases that touch anything outside `games/`, exceed 100KB, or
smell like network calls; and the app serves every game under a CSP that blocks
all egress anyway. A successful injection therefore produces, at most, a weird
game feature — which is the product working as intended.
