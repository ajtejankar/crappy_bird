# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.45", "fire"]
# ///
"""The verification gate. A game version does not ship unless this passes.

Usage:
    uv run agent/verify_game.py install                 # one-time: install chromium
    uv run agent/verify_game.py verify games/index.v2.html

Checks:
  1. size        <= 102400 bytes
  2. single file  no external network references (fetch/XHR/WebSocket/http src...)
  3. boots        loads in chromium with zero page errors, emits crappy-bird:ready
  4. dies         after starting a run and doing nothing, gravity produces a
                  crappy-bird:death postMessage (the business model depends on it)
  5. survives     a restart after death works and does not throw

Also drops screenshots into agent/screenshots/ so the developer can look at
what it has done.
"""

import http.server
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

MAX_BYTES = 102_400

# Anything that smells like the network. The hosting CSP blocks these anyway;
# this catches them before we waste a release on a silently broken game.
NETWORK_SMELLS = [
    (r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//""", "external src/href"),
    (r"\bfetch\s*\(", "fetch()"),
    (r"\bXMLHttpRequest\b", "XMLHttpRequest"),
    (r"\bnew\s+WebSocket\b", "WebSocket"),
    (r"\bnew\s+EventSource\b", "EventSource"),
    (r"\bsendBeacon\b", "navigator.sendBeacon"),
    (r"\bimportScripts\b", "importScripts"),
    (r"""\bimport\s*\(\s*["']https?:""", "dynamic import of URL"),
    (r"@import\s+url\(\s*['\"]?https?:", "css @import of URL"),
]

HARNESS = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>harness</title></head>
<body style="margin:0;background:#222">
<iframe id="g" src="game.html" style="width:400px;height:720px;border:0"></iframe>
<script>
  window.__msgs = [];
  window.addEventListener('message', e => {
    try { window.__msgs.push(JSON.parse(JSON.stringify(e.data))); } catch (err) {}
  });
</script>
</body></html>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def install():
    """Install the chromium browser playwright needs (idempotent)."""
    cmd = [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"]
    print("+", " ".join(cmd))
    raise SystemExit(subprocess.call(cmd))


def verify(path: str, screenshot_dir: str = "agent/screenshots", timeout_s: int = 30):
    """Run the full gate against one game file. Exit code 0 = shippable."""
    game = Path(path)
    failures: list[str] = []

    # ---- 1. exists + size ------------------------------------------------
    if not game.is_file():
        print(f"FAIL: {game} does not exist")
        raise SystemExit(1)
    size = game.stat().st_size
    print(f"size: {size} bytes (limit {MAX_BYTES})")
    if size > MAX_BYTES:
        failures.append(f"file is {size} bytes; limit is {MAX_BYTES}")

    # ---- 2. network smells -----------------------------------------------
    text = game.read_text(errors="replace")
    for pattern, label in NETWORK_SMELLS:
        if re.search(pattern, text):
            failures.append(f"network smell: {label} (pattern {pattern!r})")
    if not re.search(r"crappy-bird:death", text):
        failures.append("the death hook string 'crappy-bird:death' is missing — see CONTRACT.md #4")
    if not re.search(r"crappy-bird:ready", text):
        failures.append("the ready hook string 'crappy-bird:ready' is missing — see CONTRACT.md #4")
    if not re.search(r"CustomEvent", text):
        failures.append("no CustomEvent dispatch found — the injected overlay needs it, see CONTRACT.md #4")

    if failures:
        _report(failures)

    # ---- 3-5. run it in a real browser ------------------------------------
    from playwright.sync_api import sync_playwright

    shots = Path(screenshot_dir)
    shots.mkdir(parents=True, exist_ok=True)
    stem = game.stem  # e.g. index.v2

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        shutil.copy(game, tdir / "game.html")
        (tdir / "harness.html").write_text(HARNESS)

        port = _free_port()
        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(tdir), **kw)  # noqa: E731
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        page_errors: list[str] = []
        console_errors: list[str] = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 440, "height": 780})
                page.on("pageerror", lambda e: page_errors.append(str(e)))
                page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

                page.goto(f"http://127.0.0.1:{port}/harness.html")
                frame = next((f for f in page.frames if "game.html" in f.url), None)
                if frame is None:
                    failures.append("game iframe never appeared")
                    _report(failures)

                def msgs():
                    return page.evaluate("window.__msgs")

                def wait_for(msg_type: str, timeout_ms: int) -> bool:
                    try:
                        page.wait_for_function(
                            f"window.__msgs.some(m => m && m.type === '{msg_type}')",
                            timeout=timeout_ms,
                        )
                        return True
                    except Exception:
                        return False

                # NOTE: interact via pointerdown on the canvas, not the keyboard —
                # cross-frame keyboard focus is unreliable in headless browsers,
                # and the canvas is the game's primary input anyway.
                def tap():
                    frame.click("#game")

                # the same-document contract: the injected overlay listens for a
                # CustomEvent, so verify the game dispatches one on death too
                frame.evaluate(
                    "window.addEventListener('crappy-bird:death',"
                    " () => window.parent.postMessage({type: 'customevent:death'}, '*'))"
                )

                # ready handshake
                if not wait_for("crappy-bird:ready", 10_000):
                    failures.append("no crappy-bird:ready within 10s of load")

                # boot -> menu -> play: two taps, then do nothing and let gravity win
                page.wait_for_timeout(800)
                tap()                                    # skip boot
                page.wait_for_timeout(700)
                tap()                                    # start the run
                page.wait_for_timeout(350)
                tap()                                    # one honest flap for the screenshot
                page.wait_for_timeout(300)
                page.screenshot(path=str(shots / f"{stem}.playing.png"))

                if not wait_for("crappy-bird:death", timeout_s * 1000):
                    failures.append(f"no crappy-bird:death within {timeout_s}s of hands-off play")
                else:
                    death = next(m for m in msgs() if m and m.get("type") == "crappy-bird:death")
                    print(f"death observed: score={death.get('score')} cause={death.get('cause')!r}")
                    if not any(m and m.get("type") == "customevent:death" for m in msgs()):
                        failures.append("death postMessage fired but no CustomEvent — CONTRACT.md #4 "
                                        "requires both (the hosted overlay depends on the CustomEvent)")
                page.wait_for_timeout(1200)
                page.screenshot(path=str(shots / f"{stem}.dead.png"))

                # restart must work (tap dismisses the death screen and starts a new run;
                # the 1.2s wait above clears the game's panic-tap guard)
                deaths_before = sum(1 for m in msgs() if m and m.get("type") == "crappy-bird:death")
                tap()
                try:
                    page.wait_for_function(
                        f"window.__msgs.filter(m => m && m.type === 'crappy-bird:death').length > {deaths_before}",
                        timeout=timeout_s * 1000,
                    )
                    print("second death observed: restart works")
                except Exception:
                    failures.append("game did not produce a second death after restart — soft-lock?")

                browser.close()
        finally:
            server.shutdown()

        for e in page_errors:
            failures.append(f"uncaught page error: {e[:300]}")
        for e in console_errors[:5]:
            failures.append(f"console.error: {e[:300]}")

    _report(failures)


def _report(failures: list[str]):
    if failures:
        print("\n================ VERDICT: DO NOT SHIP ================")
        for f in failures:
            print(f"  ✗ {f}")
        raise SystemExit(1)
    print("\n================ VERDICT: SHIPPABLE ================")
    print("  ✓ all checks passed. release the bird.")
    raise SystemExit(0)


if __name__ == "__main__":
    import fire
    fire.Fire({"verify": verify, "install": install})
