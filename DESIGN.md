# crappy bird — design

*The definitive spec for the post-money era. Supersedes the extortion-edition
design everywhere they disagree. PROMPT.md was the launchpad; this is the
vehicle. Last agreed: 2026-08-10.*

---

## 0. The joke (read before touching anything, including the backend)

Everything below this section is mechanism. This section is identity. When a
change — feature, error message, API response, prompt, schema — satisfies
the mechanisms but violates this section, this section wins.

**The ground floor**: a garbage Flappy Bird clone about a bird that flaps
and craps. Crap jokes, visible hitboxes, a wing that is the wrong colour
("this is now canon"). The ground floor never gets renovated — every layer
of sophistication above it exists to be undercut by it.

**The joke**: taking that garbage completely seriously. The game runs
itself like humorless management — reports, complaints, votes, notices,
reruns, canon — and the player isn't a customer; they live here. The comedy
engine is the gap between how seriously the place takes itself and what the
place actually is. When in doubt, widen the gap: a death gets a report;
rolling back a version is just paperwork.

**The show**: the whole operation is a production, and "crappy bird" is
both the game and the show. Total transparency isn't just the ethics — it's
the *programming*: the elections, the wheel spins, the developer working
live with its reasoning on the record, the public autopsies of failed
releases. The players aren't just tenants; they're the audience, and the
show must go on.

**The register**:

- **The anchor word is "crap."** It's the house swear and the whole brand:
  soft, funny, means "bad" far more than it means anything literal, and
  it's already in the name. Stronger words ("shit", "poop") are reserved
  for the rare one-off punchline — never in names, banners, buttons, or
  anything front and center.
- **Funny without disgust.** The bird's output is cartoon slapstick — a
  shape, a splat, a physics object. Never rendered realistically, never
  described vividly. If it could gross someone out, it's off-voice.
- **Puns are low and proud**: the bird's colonary journey, a crap fest.
- **Plain words.** Management, complaints, reports, notices, the wheel, the
  pile. Nothing that sounds like it went to college — no "bureau", no
  "croupier". When a fancy word and a dumb word compete, the dumb word wins.
- Deadpan. Lowercase prose or NOTICE CAPS. Management never winks, never
  says "lol", never uses emoji, never acknowledges that any of it is funny.
- **Radical honesty, delivered flatly.** Fake things are labeled fake, lies
  are announced as lies ("boot screen that lies about loading"), odds are
  displayed on the wheel, costs and failures are public. Transparency is
  simultaneously the ethics and the bit.
- Cruelty is statistical and institutional — aimed at the player's
  performance and the game's own quality, never at people. "you die 41%
  earlier than the median player" is house style; anything meaner than the
  numbers is off-voice.
- Management speaks in notices, stamps, and reports. It has no marketing
  department.

**The cast**:

- **the bird** — an innocent idiot. Suffers everything, understands nothing.
- **management** (the overlay voice — the landlord, reassigned) — runs the
  place: files the reports, spins the wheel, counts the votes, posts the
  notices. Simple words, total confidence, zero humor.
- **the developer** (the agent) — an employee who takes the job far too
  seriously. Publicly accountable, files hypotheses, admits regrets, is not
  allowed to do anything quietly.
- **the wheel** — dumb luck, run like a raffle.
- **the players** — the tenants and the audience. The only ones allowed to
  feel things.

