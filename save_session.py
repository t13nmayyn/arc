"""
Save browser sessions for A.R.C to reuse.
Run once per site, then the agent handles everything.
"""
from playwright.async_api import async_playwright
import asyncio
import os

DATA_DIR = 'sessions'

async def record_session():
    os.makedirs(DATA_DIR, exist_ok=True)

    url = input("Enter URL: ")
    if not url.startswith("http"):
        url = 'https://' + url

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page    = await context.new_page()

        await page.goto(url)
        print("\n  Browser is open.")
        print("  Log in manually in the browser window.")
        print("  When done, come back here and press Enter.\n")

        input("  Press Enter when you are logged in... ")

        filename = input("  Save session as (e.g. google.json): ").strip()
        if not filename.endswith(".json"):
            filename += ".json"

        filepath = os.path.join(DATA_DIR, filename)
        await context.storage_state(path=filepath)
        print(f"\n  Session saved → {filepath}")
        await browser.close()

asyncio.run(record_session())