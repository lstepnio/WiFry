#!/usr/bin/env bash
# Run this script to capture screenshots of all WiFry tabs
# Requires: chromium/chrome, a running WiFry instance

URL="${1:-http://localhost:54126}"
DIR="$(dirname "$0")"

echo "Capturing WiFry screenshots from $URL..."
echo "Make sure the WiFry frontend is running."

# Use Python + playwright if available, otherwise instruction
if command -v python3 &>/dev/null; then
    python3 << PYEOF
import sys
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Install playwright: pip install playwright && playwright install chromium")
    sys.exit(1)

url = "$URL"
out = "$DIR"
tabs = [
    ("sessions", "Sessions"),
    ("impairments", "Impairments"),
    ("adb", "ADB"),
    ("captures", "Captures"),
    ("streams", "Streams"),
    ("sharing", "Sharing"),
    ("settings", "Settings"),
]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    
    for tab_id, label in tabs:
        page.goto(url)
        page.wait_for_timeout(1000)
        # Click the tab
        page.click(f'nav button:has-text("{label}")')
        page.wait_for_timeout(1500)
        page.screenshot(path=f"{out}/{tab_id}.png", full_page=False)
        print(f"  Captured: {tab_id}.png")
    
    # Settings subtabs
    for subtab in ["System", "Network Config", "Tools", "App Settings"]:
        page.goto(url)
        page.wait_for_timeout(500)
        page.click('nav button:has-text("Settings")')
        page.wait_for_timeout(500)
        page.click(f'button:has-text("{subtab}")')
        page.wait_for_timeout(1000)
        safe = subtab.lower().replace(" ", "-")
        page.screenshot(path=f"{out}/settings-{safe}.png", full_page=False)
        print(f"  Captured: settings-{safe}.png")
    
    browser.close()
    print("Done!")
PYEOF
else
    echo "Python3 not found. Screenshots must be captured manually."
fi
