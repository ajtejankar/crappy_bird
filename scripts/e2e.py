# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.45"]
# ///
"""E2E for the two-screen design.

Run the app in dev mode with a deterministic shakedown first:
    rm -rf data && BLOCK_PROBABILITY=1.0 uv run uvicorn app.main:app --port 8123
then:
    uv run scripts/e2e.py

Viewports: 1280x650 (the 13-inch-laptop floor -- nothing may scroll there) and 1440x780.
"""
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
        check("lobby: war chest visible", page.is_visible("#barbox"))

        # lobby -> game via the button
        page.click("#start")
        page.wait_for_url("**/play", timeout=5000)
        page.wait_for_timeout(1500)
        no_scroll(page, "game")

        # THE regression test: keyboard only, no clicks anywhere first.
        keyboard_run_until_death(page, "game: SPACE works from cold load (death via keyboard-only run)")

        # shakedown appears (p=1), page still unscrollable with overlay open
        try:
            page.wait_for_selector("#cb-shakedown.cb-on", timeout=5000)
            check("shakedown overlay appears on death", True)
        except Exception:
            check("shakedown overlay appears on death", False)
        no_scroll(page, "game+overlay")
        check("overlay shows war chest line", "war chest" in (page.text_content("#cb-chestline") or ""))

        if (W, H) == (1280, 650):
            page.screenshot(path="agent/screenshots/e2e.shakedown.png")
            # pay $2.50 through the overlay -> dev checkout -> thanks -> 2 ideas
            page.fill("#cb-amount", "2.50")
            page.click("#cb-paybtn")
            page.wait_for_url("**/thanks*", timeout=8000)
            page.wait_for_timeout(1200)
            check("thanks: receipt shows $2.50", "$2.50" in (page.text_content("#r-amount") or ""))
            check("thanks: 2 idea credits", "2 ideas" in (page.text_content("#r-credits") or ""))
            page.fill("#idea", "every 10th pipe is deeply apologetic about the whole thing")
            page.click("#submit")
            page.wait_for_timeout(700)
            check("thanks: idea accepted", "accepted" in (page.text_content("#status") or ""))
            # waitout path: back to game, die again, decline to pay
            page.goto(BASE + "/play")
            page.wait_for_timeout(1200)
            keyboard_run_until_death(page, "second visit: keyboard still works")
            page.wait_for_selector("#cb-shakedown.cb-on", timeout=15000)
            page.click("#cb-waitout")
            page.wait_for_timeout(400)
            check("waitout closes overlay", not page.is_visible("#cb-ransom"))
            check("strip appears after waitout", page.is_visible("#cb-strip"))

        check("zero page errors", not errors)
        if errors: print("   errors:", errors[:3])
        page.close()

    # download must be the raw file: no landlord, no begging
    import urllib.request
    raw = urllib.request.urlopen(BASE + "/download").read().decode()
    check("download has no injected landlord", "cb-shakedown" not in raw and "TOTALLY LEGAL" not in raw)
    check("download still has the death hook", "crappy-bird:death" in raw)
    b.close()

print()
print("ALL PASS" if not FAIL else f"{len(FAIL)} FAILURES: {FAIL}")
raise SystemExit(1 if FAIL else 0)
