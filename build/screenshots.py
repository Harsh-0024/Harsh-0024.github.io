#!/usr/bin/env python3
"""Take a screenshot of every live project for the cards on the home page.

    python3 build/screenshots.py OUTPUT_DIR

Reads OUTPUT_DIR/shots.json (written by build_site.py) and saves
OUTPUT_DIR/shots/<slug>.jpg for each live URL. A site that fails is skipped:
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
        for shot in shots:
            # Shot at a laptop size and in dark mode, to sit well on the cards.
            page = browser.new_page(viewport={"width": 1280, "height": 800}, color_scheme="dark",
                                    device_scale_factor=1)
            try:
                page.goto(shot["url"], wait_until="networkidle", timeout=45_000)
                page.wait_for_timeout(1200)  # let fonts and entrance animations settle
                page.screenshot(path=str(out / "shots" / f"{shot['slug']}.jpg"), type="jpeg", quality=74)
                print(f"Saved a screenshot of {shot['url']}")
            except Exception as error:  # one broken site must not stop the others
                print(f"Skipped {shot['url']}: {error}")
            finally:
                page.close()
        browser.close()
    (out / "shots.json").unlink()


if __name__ == "__main__":
    main()
