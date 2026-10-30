"""Screenshot every UI state at laptop and phone sizes, for reviewing polish.

    uv run --with playwright python scripts/shoot_states.py http://127.0.0.1:8014 shots/before

Run it against a scratch instance with sample music (scripts/generate_samples.py),
never a real library: it creates a tape and a show, renames a song and starts a
rip that fails. Openings and closings are also captured as a few frames, with the
motion tokens slowed down so the frames land mid-move.
"""

import pathlib
import sys

from playwright.sync_api import sync_playwright

BASE, OUT = sys.argv[1].rstrip("/"), pathlib.Path(sys.argv[2])
SIZES = {"laptop": dict(width=1440, height=900), "phone": dict(width=390, height=844)}
LONG = "An Unreasonably Long Song Title That Keeps Going (Extended Live Version)"
SLOW = ":root { --dur-open: 1600ms; --dur-shut: 1000ms; }"


def setup(request):
    """Data the states need: a tape, a show, a long title."""
    request.post(f"{BASE}/api/playlists", data={"name": "Road Trip"})
    request.post(f"{BASE}/api/podcast/shows", data={"name": "Morning Notes"})
    first = request.get(f"{BASE}/api/playlists/all/tracks").json()[0]
    request.patch(f"{BASE}/api/tracks/{first['id']}", data={"title": LONG})


