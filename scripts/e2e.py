# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.45"]
# ///
"""E2E for the post-money era: lobby, incident report, stamps, ballot, wheel.

Run the app in dev mode with a fresh DB first:
    rm -rf data && uv run uvicorn app.main:app --port 8123
then:
    uv run scripts/e2e.py

Viewports: 1280x650 (the 13-inch-laptop floor -- nothing may scroll there) and 1440x780.
"""
import json
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8123"
FAIL = []

def check(name, cond):
    print(("  ok  " if cond else "  FAIL") + " " + name)
    if not cond: FAIL.append(name)

def no_scroll(page, label):
    m = page.evaluate("""() => ({
        sh: document.documentElement.scrollHeight, ih: window.innerHeight,
        sw: document.documentElement.scrollWidth,  iw: window.innerWidth })""")
    check(f"{label}: no vertical scroll ({m['sh']} <= {m['ih']})", m["sh"] <= m["ih"] + 1)
    check(f"{label}: no horizontal scroll ({m['sw']} <= {m['iw']})", m["sw"] <= m["iw"] + 1)


def keyboard_run_until_death(page, label):
    """Wait for the game's RAF loop to be alive, then press Space with human-ish
    pacing until the bird dies. Fails only if 12 presses produce no death."""
    page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    base = page.evaluate("window.__died")
    for _ in range(12):
        page.keyboard.press("Space")
        page.wait_for_timeout(650)
        if page.evaluate("window.__died") > base:
            check(label, True)
            return
    check(label, False)


def api(path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


with sync_playwright() as pw:
    b = pw.chromium.launch()
    for W, H in [(1280, 650), (1440, 780)]:
        print(f"--- viewport {W}x{H} ---")
        page = b.new_page(viewport={"width": W, "height": H})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(
            "window.__died = 0;"
            " addEventListener('crappy-bird:death', () => window.__died++)")

        # lobby
        page.goto(BASE)
        page.wait_for_timeout(1200)
        no_scroll(page, "lobby")
        check("lobby: START button visible", page.is_visible("#start"))
        check("lobby: NOW SHOWING marquee filled",
              "v" in (page.text_content("#ns-line") or ""))
        check("lobby: the pile box visible", page.is_visible("#pile"))
        check("lobby: truth banner present",
              "the show must go on" in (page.text_content("#truth") or ""))

        # lobby -> game via the button
        page.click("#start")
        page.wait_for_url("**/play", timeout=5000)
        page.wait_for_timeout(1500)
        no_scroll(page, "game")

        # THE regression test: keyboard only, no clicks anywhere first.
        keyboard_run_until_death(page, "game: SPACE works from cold load (death via keyboard-only run)")

        # the incident report appears on every death, wheel and all
        try:
            page.wait_for_selector("#cb-report-wrap.cb-on", timeout=8000)
            check("incident report appears on death", True)
        except Exception:
            check("incident report appears on death", False)
        no_scroll(page, "game+report")
        check("report: has a report number", "no. " in (page.text_content("#cb-repno") or ""))
        check("report: management assessment present",
              len((page.text_content("#cb-assess") or "").strip()) > 0)
        check("report: wheel canvas visible", page.is_visible("#cb-wheel"))
        check("report: odds legend shows the real odds",
              "%" in (page.text_content("#cb-odds") or ""))
        check("report: three stamps offered",
              page.locator(".cb-stamp").count() == 3)

        if (W, H) == (1280, 650):
            page.screenshot(path="agent/screenshots/e2e.report.png")
            # wait out the wheel animation, then stamp the report
            page.wait_for_timeout(2900)
            check("wheel: outcome announced",
                  len((page.text_content("#cb-outcome") or "").strip()) > 0)
            page.click('.cb-stamp[data-s="delight"]')
            page.wait_for_timeout(700)
            check("stamp: ink hits the paper", page.is_visible("#cb-stamped"))
            check("stamp: management acknowledges",
                  "filed" in (page.text_content("#cb-stampline") or ""))
            page.screenshot(path="agent/screenshots/e2e.stamped.png")
            # file it; play again; leave the next report unstamped
            page.click("#cb-fileit")
            page.wait_for_timeout(400)
            check("file it closes the report", not page.is_visible("#cb-report"))
            keyboard_run_until_death(page, "second run: keyboard still works after the report")
            page.wait_for_selector("#cb-report-wrap.cb-on", timeout=8000)
            page.click("#cb-fileit")
            page.wait_for_timeout(500)
            check("silence is data: unstamped filing gets the strip",
                  "silence" in (page.text_content("#cb-strip") or ""))

        check("zero page errors", not errors)
        if errors: print("   errors:", errors[:3])
        page.close()

    # ---- the ballot, API-level (earning 11 pipes by hand is not a test plan) --
    print("--- ballot via API ---")
    d = api("/api/death", {"version": 3, "pipes": 15, "durationMs": 40000,
                           "flaps": 80, "cause": "pipe", "session": "e2e", "viewport": "desktop"})
    check("qualified death earns a ballot", d["qualified"] and d["ballot"] is not None)
    check("ballot lists versions", len(d["ballot"]["versions"]) >= 1)
    v = api("/api/vote", {"play_id": d["play_id"], "kind": "idea_new",
                          "text": "every 10th pipe is deeply apologetic about the whole thing"})
    check("vote: new idea accepted", v.get("ok") is True)
    state = api("/api/state")
    check("idea shows up in the pile with a vote",
          any("apologetic" in i["text"] and i["votes"] >= 1 for i in state["pile"]))
    d2 = api("/api/death", {"version": 3, "pipes": 12, "durationMs": 31000,
                            "flaps": 70, "cause": "ground"})
    v2 = api("/api/vote", {"play_id": d2["play_id"], "kind": "version", "version": 1})
    check("vote: version upvote accepted", v2.get("ok") is True)
    versions = api("/api/versions")
    check("version vote is counted in public",
          any(row["version"] == 1 and row["votes"] >= 1 for row in versions))

    # ---- /versions page ----------------------------------------------------
    page = b.new_page(viewport={"width": 1280, "height": 650})
    page.goto(BASE + "/versions")
    page.wait_for_timeout(800)
    check("/versions: lineage cards render", page.locator(".card").count() >= 3)
    check("/versions: exactly one NOW SHOWING",
          page.locator(".badge:not(.archived):not(.flagship)").count() == 1)
    page.close()

    # download must be the raw file: no management, no reports
    raw = urllib.request.urlopen(BASE + "/download").read().decode()
    check("download has no injected management", "cb-report" not in raw and "INCIDENT REPORT" not in raw)
    check("download still has the death hook", "crappy-bird:death" in raw)
    b.close()

print()
print("ALL PASS" if not FAIL else f"{len(FAIL)} FAILURES: {FAIL}")
raise SystemExit(1 if FAIL else 0)
