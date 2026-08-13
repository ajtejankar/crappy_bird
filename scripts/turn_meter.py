#!/usr/bin/env python3
"""PostToolUse hook: a turn meter the developer can actually see.

Dollars no longer exist here. The scarce resource is capacity: the harness
enforces --max-turns but never tells the model how far along it is. This hook
closes that gap: after tool calls it counts the session's turns (assistant
events in the transcript) and, each time the session crosses 50/75/90% of
MAX_TURNS, injects a system note so the agent can pace itself and wrap up
with dignity instead of being guillotined mid-refactor.

Only active when CRAPPY_DEV_RUN=1 (set by the CI workflow) — it stays out of
the way of humans using Claude Code in this repo. Stdlib only, by design:
hooks run on every tool call and must be fast.
"""

import json
import os
import sys

MILESTONES = (50, 75, 90)


def main() -> None:
    if os.environ.get("CRAPPY_DEV_RUN") != "1":
        return
    cap = int(os.environ.get("MAX_TURNS", "250"))

    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return
    transcript = payload.get("transcript_path")
    session_id = str(payload.get("session_id", "unknown"))[:64]
    if not transcript or not os.path.isfile(transcript):
        return

    turns = 0
    with open(transcript, errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "assistant":
                turns += 1

    pct = turns / cap * 100 if cap > 0 else 100
    milestone = max((m for m in MILESTONES if pct >= m), default=0)
    if not milestone:
        return

    # one note per crossed milestone, tracked per session
    state_path = f"/tmp/crappy-turns-{session_id}"
    last = 0
    try:
        last = int(open(state_path).read().strip())
    except (OSError, ValueError):
        pass
    if milestone <= last:
        return
    with open(state_path, "w") as f:
        f.write(str(milestone))

    if milestone >= 90:
        urgency = ("STOP building. Ship what already passes verification NOW, or write your "
                   "surrender release.json. There are not enough turns left for another attempt.")
    elif milestone >= 75:
        urgency = ("Wrap-up territory: stop exploring, finish the current change, run the "
                    "verifier, write the changelog, the notebook and release.json.")
    else:
        urgency = "Pace yourself accordingly. Verify early; a cheap failed verify now beats a doomed one later."
    note = (f"TURN METER: ~{turns} of your {cap} max turns used ({pct:.0f}%). "
            f"The harness terminates the session at the cap — mid-thought, no appeal. {urgency}")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": note,
        }
    }))


if __name__ == "__main__":
    main()