def shoot(size, page):
    out = OUT / size
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def snap(name):
        page.wait_for_timeout(450)
        page.mouse.move(5, page.viewport_size["height"] - 5)   # no hover
        page.screenshot(path=str(out / f"{name}.png"))

    def frames(name, action, times=(80, 250, 500, 900)):
        page.add_style_tag(content=SLOW)
        action()
        last = 0
        for t in times:
            page.wait_for_timeout(t - last)
            last = t
            page.screenshot(path=str(out / f"{name}-{t}ms.png"))
        page.wait_for_timeout(1700)
        page.evaluate("document.querySelectorAll('style').forEach((s) => s.textContent.includes('--dur-open: 1600ms') && s.remove())")

    def step(name, fn):
        try:
            fn()
        except Exception as e:   # one broken state shouldn't stop the rest
            print(f"  {size}/{name}: {e.__class__.__name__}: {str(e).splitlines()[0]}")

    def back():
        for b in ("#backBtn", "#browseBack", "#epBack"):
            if page.is_visible(b):
                page.click(b)
                page.wait_for_timeout(900)

    page.goto(BASE + "/")
    page.wait_for_timeout(1500)
    step("shelf", lambda: snap("01-shelf"))
    step("plus", lambda: (page.click("#dlToggle"), snap("02-plus-choices")))
    step("add-tape", lambda: (page.locator(".slot-choice").nth(1).click(), page.keyboard.type("Road Trip"), snap("03-add-tape-typed")))
    step("add-tape-error", lambda: (page.keyboard.press("Enter"), page.wait_for_timeout(600), snap("04-add-tape-duplicate")))
    step("rip-error", lambda: (page.click("#dlToggle") if page.is_hidden("#libSlot") else None, page.wait_for_timeout(300),
                                page.click("#dlToggle") if page.locator(".slot-choice").count() == 0 else None,
                                page.locator(".slot-choice").first.click(), page.keyboard.type("https://example.invalid/nope"),
                                page.keyboard.press("Enter"), page.wait_for_timeout(4000), snap("05-downloads-error")))
    step("dl-open", lambda: (page.click("#dlSummary"), snap("06-downloads-open"), page.click("#dlSummary")))
    step("all-tracks", lambda: (page.locator(".shelf-row", has_text="All Tracks").click(), page.wait_for_timeout(900), snap("07-all-tracks")))
    step("row-menu", lambda: (page.locator("#trackList li").nth(1).hover(), page.locator("#trackList li").nth(1).locator(".tl-more").click(), snap("08-row-menu")))
    step("row-menu-hover", lambda: (page.locator(".menu-item").first.hover(), page.wait_for_timeout(300), page.screenshot(path=str(out / "09-row-menu-hover.png"))))
    step("edit", lambda: (page.locator(".menu-item", has_text="Edit").click(), snap("10-edit-form")))
    step("confirm", lambda: (page.fill("#edTitle", "Changed"), page.keyboard.press("Escape"), snap("11-confirm")))
    step("confirm-close", lambda: (page.click("#confirmOk") if page.is_visible("#confirmOk") else None, page.wait_for_timeout(500)))
    step("add-to", lambda: (page.locator("#trackList li").nth(2).hover(), page.locator("#trackList li").nth(2).locator(".tl-addto").click(), snap("12-add-to-menu")))
    step("bar-menu", lambda: (page.keyboard.press("Escape"), page.click("#tapeMoreBtn"), snap("13-bar-menu")))
    step("list-search", lambda: (page.keyboard.press("Escape"), page.click("[data-search='search']"), page.keyboard.type("zzz"), snap("14-search-no-results")))
    step("back-shelf", lambda: (page.keyboard.press("Escape"), back()))
    step("albums", lambda: (page.locator(".shelf-row", has_text="Albums").click(), page.wait_for_timeout(900), snap("15-albums")))
    step("album", lambda: (page.locator(".browse-row").first.click(), page.wait_for_timeout(900), snap("16-album")))
    step("album-form", lambda: (page.click("#tapeMoreBtn"), page.locator(".menu-item", has_text="Edit album").click(), snap("17-album-form")))
    step("back-shelf2", lambda: (page.click("#alCancel"), page.wait_for_timeout(400), back(), back()))
    step("empty-tape", lambda: (page.locator(".shelf-row", has_text="Road Trip").click(), page.wait_for_timeout(900), snap("18-empty-tape"), back()))
    step("podcasts", lambda: (page.click("#modePods"), page.wait_for_timeout(900), snap("19-podcasts")))
    step("show", lambda: (page.locator("#showList .browse-row, #showList .shelf-row").first.click(), page.wait_for_timeout(900), snap("20-show"), back()))
    step("music", lambda: (page.click("#modeMusic"), page.wait_for_timeout(700)))
    step("playing", lambda: (page.locator(".shelf-row", has_text="All Tracks").click(), page.wait_for_timeout(900),
                             page.locator("#trackList li").nth(2).click(), page.wait_for_timeout(1500), snap("21-playing")))
    step("deck", lambda: (page.click("#miniOpen") if page.is_visible("#miniOpen") else None, page.wait_for_timeout(800), snap("22-deck")))
    step("up-next", lambda: (page.click("#upnextBar"), snap("23-up-next"), page.click("#upnextBar")))
    step("full-screen", lambda: (page.evaluate("DeckFX.setImmersive(true)"), snap("24-full-screen"), page.evaluate("DeckFX.setImmersive(false)")))
    step("toast", lambda: (page.goto(BASE + "/"), page.wait_for_timeout(1200), page.evaluate("document.querySelector('.toast') || 0"),
                           page.click("#dlToggle"), page.locator(".slot-choice").nth(1).click(), page.keyboard.type("Toast Tape"),
                           page.keyboard.press("Enter"), page.wait_for_timeout(250), page.screenshot(path=str(out / "25-toast.png"))))

    # Motion, slowed: + opening, a row menu opening and shutting, going into a list and back.
    page.goto(BASE + "/")
    page.wait_for_timeout(1200)
    step("f-plus", lambda: frames("m1-plus-open", lambda: page.click("#dlToggle")))
    step("f-plus-shut", lambda: frames("m2-plus-shut", lambda: page.click("#dlToggle")))
    step("f-into", lambda: frames("m3-into-list", lambda: page.locator(".shelf-row", has_text="All Tracks").click(), (60, 180, 320, 600)))
    step("f-menu", lambda: (page.locator("#trackList li").nth(1).hover(), frames("m4-menu-open", lambda: page.locator("#trackList li").nth(1).locator(".tl-more").click())))
    step("f-menu-shut", lambda: frames("m5-menu-shut", lambda: page.locator("#trackList li").nth(1).locator(".tl-more").click()))
    step("f-back", lambda: frames("m6-back", lambda: page.click("#backBtn"), (60, 180, 320, 600)))
    if errors:
        print(f"  {size}: page errors: {errors}")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    ctx = browser.new_context()
    setup(ctx.request)
    for size, viewport in SIZES.items():
        page = browser.new_page(viewport=viewport, device_scale_factor=2 if size == "phone" else 1)
        shoot(size, page)
        page.close()
    browser.close()
print(f"saved to {OUT}")
