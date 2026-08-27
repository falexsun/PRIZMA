"""One-time interactive login for MAX (max.ru).

Run inside the container (or locally with the same .env):

    python -m app.parsers.max_login [optional-max-post-url]

The script opens a headless Chromium, navigates to a MAX post page, clicks the
"Open in browser" / "Войти по номеру телефона" buttons, prompts for the phone
number and SMS code, and saves the resulting Playwright storage state to
MAX_SESSION_PATH (default: max_session.json). The worker reuses this session for
subsequent metric fetches.
"""
import asyncio
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from app.core.config import settings


async def main() -> None:
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://max.ru/"

    session_path = Path(settings.max_session_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        await page.goto(target_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Public preview: click "Open in browser" if present.
        for button_text in ["Открыть в браузере", "Открыть в браузер", "Открыть"]:
            try:
                await page.get_by_text(button_text, exact=False).first.click(timeout=3000)
                await page.wait_for_timeout(2000)
                break
            except Exception:
                pass

        # Choose phone login.
        try:
            await page.get_by_text("Войти по номеру телефона", exact=False).click(timeout=3000)
            await page.wait_for_timeout(1000)
        except Exception:
            print("Phone-login button not found; if you are already logged in, state will be saved.")

        # Enter phone number.
        phone = input("Enter your MAX phone number (+7...): ").strip()
        if phone:
            try:
                await page.locator("input[type='tel']").fill(phone)
                await page.get_by_role("button", name=re.compile("продолжить", re.IGNORECASE)).click(timeout=5000)
            except Exception as exc:
                print(f"Could not fill phone number: {exc}")

        # Enter SMS code.
        code = input("Enter the SMS code from MAX: ").strip()
        if code:
            try:
                # MAX code inputs are usually 4-6 separate digit boxes or one field.
                for idx, digit in enumerate(code):
                    await page.locator(f"input[aria-label*='код' i], input[type='number']").nth(idx).fill(digit)
                await page.get_by_role("button", name=re.compile("войти", re.IGNORECASE)).click(timeout=5000)
            except Exception as exc:
                print(f"Could not fill SMS code: {exc}")

        # Wait for the post/dashboard to load (i.e. login page text disappears).
        await page.wait_for_timeout(5000)
        body = await page.locator("body").inner_text()
        if "войдите в max" in body.lower():
            print("Login appears to have failed - please check the phone number and code.")
        else:
            await context.storage_state(path=str(session_path))
            print(f"MAX session saved to {session_path.resolve()}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
