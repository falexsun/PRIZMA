from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SESSION_PATH = ROOT / "uploads" / "instagram_storage_state.json"


def _proxy_config(proxy_url: str | None) -> dict | None:
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    if not parsed.scheme or not parsed.hostname:
        return {"server": proxy_url}
    result = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        result["username"] = parsed.username
    if parsed.password:
        result["password"] = parsed.password
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Create local Instagram Playwright session")
    parser.add_argument("--proxy", help="Optional proxy URL, for example socks5://user:pass@host:port")
    parser.add_argument("--ask-proxy", action="store_true", help="Ask for proxy URL without echoing it")
    args = parser.parse_args()
    if args.ask_proxy and not args.proxy:
        import getpass

        args.proxy = getpass.getpass("Proxy URL (hidden, leave empty for direct): ").strip() or None

    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("Instagram session setup")
    print("A browser window will open. Log in manually, complete 2FA/challenge if needed.")
    print("Do not paste your password into this console.")
    if args.proxy:
        print("Proxy mode: enabled")

    with sync_playwright() as p:
        launch_kwargs = {"headless": False}
        proxy = _proxy_config(args.proxy)
        if proxy:
            launch_kwargs["proxy"] = proxy
        browser = p.chromium.launch(**launch_kwargs)
        context_kwargs = dict(
            locale="ru-RU",
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
        )
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        try:
            page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightError as exc:
            print(f"Instagram login page did not open automatically: {exc}")
            print("The browser window will stay open. Try opening https://www.instagram.com manually in it.")

        input("After Instagram is fully logged in, press Enter here to save the session...")

        try:
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2000)
        except PlaywrightError:
            pass
        context.storage_state(path=str(SESSION_PATH))
        browser.close()

    print(f"Saved Instagram session to {SESSION_PATH}")


if __name__ == "__main__":
    main()
