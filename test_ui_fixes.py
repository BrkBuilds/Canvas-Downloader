#!/usr/bin/env python3
"""
Test script to verify the UI fixes for:
1. Button styling in dialogs (segmented control)
2. Vertical spacing (Show label, h3, separators)
"""
import asyncio
from playwright.async_api import async_playwright
import json

async def test_ui_fixes():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 1024})
        page = await context.new_page()

        try:
            # Navigate to the app
            print("🔄 Loading app...")
            await page.goto("http://localhost:8501", wait_until="domcontentloaded", timeout=10000)

            # Wait for Streamlit to fully load
            await asyncio.sleep(3)
            print("✅ App loaded")

            # Take a screenshot of the initial state
            await page.screenshot(path="/tmp/01_initial_state.png")
            print("📸 Screenshot 1: Initial state")

            # Look for the dialog triggers - we need to navigate to where the dialogs are
            # The app likely has API token input, so let's check what's on the page

            # Get page content to understand structure
            body_html = await page.content()
            if "Select Course to sync" in body_html or "sync" in body_html.lower():
                print("✅ Found sync dialog trigger")
            else:
                print("⚠️ Sync dialog trigger not immediately visible, may need to scroll/interact")

            # Check for button styling by inspecting computed styles
            print("\n🔍 Checking segmented control button styling...")

            # Look for buttons with "Favorites Only" text
            fav_buttons = await page.locator("text=Favorites Only").all()
            if fav_buttons:
                print(f"✅ Found {len(fav_buttons)} 'Favorites Only' button(s)")
                for i, btn in enumerate(fav_buttons):
                    try:
                        # Get computed style
                        bg_color = await btn.evaluate("el => window.getComputedStyle(el).backgroundColor")
                        opacity = await btn.evaluate("el => window.getComputedStyle(el).opacity")
                        border = await btn.evaluate("el => window.getComputedStyle(el).border")
                        print(f"  Button {i}: bg={bg_color}, opacity={opacity}, border={border}")
                    except Exception as e:
                        print(f"  Button {i}: Could not get styles - {e}")

            # Check spacing by measuring element positions
            print("\n📐 Checking element spacing...")

            show_labels = await page.locator("text=Show:").all()
            if show_labels:
                print(f"✅ Found {len(show_labels)} 'Show:' label(s)")
                for i, label in enumerate(show_labels):
                    bbox = await label.bounding_box()
                    if bbox:
                        print(f"  Label {i}: y={bbox['y']}, height={bbox['height']}")

            # Take screenshots of different sections
            await page.screenshot(path="/tmp/02_page_full.png")
            print("📸 Screenshot 2: Full page")

            print("\n✅ Test script completed successfully")
            print("📋 Screenshots saved to /tmp/0*.png")

        except Exception as e:
            print(f"❌ Error during testing: {e}")
            # Take screenshot of error state
            try:
                await page.screenshot(path="/tmp/error_state.png")
                print("📸 Screenshot of error state saved")
            except:
                pass

        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_ui_fixes())
