"""Interactive Playwright login for GSU iCollege SSO.

This module launches a visible browser window so the user can complete
the full SSO flow (CampusID + password + Duo MFA). After successful
authentication, the browser session state (cookies + localStorage) is
saved to disk for headless reuse in subsequent scraping runs.

Key discovery: icollege.gsu.edu is a WordPress landing page.
The actual D2L Brightspace instance lives at gastate.view.usg.edu.
Login is initiated via SAML SSO through GSU's Shibboleth IdP.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
from rich.console import Console
from rich.panel import Panel

from config import settings

console = Console()


# Maximum time (ms) to wait for the user to complete MFA
_LOGIN_TIMEOUT_MS = 5 * 60 * 1000  # 5 minutes


def _is_authenticated(url: str) -> bool:
    """Check if the current URL indicates a successful D2L login.

    After SAML SSO completes, the browser lands on the D2L homepage
    at gastate.view.usg.edu/d2l/home or similar.
    """
    url_lower = url.lower()
    d2l_host = "gastate.view.usg.edu"
    return (
        d2l_host in url_lower
        and any(p in url_lower for p in ["/d2l/home", "/d2l/le/", "/d2l/lp/"])
        # Exclude the SAML initiate-login URL itself
        and "initiate-login" not in url_lower
    )


def interactive_login() -> Path:
    """Launch a headed browser for the user to complete SSO login.

    Returns the path to the saved session state file.

    Flow:
        1. Open Chromium (headed) → navigate to SAML login URL
        2. GSU Shibboleth IdP handles the SSO redirect
        3. User completes CampusID + password + Duo MFA
        4. SAML assertion redirects back to gastate.view.usg.edu
        5. Wait until the URL indicates successful D2L authentication
        6. Save storageState (cookies + localStorage) to disk
    """
    settings.ensure_data_dir()
    session_path = settings.session_path

    console.print(
        Panel(
            "[bold cyan]iCollege SSO Login[/bold cyan]\n\n"
            "A browser window will open to the GSU login page.\n"
            "Please:\n"
            "  1. Enter your [bold]CampusID[/bold] and password\n"
            "  2. Complete [bold]Duo MFA[/bold] verification\n"
            "  3. Wait until the iCollege/D2L dashboard loads\n\n"
            "The window will close automatically once login succeeds.\n"
            f"[dim]D2L Host: gastate.view.usg.edu[/dim]\n"
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
            # Navigate to the SAML SSO login entry point
            login_url = settings.saml_login_url
            console.print(f"[dim]Navigating to SAML login...[/dim]")
            console.print(f"[dim]{login_url}[/dim]")
            page.goto(login_url, wait_until="domcontentloaded")

            # Wait for the user to complete login and land on D2L
            console.print("[yellow]Waiting for you to complete login...[/yellow]")
            page.wait_for_function(
                """() => {
                    const url = window.location.href.toLowerCase();
                    const host = 'gastate.view.usg.edu';
                    return url.includes(host) && (
                        url.includes('/d2l/home') ||
                        url.includes('/d2l/le/') ||
                        url.includes('/d2l/lp/')
                    ) && !url.includes('initiate-login');
                }""",
                timeout=_LOGIN_TIMEOUT_MS,
            )

            # Give the page a moment to fully stabilize cookies
            page.wait_for_load_state("networkidle", timeout=15_000)

            console.print(f"[dim]Authenticated! Final URL: {page.url}[/dim]")

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
