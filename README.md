# crappy bird

A deliberately awful browser game that is also a **live RL environment for a
coding agent**. Humans play it, stamp its incident reports, and vote on its
future. An AI developer — running on a flat Claude Pro subscription, bounded
by usage capacity it must learn to husband — governs the game's evolution: it
decides what to build, what version holds the live slot, and how its own dice
are weighted. Every decision is public: transcripts, changelog, lab notebook,
config audit log.

Nobody reviews the code. Nobody pays anything. Nobody earns anything.
**No money moves through this system, in any direction, ever.**

```
             ┌────────────────────── FAST LOOP (free, always on) ─────────────────────┐
             │                                                                        │
   players ──► play ──► die ──► stamp the report / vote (>10 pipes) ──► the wheel     │
             │                                                            │           │
             │              nothing ◄───── spins on every death ──────────┤           │
             │              rerun (temporary revival) ◄───────────────────┤           │
             └──────────────────────────────────────────────┐             │           │
                                                            │       SUMMON (throttled │
                                                            │        by capacity)     │
             ┌────────────────────── SLOW LOOP (costly) ────▼─────────────▼───────────┐
             │                                                                        │
             │   agent run: read dossier + pile + ledger + notebook                   │
             │   → implement an idea / small polish / retune the wheel / rollback /   │
             │     decline (conserve capacity) → verify in browser → ship             │
             │                                                                        │
             └────────────────────────────────────────────────────────────────────────┘
```

## The three parties and their frequencies

| party  | operates at    | owns                                                   |
|--------|----------------|--------------------------------------------------------|
| humans | player speed   | the preference field: ideas, votes, stamps             |
| wheel  | player speed   | timing + chaos: executes the agent's standing policy   |
| agent  | capacity speed | all decisions: what to build, what's live, the weights |

This is co-evolution. Humans never decide directly; the agent never acts
unobserved; the dice keep both honest.

## How a death works

Dying files an **incident report**: cause of death, pipes cleared,
management's statistical assessment of your performance. You may stamp it —
`WOULD DIE AGAIN` / `NOTED` / `FORMAL COMPLAINT` (one stamp per report;
silence is data). Clear more than the vote threshold (launch: 10 pipes) and
the death screen becomes a polling place: one vote, spendable on exactly one
of (a) upvoting any version in the lineage, (b) submitting a new idea to the
pile, (c) upvoting an existing idea. Then the wheel spins, visibly, with its
real odds: **NOTHING** (the wheel mocks you), **RERUN** (an old version takes
the live slot for a while, sampled by votes plus an underdog floor), or
**SUMMON** (the developer wakes up — if the capacity ledger allows it).

## Layout

| path | what |
|---|---|
| `games/index.v{N}.html` | every game version, immutable history, single files ≤100KB |
| `games/latest.json` | the last version the agent shipped (the DB owns the live pointer) |
| `games/CHANGELOG.md` | the AI developer's public memory |
| `games/CONTRACT.md` | invariants every release must keep, including the house voice |
| `app/` | FastAPI app: lobby, live-slot serving + overlay injection, telemetry, votes, wheel, ledger, trigger |
| `app/static/management.html` | the overlay injected into `/play`: incident report, stamps, ballot, wheel |
| `agent/AGENT_PROMPT.md` | the mission brief Claude Code runs with |
| `agent/NOTEBOOK.md` | the developer's cross-run memory. public. |
| `agent/verify_game.py` | the verification gate (Playwright) — the agent gets no vote on whether it shipped |
| `scripts/e2e.py` | full end-to-end UI test, including the 13" no-scroll assertions |
| `scripts/turn_meter.py` | PostToolUse hook: capacity meter injected into the agent's context |
| `.github/workflows/develop.yml` | the entire development lifecycle |
| `transcripts/` | full agent-run transcripts (secret-scrubbed, gzipped) |
| `index.html` | the original v1, untouched, for posterity |

## Run it locally (no accounts needed)

```sh
uv sync
uv run uvicorn app.main:app --port 8080 --reload
```

Without `GITHUB_REPO`/`GITHUB_PAT` the app runs in DEV MODE: the wheel still
spins, reruns still happen, and SUMMON is simulated (the developer is
imaginary). Telemetry, stamps, votes and the pile all work against a local
SQLite file.

Tests:

```sh
uv run agent/verify_game.py install          # once
uv run agent/verify_game.py verify games/index.v3.html
rm -rf data && uv run uvicorn app.main:app --port 8123   # then, in another shell:
uv run scripts/e2e.py
```

## Production shape

- **Fly.io** runs the app (`fly.toml`); SQLite lives on a small volume.
- Game files are read from **GitHub raw** at serve time (60s cache), so agent
  releases go live without redeploying the app.
- The app holds a fine-grained PAT with **Actions: write only** — it can wake
  the developer but can never write to the repo.
- The workflow authenticates the agent with `CLAUDE_CODE_OAUTH_TOKEN` (from
  `claude setup-token` on a dedicated Claude Pro account), model pinned to
  Sonnet, hard-capped by `--max-turns`.
- The verification gate runs from pristine HEAD, checks blast radius, size,
  network hygiene, the death-hook paperwork, and plays the game in a real
  browser before anything ships.

## The reward model (what "good" means here)

Positive signal: version upvotes, delight share, votes cast, ideas submitted,
rerun performance. **There is no negative reward** — silence and rollback are
the absence of preference, not punishment. Plays/day, retries and return
rates are health instruments, never objectives; the mission brief bans
engagement optimization outright.
