"""Diagnose why announcement scraping returns 0 results.

Navigates to a specific course's announcement page, captures:
- Network requests/responses (especially API calls)
- Page HTML structure
- Screenshots
"""

import sys
sys.path.insert(0, ".")

from playwright.sync_api import sync_playwright, Response
from config import settings
from rich.console import Console

console = Console()

# Target course (Calculus)
COURSE_ORG_ID = "3693899"
COURSE_NAME = "CALCULUS OF ONE VARIABLE I"


def run():
    settings.ensure_data_dir()
    base_url = settings.d2l_base_url.rstrip("/")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            storage_state=str(settings.session_path),
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # Track ALL network responses
        api_responses = []

        def on_response(response: Response):
            url = response.url
            if "/d2l/api/" in url or "/news" in url.lower():
                status = response.status
                api_responses.append({"url": url, "status": status})
                console.print(f"  [dim]API: {status} {url[:120]}[/dim]")

        page.on("response", on_response)

        # ── Test 1: Course homepage ───────────────────────────────
        console.print(f"\n[bold cyan]Test 1: Course homepage[/bold cyan]")
        course_url = f"{base_url}/d2l/home/{COURSE_ORG_ID}"
        console.print(f"  URL: {course_url}")
        resp = page.goto(course_url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=20_000)
        console.print(f"  Status: {resp.status if resp else 'N/A'}")
        console.print(f"  Final URL: {page.url}")
        console.print(f"  Title: {page.title()}")
        page.screenshot(path="data/diag_course_home.png")

        # ── Test 2: News/Announcements page ───────────────────────
        console.print(f"\n[bold cyan]Test 2: News page (legacy URL)[/bold cyan]")
        news_url = f"{base_url}/d2l/lms/news/main.d2l?ou={COURSE_ORG_ID}"
        console.print(f"  URL: {news_url}")
        resp = page.goto(news_url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=20_000)
        console.print(f"  Status: {resp.status if resp else 'N/A'}")
        console.print(f"  Final URL: {page.url}")
        console.print(f"  Title: {page.title()}")
        page.screenshot(path="data/diag_news_page.png")

        # Save HTML
        with open("data/diag_news_body.html", "w") as f:
            f.write(page.evaluate("() => document.body.innerHTML"))
        console.print("  HTML saved: data/diag_news_body.html")

        # Check for any announcement-like content
        body_text = page.inner_text("body")
        console.print(f"  Body text length: {len(body_text)} chars")
        console.print(f"  Body preview: {body_text[:300]}")

        # ── Test 3: Direct API news endpoint ──────────────────────
        console.print(f"\n[bold cyan]Test 3: Direct API /news/ calls[/bold cyan]")
        for version in ["1.74", "1.67", "1.48", "1.43"]:
            api_url = f"{base_url}/d2l/api/le/{version}/{COURSE_ORG_ID}/news/"
            resp = page.goto(api_url, wait_until="domcontentloaded")
            status = resp.status if resp else "N/A"
            console.print(f"  v{version}: {status}")
            if resp and resp.ok:
                body = page.inner_text("body")
                console.print(f"    Response: {body[:500]}")
                break

        # ── Test 4: Course content page ───────────────────────────
        console.print(f"\n[bold cyan]Test 4: Course content page[/bold cyan]")
        content_url = f"{base_url}/d2l/le/content/{COURSE_ORG_ID}/Home"
        console.print(f"  URL: {content_url}")
        resp = page.goto(content_url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=20_000)
        console.print(f"  Status: {resp.status if resp else 'N/A'}")
        console.print(f"  Final URL: {page.url}")
        page.screenshot(path="data/diag_course_content.png")

        # ── Summary ───────────────────────────────────────────────
        console.print(f"\n[bold cyan]Summary: {len(api_responses)} API calls captured[/bold cyan]")
        for r in api_responses:
            console.print(f"  [{r['status']}] {r['url'][:140]}")

        page.remove_listener("response", on_response)
        browser.close()

    console.print("\n[bold green]✓ Done![/bold green] Check data/ for screenshots.")


if __name__ == "__main__":
    run()
