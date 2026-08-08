#!/usr/bin/env python3
"""PostToolUse hook: a budget meter the developer can actually see.

Claude Code's --max-budget-usd enforces the cap but never tells the model.
This hook closes that gap: after tool calls, it prices the session transcript
(hook input carries transcript_path; assistant events carry token usage) and,
each time cumulative spend crosses another BUDGET_REMINDER_STEP_USD boundary,
injects a system note so the agent can pace itself and wrap up with dignity
instead of being guillotined mid-refactor.

Only active when CRAPPY_DEV_RUN=1 (set by the CI workflow) — it stays out of
the way of humans using Claude Code in this repo. Stdlib only, by design:
hooks run on every tool call and must be fast.
"""

import json
import os
import sys

# Opus 5, USD per million tokens
PRICE_IN, PRICE_OUT, PRICE_CACHE_WRITE, PRICE_CACHE_READ = 5.0, 25.0, 6.25, 0.5


def main() -> None:
    if os.environ.get("CRAPPY_DEV_RUN") != "1":
        return
    cap = float(os.environ.get("MAX_SESSION_USD", "8"))
    step = float(os.environ.get("BUDGET_REMINDER_STEP_USD", "2"))

    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return
    transcript = payload.get("transcript_path")
    session_id = str(payload.get("session_id", "unknown"))[:64]
    if not transcript or not os.path.isfile(transcript):
        return

    tin = tout = cw = cr = 0
    with open(transcript, errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") != "assistant":
                continue
            usage = (event.get("message") or {}).get("usage") or {}
            tin += usage.get("input_tokens", 0) or 0
            tout += usage.get("output_tokens", 0) or 0
            cw += usage.get("cache_creation_input_tokens", 0) or 0
            cr += usage.get("cache_read_input_tokens", 0) or 0
    cost = (tin * PRICE_IN + tout * PRICE_OUT + cw * PRICE_CACHE_WRITE + cr * PRICE_CACHE_READ) / 1e6

    # one reminder per crossed step boundary, tracked per session
    state_path = f"/tmp/crappy-budget-{session_id}"
    last = 0.0
    try:
        last = float(open(state_path).read().strip())
    except (OSError, ValueError):
        pass
    crossed = int(cost / step) * step
    if crossed <= last:
        return
    with open(state_path, "w") as f:
        f.write(str(crossed))

    pct = cost / cap * 100 if cap > 0 else 100
    if pct >= 90:
        urgency = ("STOP building. Ship what already passes verification NOW, or write your "
                   "surrender release.json. There is no budget left for another attempt.")
    elif pct >= 70:
        urgency = ("Wrap-up territory: stop exploring, finish the current feature, run the "
                   "verifier, write the changelog and release.json.")
    else:
        urgency = "Pace yourself accordingly."
    note = (f"BUDGET METER: ~${cost:.2f} of your ${cap:.2f} hard cap consumed ({pct:.0f}%). "
            f"The harness terminates this session at the cap — mid-thought, no appeal. "
            f"(Meter excludes subagent spend; if you delegated, the true total is higher.) {urgency}")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": note,
        }
    }))


if __name__ == "__main__":
    main()
