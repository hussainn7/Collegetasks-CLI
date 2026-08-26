"""Diagnostic script to inspect the iCollege session and page structure.

Captures what the browser actually sees after login — URLs, status codes,
page content, and all links — so we can fix the course parser.
"""

import sys
import json
sys.path.insert(0, ".")

from playwright.sync_api import sync_playwright
from config import settings
from rich.console import Console

console = Console()

def run_diagnostics():
    settings.ensure_data_dir()

    if not settings.session_path.is_file():
        console.print("[red]No session file found. Run 'python main.py login' first.[/red]")
        return

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

        # ── Test 1: Navigate to base URL ──────────────────────────
        console.print("\n[bold cyan]Test 1: Navigate to base iCollege URL[/bold cyan]")
        console.print(f"  URL: {settings.icollege_url}")
        response = page.goto(settings.icollege_url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=15_000)
        console.print(f"  Status: {response.status if response else 'No response'}")
        console.print(f"  Final URL: {page.url}")
        console.print(f"  Title: {page.title()}")

        # Screenshot
        page.screenshot(path="data/diag_step1_base.png")
        console.print("  📸 Screenshot: data/diag_step1_base.png")

        # ── Test 2: Try /d2l/home ─────────────────────────────────
        console.print("\n[bold cyan]Test 2: Navigate to /d2l/home[/bold cyan]")
        base = settings.icollege_url.rstrip("/")
        response = page.goto(f"{base}/d2l/home", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=15_000)
        console.print(f"  Status: {response.status if response else 'No response'}")
        console.print(f"  Final URL: {page.url}")
        console.print(f"  Title: {page.title()}")

        page.screenshot(path="data/diag_step2_d2l_home.png")
        console.print("  📸 Screenshot: data/diag_step2_d2l_home.png")

        # ── Test 3: Try /d2l/le/dashboard ─────────────────────────
        console.print("\n[bold cyan]Test 3: Navigate to /d2l/le/dashboard[/bold cyan]")
        response = page.goto(f"{base}/d2l/le/dashboard", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=15_000)
        console.print(f"  Status: {response.status if response else 'No response'}")
        console.print(f"  Final URL: {page.url}")
        console.print(f"  Title: {page.title()}")

        page.screenshot(path="data/diag_step3_dashboard.png")
        console.print("  📸 Screenshot: data/diag_step3_dashboard.png")

        # ── Test 4: Dump all links from the current page ──────────
        console.print("\n[bold cyan]Test 4: All links on current page[/bold cyan]")
        links = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                href: a.href,
                text: a.innerText.trim().substring(0, 80),
                classes: a.className.substring(0, 60)
            })).filter(l => l.href && !l.href.startsWith('javascript'));
        }""")

        # Filter for interesting links (d2l related)
        d2l_links = [l for l in links if "d2l" in l["href"].lower() or "home" in l["href"].lower()]
        console.print(f"  Total links: {len(links)}")
        console.print(f"  D2L-related links: {len(d2l_links)}")

        for link in d2l_links[:30]:
            text_preview = link["text"][:50] if link["text"] else "(no text)"
            console.print(f"    [dim]{link['href']}[/dim]")
            console.print(f"      Text: {text_preview}")

        # ── Test 5: Check for enrollment API ──────────────────────
        console.print("\n[bold cyan]Test 5: Try D2L enrollment API[/bold cyan]")
        api_urls = [
            f"{base}/d2l/api/lp/1.43/enrollments/myenrollments/",
            f"{base}/d2l/api/lp/1.28/enrollments/myenrollments/",
            f"{base}/d2l/api/lp/1.47/enrollments/myenrollments/",
        ]
        for api_url in api_urls:
            response = page.goto(api_url, wait_until="domcontentloaded")
            status = response.status if response else "No response"
            console.print(f"  {api_url}")
            console.print(f"    Status: {status}")
            if response and response.ok:
                try:
                    body = page.inner_text("body")[:500]
                    console.print(f"    Body preview: {body[:300]}")
                except Exception:
                    pass
                break  # Found a working version

        # ── Test 6: Check page HTML structure ─────────────────────
        console.print("\n[bold cyan]Test 6: Page body snippet (from base URL)[/bold cyan]")
        page.goto(settings.icollege_url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=15_000)

        body_html = page.evaluate("() => document.body.innerHTML.substring(0, 3000)")
        # Save full HTML for inspection
        with open("data/diag_page_body.html", "w") as f:
            full_html = page.evaluate("() => document.body.innerHTML")
            f.write(full_html)
        console.print(f"  Full HTML saved to: data/diag_page_body.html")
        console.print(f"  Body preview (first 500 chars):")
        console.print(f"  [dim]{body_html[:500]}[/dim]")

        browser.close()

    console.print("\n[bold green]✓ Diagnostics complete![/bold green]")
    console.print("Check the data/ directory for screenshots and HTML dumps.")


if __name__ == "__main__":
    run_diagnostics()