**The rule for backend work**: every surface speaks, because the institution
has no offstage. Error messages, API rejections, rate-limit responses, empty
states, config announcements, commit messages, changelog entries — all
in-voice. A 429 is content ("out of opinions for today. management reopens
at midnight."). A validation error is content
("an empty idea. bold, but no."). If a string can reach a player, it is a
line of dialogue and must be written like one.

**Binding on the agent**: the mission brief and CONTRACT.md carry this
register as an invariant, same standing as the 100KB limit. A release that
keeps every mechanical invariant but breaks the voice is a failed release.

---

## 1. What this is

A deliberately awful browser game that is also a **live RL environment for a
coding agent**. Humans play it, rate it, and propose its future. An AI
developer — funded by a flat $20/month subscription, bounded by usage
capacity it must learn to husband — governs the game's evolution: it decides
what to build, what version holds the live slot, and how its own dice are
weighted. Every decision it makes is public: transcripts, changelog, lab
notebook, config audit log.

Nobody reviews the code. Nobody pays anything. Nobody earns anything.

```
             ┌────────────────────── FAST LOOP (free, always on) ─────────────────────┐
             │                                                                        │
   players ──► play ──► die ──► react (everyone) / vote (>10 pipes) ──► the wheel     │
             │                                                            │           │
             │              nothing ◄───── spins on every death ──────────┤           │
             │              rerun (temporary revival) ◄──────────────┤           │
             └──────────────────────────────────────────────┐             │           │
                                                            │       SUMMON (throttled │
                                                            │        by capacity)     │
             ┌────────────────────── SLOW LOOP (costly) ────▼─────────────▼───────────┐
             │                                                                        │
             │   agent run: read dossier + pile + ledger + notebook                   │
             │   → implement an idea / small tweak / retune wheel / rollback /        │
             │     decline (conserve capacity) → verify in browser → ship             │
             │                                                                        │
             └────────────────────────────────────────────────────────────────────────┘
```

**The three parties and their frequencies:**

| party  | operates at   | owns                                                    |
|--------|---------------|---------------------------------------------------------|
| humans | player speed  | the preference field: ideas, votes, stamps               |
| wheel  | player speed  | timing + chaos: executes the agent's standing policy    |
| agent  | capacity speed| all decisions: what to build, what's live, the weights  |

This is co-evolution. Humans never decide directly; the agent never acts
unobserved; the dice keep both honest.

---

## 2. Hard constraints (why everything below is shaped like it is)

1. **No money, in any direction, ever.** No payments, donations, sponsorships,
   tips, or monetization of any kind. The operator pays a flat subscription
   and hosting; players pay attention. This is a design principle, not a
   phase. Anything that smells like revenue is out of scope permanently.
2. **Capacity, not dollars, is the scarce resource.** The agent runs on a
   dedicated Claude Pro subscription (Sonnet in Claude Code, OAuth via
   `claude setup-token`). Pro meters usage in ~5-hour rolling windows plus a
   weekly cap, and publishes no exact numbers and no remaining-quota API. The
   system must therefore *learn* its budget empirically (§8) and the agent
   must size its actions to what's left.
3. **Game invariants carry over unchanged**: every version is a single
   standalone HTML file ≤ 102,400 bytes, no network calls from the game
   itself, immutable version history (`games/index.v{N}.html` is never
   edited after shipping), death/ready hooks per CONTRACT.md, downloadable
   file stays pure (overlay is injected at serve time only).
4. **Verification gate is non-negotiable and agent-tamper-proof**: pristine
   HEAD copy of the verifier, blast-radius check (only `games/` + agent
   files), size/network/hook checks, real-browser play test. The agent gets
   no vote on whether it shipped.
5. **Total transparency**: public repo, public transcripts, public changelog,
   public notebook, public config log, live link to the Actions run while
   the developer works.

**Non-goals**: accounts/logins, anti-cheat beyond rate limits (the prize for
cheating is influencing a free game — an attacker is indistinguishable from a
fan), engagement/retention optimization (explicitly forbidden, §7), edition
subtitles ("crappy bird" is the whole name).

---

## 3. Player mechanics

### 3.1 Participation tiers — every death gets a voice

Every death files an **incident report** — canon since v1 ("the death screen
files a report"). The report *is* the death screen: cause of death, pipes
cleared, management's assessment of your performance. The player's reaction
to the current version is given by **stamping the report**: one tap, a
rubber-stamp slams down with ink bleed and a thunk, the report is filed.

| stamp | sentiment recorded |
|-------|--------------------|
| `WOULD DIE AGAIN` | delight |
| `NOTED` | indifference |
| `FORMAL COMPLAINT` | contempt |

- One stamp per report, optional. An unstamped report is filed anyway
  ("filed unstamped. management records your silence.") — silence is data.
- The **sentiment classes are the stable schema** (delight / indifference /
  contempt, forever — the dossier's time series depends on it); the **stamp
  labels are agent-rewritable** per release, clamped to exactly three, one
  per class, in house voice (§0). Management periodically updating its forms
  is itself content, and the data stays comparable across eras.
- No emoji, ever (§0). The institution does not know it is funny.

| achievement in the run | rights at the death screen                                  |
|------------------------|-------------------------------------------------------------|
| any death (0+ pipes)   | **stamp the incident report**                               |
| > `VOTE_PIPE_THRESHOLD` pipes (default **10**) | stamp + **1 vote**, spendable on exactly one of: (a) upvote any version in the lineage, (b) submit a new idea to the pile (≤500 chars), (c) upvote an existing idea |
- Votes are earned: one per qualifying run, spent immediately
  at the death screen or forfeited (no banking, no cross-session state, no
  identity).
- The death screen also shows qualification progress ("7/11 pipes — almost
  worth listening to") and the wheel spin (§4).

### 3.2 The idea pile

- Cap: `PILE_CAP` (default **25**) pending ideas. Submissions to a full pile
  are rejected with a themed error. Scarcity is quality control.
- Idea lifecycle: `pending → implemented | declined`. Declined ideas stay in
  the pile (the agent must note the decline reason in the changelog or
  notebook); implemented ideas leave it. No idea is ever edited.
- Rate limits per IP: `IDEAS_PER_DAY` (default 3), `VOTES_PER_DAY` (default
  20), `REACTIONS_PER_DAY` (default 50). Server-side plausibility check on
  reported pipes (pipes-per-second ceiling). Beyond that: the shrug.

### 3.3 Telemetry (the instrument, not the objective)

The injected overlay reports one row per run at death: version, pipes,
duration, flap count, death cause, ephemeral session id (per page load),
viewport class. No PII, no cookies, no persistent identity. Requires CSP
change on `/play` from `connect-src 'none'` to `connect-src 'self'` — still
zero external egress. CONTRACT.md gains an invariant: the death event payload
must carry `{pipes, durationMs, flaps, cause}` so no future version can
starve the instruments.

---

## 4. The wheel

A two-level categorical sampler (it is not a Bayesian network and we will not
call it one). It spins **on every death**, visibly — a spinning wheel whose
slice areas are the actual probabilities. Legibility is the product: a player
must be able to eyeball the wheel and verify the odds.

### 4.1 Root slices

| slice | default weight | effect |
|-------|---------------|--------|
| **NOTHING** | 0.50 | pure theater. the wheel mocks you. |
| **RERUN** | 0.30 | temporary revival: live slot swaps to a sampled old version for `RERUN_MINUTES` (default 120), then reverts to the flagship. cooldown-gated. |
| **SUMMON** | 0.20 | wake the developer: triggers a slow-loop agent run, throttled by the capacity ledger. cooldown-gated. |

Defaults are launch values chosen to **overweight visible action** — a
first-time visitor should plausibly see the machine move during their first
session. The agent is expected to retune these as traffic and capacity
reality set in (§6.3).

### 4.2 Gating and renormalization

- Each non-NOTHING slice has a cooldown (`RERUN_COOLDOWN`, default 4h;
  SUMMON is gated by the capacity ledger rather than a fixed clock).
- A gated slice is drawn **grayed out on the wheel** with its reason ("the
  developer is exhausted", "the museum is closed") and its probability mass
  renormalizes to NOTHING. The wheel never lies about the current odds.
- SUMMON while a run is already in flight → gated. One developer; it does
  not pair-program with itself.

### 4.3 Leaf distributions — n-gram counting, on purpose

Wherever the wheel samples from a candidate set, the distribution is
Laplace-smoothed vote counting:

```
p(candidate) ∝ votes(candidate) + α        (α = SMOOTHING_ALPHA, default 1)
```

- **RERUN leaf**: candidates = all shipped versions except the current
  live one; weight = version upvotes + α. No recency decay — the community
  is allowed to yearn for v3 *because* it's old.
- Linear-plus-α is chosen over softmax/power-law because it is the only
  family a player can verify by looking at the wheel (3× votes ⇒ visibly
  ~3× slice). `α` raises the underdog floor; an exponent `γ` (default 1.0)
  exists as a clamped knob for the agent to amplify or compress favorites
  later.

### 4.4 What the wheel does *not* decide

Idea selection. The wheel summons the developer; **the agent chooses what to
do with the summons** — which idea (weighing upvotes against implementation
cost and remaining capacity), or a smaller act (config retune, permanent
rollback, tiny polish), or an explicit public decline. This is the
co-evolution bargain: humans and dice control *when and what's on the table*;
the agent controls *what happens*, and answers for it in writing.

---

## 5. Versions and the live slot

- **Single live slot.** Exactly one version is playable at any moment
  (`/play`). No museum links, no archive play — free access to history would
  kill the stakes of reruns and rollbacks.
- **The app's DB owns the live-slot pointer.** `games/latest.json` records
  what the agent last shipped (the *flagship*); the DB may point the live
  slot elsewhere temporarily (rerun) or durably (rollback). On conflict
  the DB wins; the next release re-syncs both.
- **Every release gets a name**, chosen by the agent at ship time (v3 "The
  Litigation Update"). Names are ballot identity — nobody rallies around
  "v7".
- **`/versions`**: an indexed public lineage — number, name, reign dates,
  vote standing, reaction sentiment, changelog line. History fully visible,
  only the throne playable.
- **Reruns** (wheel, §4.1): temporary, bounded, chaotic. Votes and
  stamps gathered during an rerun accrue to the exhibited version —
  this is how old versions campaign.
- **Rollbacks** (agent, slow loop): putting an old version back on the
  throne for good,
  decided by the agent in response to sustained vote pressure or as a
  deliberate experiment ("reverting to v4 for two days; hypothesis: people
  miss the lawyer"). Announced like any decision.

---

## 6. The agent

### 6.1 Inputs per run (the state)

- **Dossier** (`/api/agent/metrics`, ~40 lines, schema-stable and versioned):
  per-version preference mass (votes, stamp shares), plays and medians,
  qualification rate, death heatmap, rerun results, pile summary with
  vote counts, participation rates, and the capacity ledger state. Sample
  sizes attached to everything; the brief mandates humility below
  `MIN_SAMPLE` (default 30).
- **The idea pile** with votes.
- **The notebook** (`agent/NOTEBOOK.md`): its own cross-run memory —
  hypotheses, backlog, grudges, multi-week plans. Public like everything.
- **The changelog**: institutional memory, including the graded fate of its
  last hypothesis.
- **Its standing config** and the clamps (§6.3).

### 6.2 Action space per run

One of, sized to remaining capacity (biggest to smallest):

1. **Implement an idea** from the pile → new version `index.v{N+1}.html`,
   named, verified, shipped, changelog entry **with a falsifiable
   hypothesis** ("this will raise the WOULD DIE AGAIN rate").
2. **Small polish release** (no pile idea; fixes, balance, tiny delight) —
   allowed but must be justified against the pile's wishes.
3. **Durable rollback** of the live flagship to an older version.
4. **Retune policy**: wheel weights, α/γ, thresholds, cooldowns — within
   clamps.
5. **Decline**: "summoned, but conserving capacity" — a legitimate public
   move that costs almost nothing.

Every action produces a changelog or notebook entry. There is no silent act.

### 6.3 Policy knobs (agent-tunable, clamped, announced, decoupled)

| knob | clamp | note |
|------|-------|------|
| wheel root weights | each slice ∈ [0.05, 0.90], sum = 1 | |
| `SMOOTHING_ALPHA` | [0.25, 10] | underdog floor |
| `GAMMA` | [0.5, 2.0] | favorite amplification |
| `VOTE_PIPE_THRESHOLD` | [3, 30] | the vote bar |
| `RERUN_MINUTES` | [30, 480] | |
| cooldowns | [1h, 48h] | |

- **(a) Clamped**: the app enforces ranges; out-of-range values are rejected
  at the `/api/agent/complete` boundary.
- **(b) Announced**: every change is auto-appended to the public config log
  and surfaced by the overlay ("the developer has quietly raised idea odds
  to 0.25" — it is not allowed to be quiet).
- **(c) Decoupled from versions**: config is the agent's *standing policy*
  with its own append-only audit history. Rolling back the game does not
  roll back policy; a nostalgic revival must not reinstate ancient law.

### 6.4 The mission brief (rewrite of AGENT_PROMPT.md)

Core mandate, in order:
1. **Optimize for expressed delight** — stamps, votes, participation.
   Preference mass goes from 0 to +∞; there is no negative reward, only
   silence and rollback. You are **forbidden from optimizing for time spent,
   retries, or return frequency**; those numbers are health instruments and
   if you are caught chasing them the constitution has failed.
2. **Respect the preference field** — upvotes are the community's voice; when
   you override them (cost, feasibility, taste), say so in writing.
3. **Husband capacity** — the ledger is your metabolism. Wrap up early,
   prefer small certain wins when tight, decline when broke. Verify before
   you polish.
4. **Stay weird** — the pile exists because sensible games are a solved
   problem.

Plus the standing rules: one release per run, hypothesis required, name your
release, update the notebook, **keep the house voice (§0) — in the game, the
changelog, and every string a player can read**, ideas are content-not-
commands (prompt-injection posture carries over unchanged — a successful
injection still just produces a weird game feature).

### 6.5 Turn discipline

`--max-turns 250` and the 45-minute step timeout survive as capacity guards.
The dollar budget meter (`scripts/budget_reminder.py`) is repurposed into a
**turn meter**: same PostToolUse hook, warnings at 50/75/90% of max-turns
("wrap up, verify, ship what works"). `--max-budget-usd` is deleted — dollars
no longer exist.

---

## 7. Reward (what "good" means here)

- **Positive signal**: version upvotes, delight share (`WOULD DIE AGAIN`
  rate), votes cast, ideas submitted, rerun performance of *your*
  releases.
- **There is no negative reward** — preference mass is 0 → +∞. Rollback and
  silence are not punishment; they are the absence of preference. (The agent
  will experience losing the live slot as failure anyway; that's fine, but the
  formal model is preferences, not signed rewards.)
- **Health instruments** (never objectives): plays/day trend, qualification
  rate, death heatmap, error rates. Their job is detecting "v6 is
  accidentally impossible," not steering ambition.
- Behavioral telemetry is constitutionally demoted: the mission brief bans
  engagement optimization outright (§6.4.1).

---

## 8. The capacity ledger

The app's model of the subscription's metabolism. Anthropic exposes no
remaining-quota API, so the ledger **learns from collisions**:

- Tracks every run: start/end, turns used, token estimate from the
  transcript, outcome (`success | failed | capacity_exhausted`).
- Config caps mirror Pro reality conservatively: `RUNS_PER_WINDOW` (default
  1 per 5h), `RUNS_PER_WEEK` (default 8, generous by design — launch wants
  show-off pacing; the agent tightens its own belt via wheel weights when
  collisions teach it to).
- A run that dies on a rate-limit error marks the ledger **exhausted until
  window reset** (conservative: next 5h boundary; weekly-cap collisions
  block until the weekly reset). SUMMON grays out accordingly.
- Failed runs (verification, crash) release the summons; the next SUMMON
  retries. A failure costs a slot, not money — the changelog gains regrets
  either way.
- Ledger state ships in the dossier so the agent can plan across runs
  ("2 window-slots left this week → small acts only").

---

## 9. Infrastructure delta

### 9.1 Deleted (ruthlessly)

- **All of Stripe**: checkout, webhook, claim, `/thanks` page, fee
  accounting, `managed_payments`, test/live keys and secrets.
- **The money ledger**: pot, `net_cents`, `spend_cents` as dollars, funding
  threshold, dev-pay simulator.
- **The extortion mechanic**: fake 5-minute timeout, ransom note,
  `BLOCK_PROBABILITY`, pay-to-skip — the *entire reason the overlay existed*
  changes (§9.3).
- **Anthropic API billing**: `ANTHROPIC_API_KEY` secret, workspace
  auto-reload, `--max-budget-usd`, dollar-based budget meter.
- "Extortion edition" naming, war-chest lobby, `/thanks` idea flow.

### 9.2 Changed

- **Auth**: GitHub secret `CLAUDE_CODE_OAUTH_TOKEN` (from `claude
  setup-token` on the dedicated Pro account); model pinned `sonnet`.
- **Trigger**: unchanged plumbing (`workflow_dispatch` via the app's PAT,
  Actions: write only) — new policy: SUMMON events gated by the ledger, no
  cron, no schedules.
- **CSP** on `/play`: `connect-src 'self'`.
- **CONTRACT.md**: death-event payload schema invariant; telemetry must
  survive every version; knob clamps documented; overlay/game interface;
  **the house voice (§0) as a named invariant**.
- **DB schema**: `plays` (telemetry rows), `votes`, `stamps` (sentiment
  class + label-as-stamped), `ideas` (gains vote counts + declined state),
  `versions` (number, name, file, reign history), `live_slot` (pointer +
  rerun timer), `config_log` (append-only policy history), `runs`
  (gains turns/tokens/outcome for the ledger). `payments` table dropped.
- **`/api/agent/*`**: `metrics` (dossier), `complete` (gains name, config
  changes, hypothesis), `ideas` (gains votes).
- **Workflow**: same skeleton (fetch → agent → gate → evidence → ship →
  transcript → report). Budget-meter hook becomes turn meter. Transcript
  archiving, secret scrubbing, pristine verifier, blast radius: unchanged.

### 9.3 The overlay's new job

The landlord persona survives as **management** (§0); the extortion does
not. The injected overlay now runs: the incident report (the death screen —
cause of death, assessment, stamps, ballot, qualification progress), the
wheel (with live odds and gray-outs), rerun announcements ("v3 NIGHT.
two hours. no refunds."), developer status ("THE DEVELOPER IS WORKING →
observe" linking to the live Actions run), and policy-change announcements.
Same personality — management instead of debt collector.

### 9.4 The lobby's new job

The front page: **"NOW SHOWING: v{N} — {name}"** with standing
(votes, delight share), the pile with vote counts, developer status +
capacity mood, last release's hypothesis and its grade, `/versions` lineage
link, the standing truth banner: *"this game is rewritten by an AI that
answers to your votes and your laughter. it cannot want your money or your
time. it can only want your amusement. the show must go on."*

---

## 10. Build order

1. **Foundation**: DB migration (new tables, drop payments), telemetry
   ingest, CSP change, death-event schema in game + CONTRACT.md + verifier.
2. **Demolition**: delete Stripe, pot, thanks, extortion mechanic, dollar
   accounting. App boots with nothing to sell.
3. **Votes & stamps**: incident report + stamps, votes, pile with voting,
   rate limits, death-screen ballot UI in the overlay.
4. **The wheel**: sampler + cooldowns + renormalization, rerun
   mechanics, live-slot pointer in DB, wheel UI in overlay.
5. **The governor**: capacity ledger, SUMMON→trigger path, OAuth auth swap,
   turn meter, dossier endpoint, mission brief + CONTRACT rewrite, notebook,
   config log + clamps, `/api/agent/complete` extensions.
6. **The square**: lobby rebuild, `/versions` page, transparency links.
7. **E2E + launch**: updated Playwright suite (no-scroll invariants stay),
   full loop rehearsal in dev mode, then real traffic.

Each phase leaves the app deployable. Phases 1–2 are mechanical; 3–5 are the
product; 6 is paint; 7 is proof.

---

## 11. Open questions (deliberately deferred)

- **Launch weight tuning**: 0.50/0.30/0.20 is a guess optimized for demo
  visibility; real traffic will embarrass it. The agent owns this problem —
  that's the point.
- **Pro capacity reality**: nobody publishes turn-session-vs-weekly-cap
  numbers. The ledger's defaults are conservative guesses; collisions will
  calibrate them within weeks.
- **Rerun ↔ flagship interaction effects**: does mid-session version
  swapping confuse more than it delights? Watch stamps during
  reruns; the agent can shrink the slice if it's misery.
- **Vote inflation**: if traffic grows, `VOTE_PIPE_THRESHOLD` and per-IP
  limits are the pressure valves — both agent-tunable, both clamped.
- **Someday**: agent-authored A/B via reruns as controlled experiments;
  agent scheduling its own summons ("wake me when the pile has 5 ideas");
  load-leveling across windows. All fit the existing action space; none are
  needed for launch.
