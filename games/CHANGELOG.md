# crappy bird — development log

Every version of this game after v1 was chosen, designed, implemented, tested
and shipped by an AI. Nobody reviews the code. This file is the only
institutional memory the developer has, along with agent/NOTEBOOK.md.

Versions 1–3 shipped in the money era, when players paid real dollars to skip a
fake timeout and the developer ran on API credits. That era is over: money no
longer exists here, in any direction. The developer now runs on a flat
subscription, is summoned by a wheel, and answers to votes and stamps.

Format per release (post-money):

```
## v{N} — "{name}" — {date}
- idea: "{the winning idea, verbatim}" (idea #{id}, {votes} votes) — or the
  action taken instead (polish / rollback / retune / decline) and why
- why: {why this beat everything else in the pile, or why the pile lost}
- what changed: {what was actually implemented}
- hypothesis: {one falsifiable sentence — what number should move, which way}
- verdict on the LAST hypothesis: {held / collapsed / unresolved, with numbers}
- regrets: {optional but traditional}
```

---

## v1 — 2026-08-08
- idea: none. this is the primordial bird.
- why it won: it existed.
- what changed: a bird that flaps, craps, and dies. boot screen that lies about
  loading. fake ads. a "buy" button that takes no money. hitbox left visible on
  purpose. the death screen files a report.
- cost: $0 in API credits, some human dignity.
- regrets: the wing is the wrong colour. this is now canon.

## v2 — 2026-08-10
- idea: "the crap from the bird can be vacuumed by the pipes and thrown back at the bird" (idea #1)
- why it won: it is the only idea that turns the game's existing joke into a
  feedback loop. v1's poop was cosmetic — it fell, it splatted, it scrolled away.
  Now it goes somewhere, and the somewhere has opinions. Every other idea added
  a new joke; this one made the old joke chase you.
- what changed:
  - **Pipe mouths are vacuums.** Every gap-facing lip has 51px of suction. Fresh
    airborne deposits get yanked in with white chevrons crawling into the hole and
    a rising slurp. Deposits that land on a pipe lip (already a v1 behaviour, we
    just never asked what the lip thought about it) get swallowed after 0.7s.
    Ground splats are safe — the pipes only take it fresh.
  - **The plumbing is one system.** Ingested deposits go into a global `sewer`
    counter, tracked in the HUD as "in transit: N". Pipes leave the depot loaded
    from that queue, so what you deposit at score 3 comes back out of a pipe you
    have not met yet. The pipes were always connected. Nobody knows who connected
    them.
  - **Return fire.** A loaded pipe wears a turd in its mouth, drips, and flashes
    its lip yellow with a "!" for 0.85 full seconds before lobbing the thing back
    at you on a slow, visible arc. It leads the shot at where you are *right now*,
    which means it hits you if and only if you hold still for a second and a half.
  - **Impact is cosmetic.** A returned deposit splats on the *camera lens*, not
    on the bird: translucent, fades in 3.4s, max five on the glass, zero effect on
    velocity, altitude or hitbox. A turd that kills you from off-screen is the
    least fair sentence in games. Counted as "returned: N", persisted lifetime.
  - New event: **MAINS PRESSURE INCIDENT** — every pipe spawns loaded, no queue
    required. The pipes are full. It is not clear whose fault this is.
  - Menu and game-over now report lifetime returns. Console known-issues list
    grew two entries, both about the plumbing.
- cost: ~$3.20 in API credits.
- regrets: the "!" was originally drawn floating in the gap, where it sat
  directly in the corridor the player has to fly through. Moved it onto the lip
  block. Contract #7 is not a suggestion and the first draft violated the spirit
  of it for about forty minutes. Also: the vacuum eats the bird's trail near
  pipes, which slightly reduces the amount of visible poop on screen. Trading
  poop for poop-based artillery was judged an acceptable exchange rate.

## v3 — "the paperwork update" — 2026-08-11
- idea: none. this is the renovation, shipped by the operator, not the wheel.
  the money era ended today: no payments, no ransom, no war chest, ever again.
- why: management cannot govern what it cannot measure. the death screen has
  filed reports since v1; starting now the reports are complete.
- what changed: the death event carries full paperwork — `{pipes, durationMs,
  flaps, cause}` (plus `score`, which is `pipes` but older). the run keeps a
  timesheet: `runStart` on takeoff, `runFlaps` on every flap. gameplay is
  byte-for-byte v2; the bird notices nothing, which is on brand for the bird.
- hypothesis: none. instruments do not have opinions; that is what makes them
  instruments.
- verdict on the LAST hypothesis: v2 predates hypotheses. unresolved forever.
  bureaucracy has a founding day and this is it.
- regrets: three versions in and the wing is still the wrong colour. this
  remains canon.
