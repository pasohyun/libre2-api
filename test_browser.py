from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    print("connecting...")
    browser = p.chromium.connect_over_cdp(
        "wss://brd-customer-hl_f971a954-zone-scraping_browser1:d4v3nb7vti4c@brd.superproxy.io:9222",
        timeout=30000,
    )
    print("connected!")
    page = browser.new_page()
    page.goto("https://example.com")
    print(page.title())
    browser.close()
    print("done!")
