"""Interactive Playwright login for GSU iCollege SSO.

Uses a PERSISTENT browser profile so that session cookies, Duo's
"trust this browser" token, and all auth state survive across runs —
just like a real Chrome installation. This means:

  - After the first login + Duo MFA, subsequent runs reuse the profile
  - Duo "remember me for 30 days" works because the cookie persists
  - D2L session cookies auto-renew on each visit
  - You only need to re-login if the profile is deleted or Duo trust expires
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


def _is_on_d2l_dashboard(url: str) -> bool:
    """Check if the URL indicates a successful D2L login."""
    url_lower = url.lower()
    return (
        "gastate.view.usg.edu" in url_lower
        and any(p in url_lower for p in ["/d2l/home", "/d2l/le/", "/d2l/lp/"])
        and "initiate-login" not in url_lower
    )


def interactive_login() -> None:
    """Launch a headed persistent browser for the user to complete SSO login.

    Uses launch_persistent_context so the browser profile (cookies,
    localStorage, Duo trust, etc.) is saved to disk permanently.
    After the first successful login + Duo MFA, the profile persists
    and future runs won't need to re-authenticate.
    """
    settings.ensure_data_dir()
    profile_path = str(settings.browser_profile_path)

    console.print(
        Panel(
            "[bold cyan]iCollege SSO Login[/bold cyan]\n\n"
            "A browser window will open to the GSU login page.\n"
            "Please:\n"
            "  1. Enter your [bold]CampusID[/bold] and password\n"
            "  2. Complete [bold]Duo MFA[/bold] verification\n"
            "  3. [bold yellow]Check 'Remember me' / 'Trust this browser'[/bold yellow]\n"
            "     in Duo so you won't need MFA again for 30 days\n"
            "  4. Wait until the iCollege/D2L dashboard loads\n\n"
            "The window will close automatically once login succeeds.\n"
            f"[dim]Profile: {profile_path}[/dim]\n"
            f"[dim]Timeout: 5 minutes[/dim]",
            title="🔐 Login Required",
            border_style="cyan",
        )
    )

    with sync_playwright() as pw:
        # Use a persistent context — this is the key difference.
        # All cookies, localStorage, service workers, and Duo trust
        # tokens are stored in the profile directory and survive
        # browser restarts.
        context = pw.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            ignore_default_args=["--enable-automation"],
        )

        page = context.pages[0] if context.pages else context.new_page()

        try:
            # Navigate to the SAML SSO login entry point
            login_url = settings.saml_login_url
            console.print(f"[dim]Navigating to SAML login...[/dim]")
            page.goto(login_url, wait_until="domcontentloaded")

            # Check if we're already authenticated (profile still valid)
            current_url = page.url.lower()
            if _is_on_d2l_dashboard(current_url):
                console.print(
                    "[bold green]✓ Already authenticated![/bold green] "
                    "Profile is still valid — no login needed."
                )
                context.close()
                return

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

            # Let the page fully load so all cookies are set
            page.wait_for_load_state("networkidle", timeout=15_000)

            console.print(f"[dim]Authenticated! Final URL: {page.url}[/dim]")
            console.print(
                "[bold green]✓ Login successful![/bold green] "
                f"Profile saved to [dim]{profile_path}[/dim]\n"
                "[dim]Session will persist across runs. "
                "Duo trust lasts ~30 days.[/dim]"
            )

        except PwTimeout:
            console.print(
                "[bold red]✗ Login timed out.[/bold red] "
                "Please try again and complete login within 5 minutes."
            )
            context.close()
            sys.exit(1)

        except Exception as exc:
            console.print(f"[bold red]✗ Login failed:[/bold red] {exc}")
            context.close()
            sys.exit(1)

        finally:
            context.close()


if __name__ == "__main__":
    interactive_login()
