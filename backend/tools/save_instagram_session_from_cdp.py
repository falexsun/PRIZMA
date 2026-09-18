import os
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, sync_playwright


SESSION_PATH = Path("uploads") / "instagram_storage_state.json"
CDP_URL = os.environ.get("INSTAGRAM_CDP_URL", "http://host.docker.internal:9222")


def main() -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"Connecting to local browser via {CDP_URL}...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2_000)
        except PlaywrightError as exc:
            print(f"Instagram page check failed, saving current browser state anyway: {exc}")
        context.storage_state(path=str(SESSION_PATH))
        browser.close()
    print(f"Saved Instagram session to {SESSION_PATH}")


if __name__ == "__main__":
    main()
