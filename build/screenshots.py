#!/usr/bin/env python3
"""Take a screenshot of every live project for the cards on the home page.

    python3 build/screenshots.py OUTPUT_DIR

Reads OUTPUT_DIR/shots.json (written by build_site.py) and saves
OUTPUT_DIR/shots/<slug>.jpg and <slug>-phone.jpg for each live URL. A site that fails is skipped:
its card falls back to a drawn cover, and the rest of the build carries on.
Set CHROME_CHANNEL=chrome to use an installed Google Chrome instead of
Playwright's own Chromium.
"""

from pathlib import Path
import json
import os
import sys

from playwright.sync_api import sync_playwright


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "_site")
    shots = json.loads((out / "shots.json").read_text(encoding="utf-8"))
    (out / "shots").mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("CHROME_CHANNEL") or None)
        # Each live app is shot twice: at laptop size for wide screens, and at phone
        # size so phones show the app as it really looks on a phone.
        sizes = [
            ("", {"viewport": {"width": 1280, "height": 800}, "device_scale_factor": 1}),
            ("-phone", {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2,
                        "is_mobile": True, "has_touch": True}),
        ]
        for shot in shots:
            for suffix, options in sizes:
                # Dark mode sits well on the cards in both themes.
                page = browser.new_page(color_scheme="dark", **options)
                try:
                    page.goto(shot["url"], wait_until="networkidle", timeout=45_000)
                    page.wait_for_timeout(1200)  # let fonts and entrance animations settle
                    page.screenshot(path=str(out / "shots" / f"{shot['slug']}{suffix}.jpg"),
                                    type="jpeg", quality=72)
                    print(f"Saved a{' phone' if suffix else ''} screenshot of {shot['url']}")
                except Exception as error:  # one broken site must not stop the others
                    print(f"Skipped {shot['url']}{suffix}: {error}")
                finally:
                    page.close()
        browser.close()
    (out / "shots.json").unlink()


if __name__ == "__main__":
    main()
