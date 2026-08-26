"""Interactive Playwright login for GSU iCollege SSO.

This module launches a visible browser window so the user can complete
the full SSO flow (CampusID + password + Duo MFA). After successful
authentication, the browser session state (cookies + localStorage) is
saved to disk for headless reuse in subsequent scraping runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
from rich.console import Console
from rich.panel import Panel

from config import settings

console = Console()


# Markers that indicate we've landed on an authenticated D2L page
_DASHBOARD_INDICATORS = [
    "d2l/home",            # D2L homepage URL fragment
    "d2l/le/dashboard",    # Alternative dashboard path
]

# Maximum time (ms) to wait for the user to complete MFA
_LOGIN_TIMEOUT_MS = 5 * 60 * 1000  # 5 minutes


def _is_authenticated(url: str) -> bool:
    """Check if the current URL looks like an authenticated D2L page."""
    return any(indicator in url.lower() for indicator in _DASHBOARD_INDICATORS)


def interactive_login() -> Path:
    """Launch a headed browser for the user to complete SSO login.

    Returns the path to the saved session state file.

    Flow:
        1. Open Chromium (headed) → navigate to iCollege
        2. User completes SSO (CampusID + password + Duo)
        3. Wait until the URL indicates successful authentication
        4. Save storageState to disk
    """
    settings.ensure_data_dir()
    session_path = settings.session_path

    console.print(
        Panel(
            "[bold cyan]iCollege SSO Login[/bold cyan]\n\n"
            "A browser window will open. Please:\n"
            "  1. Enter your [bold]CampusID[/bold] and password\n"
            "  2. Complete [bold]Duo MFA[/bold] verification\n"
            "  3. Wait until the iCollege dashboard loads\n\n"
            "The window will close automatically once login succeeds.\n"
            f"[dim]Timeout: 5 minutes[/dim]",
            title="🔐 Login Required",
            border_style="cyan",
        )
    )

    with sync_playwright() as pw:
        # Launch a visible browser so the user can interact with SSO
        browser = pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            # Navigate to iCollege — this will redirect through SSO
            console.print(f"[dim]Navigating to {settings.icollege_url}...[/dim]")
            page.goto(settings.icollege_url, wait_until="domcontentloaded")

            # Wait for the user to complete login and land on the dashboard
            console.print("[yellow]Waiting for you to complete login...[/yellow]")
            page.wait_for_function(
                """() => {
                    const url = window.location.href.toLowerCase();
                    return url.includes('d2l/home') || url.includes('d2l/le/dashboard');
                }""",
                timeout=_LOGIN_TIMEOUT_MS,
            )

            # Give the page a moment to fully stabilize cookies
            page.wait_for_load_state("networkidle", timeout=15_000)

            # Save the authenticated session state
            context.storage_state(path=str(session_path))
            console.print(
                f"[bold green]✓ Login successful![/bold green] "
                f"Session saved to [dim]{session_path}[/dim]"
            )

        except PwTimeout:
            console.print(
                "[bold red]✗ Login timed out.[/bold red] "
                "Please try again and complete login within 5 minutes."
            )
            browser.close()
            sys.exit(1)

        except Exception as exc:
            console.print(f"[bold red]✗ Login failed:[/bold red] {exc}")
            browser.close()
            sys.exit(1)

        finally:
            browser.close()

    return session_path


if __name__ == "__main__":
    interactive_login()
