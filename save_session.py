"""
save_session.py
Open a browser, log in to any website manually, save the session.
Next time the agent will use it automatically — no login needed.
"""
import asyncio
import os
from playwright.async_api import async_playwright

DATA_DIR = "sessions"


async def record_session():
    os.makedirs(DATA_DIR, exist_ok=True)

    url = input("Enter URL: ").strip()
    if not url.startswith("http"):
        url = "https://" + url

    print("\n  Browser opening...")
    print("  → Log in to the website manually")
    print("  → Once done, come back here and press Enter\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page    = await context.new_page()

        await page.goto(url)

        input("  Press Enter when you are logged in and ready to save... ")

        filename = input("  Session name (e.g. google): ").strip()
        if not filename.endswith(".json"):
            filename += ".json"

        filepath = os.path.join(DATA_DIR, filename)
        await context.storage_state(path=filepath)

        print(f"\n  ✓ Session saved → {filepath}")
        print(f"  Use it with:  session_name = \"{filename.replace('.json','')}\"")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(record_session())