"""Session validation and persistent browser context management.

Uses Playwright's launch_persistent_context to maintain a real Chrome
profile on disk. This means all cookies (including Duo MFA trust tokens
and D2L session cookies) survive across browser restarts.

Key behavior:
  - Session cookies auto-renew each time the browser visits D2L
  - Duo "trust this browser" lasts ~30 days
  - If the session does expire, auto-attempts re-auth via the SAML
    endpoint before giving up (the persistent profile often has enough
    state for SSO to succeed without manual intervention)
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Generator

from playwright.sync_api import (
    sync_playwright,
    Page,
    BrowserContext,
    Playwright,
    TimeoutError as PwTimeout,
)
from rich.console import Console

from config import settings

console = Console()


def _profile_exists() -> bool:
    """Check if the persistent browser profile directory exists and has data."""
    profile = settings.browser_profile_path
    return profile.is_dir() and any(profile.iterdir())


def validate_session(page: Page) -> bool:
    """Check if the persistent profile is still authenticated against D2L.

    Uses the lightweight /d2l/api/lp/1.43/users/whoami endpoint.
    Returns True if authenticated, False otherwise.
    """
    d2l_base = settings.d2l_base_url.rstrip("/")

    try:
        whoami_url = f"{d2l_base}/d2l/api/lp/1.43/users/whoami"
        response = page.goto(whoami_url, wait_until="domcontentloaded", timeout=20_000)

        if response:
            current_url = page.url.lower()

            # Redirected to SSO → session expired
            if any(m in current_url for m in [
                "idp.gsu.edu", "initiate-login", "shibboleth"
            ]):
                return False

            # API returned 200 → authenticated
            if response.status == 200:
                return True

            # 403 → cookies present but session expired on server
            if response.status == 403:
                return False

        return False

    except PwTimeout:
        return False
    except Exception:
        return False


def _try_silent_reauth(context: BrowserContext) -> bool:
    """Attempt silent re-authentication via the SAML endpoint.

    Because the persistent profile retains Duo's trust cookie and the
    IdP's session cookie, SSO can often complete automatically without
    any user interaction. This is what makes the cron job work.

    Returns True if re-auth succeeded, False if manual login is needed.
    """
    console.print("[yellow]Session expired — attempting silent re-auth...[/yellow]")

    page = context.new_page()
    try:
        # Navigate to the SAML login URL
        page.goto(
            settings.saml_login_url,
            wait_until="domcontentloaded",
            timeout=30_000,
        )

        # Wait up to 30 seconds for SSO to complete automatically
        # (IdP session + Duo trust cookie should carry us through)
        try:
            page.wait_for_function(
                """() => {
                    const url = window.location.href.toLowerCase();
                    return url.includes('gastate.view.usg.edu') && (
                        url.includes('/d2l/home') ||
                        url.includes('/d2l/le/') ||
                        url.includes('/d2l/lp/')
                    ) && !url.includes('initiate-login');
                }""",
                timeout=30_000,
            )
            page.wait_for_load_state("networkidle", timeout=10_000)
            console.print("[green]✓ Silent re-auth succeeded![/green]")
            return True
        except PwTimeout:
            # SSO didn't complete automatically — needs manual login
            return False
    except Exception:
        return False
    finally:
        page.close()


@contextmanager
def authenticated_context(
    headless: bool | None = None,
) -> Generator[Page, None, None]:
    """Context manager that yields an authenticated Playwright Page.

    Uses a persistent browser profile so sessions survive across runs.
    If the session has expired, attempts silent re-authentication via
    the saved IdP/Duo cookies. Only fails if manual login is truly needed.

    Usage:
        with authenticated_context() as page:
            page.goto("https://gastate.view.usg.edu/d2l/home")
            # ... scrape away
    """
    settings.ensure_data_dir()
    profile_path = str(settings.browser_profile_path)
    use_headless = headless if headless is not None else settings.headless

    if not _profile_exists():
        console.print(
            "[bold red]✗ No browser profile found.[/bold red] "
            "Run [bold]python main.py login[/bold] first."
        )
        sys.exit(1)

    pw: Playwright = sync_playwright().start()
    context: BrowserContext | None = None

    try:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=use_headless,
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

        # Validate the session
        console.print("[dim]Validating session...[/dim]")
        if validate_session(page):
            console.print("[green]✓ Session valid[/green]")
            yield page
            return

        # Session expired — try silent re-auth
        if _try_silent_reauth(context):
            # Re-validate on the original page
            if validate_session(page):
                console.print("[green]✓ Session restored[/green]")
                yield page
                return

        # Silent re-auth failed — manual login needed
        console.print(
            "[bold red]✗ Session expired and silent re-auth failed.[/bold red]\n"
            "Run [bold]python main.py login[/bold] to re-authenticate.\n"
            "[dim]Tip: Check 'Remember me' in Duo to extend trust to 30 days.[/dim]"
        )
        sys.exit(1)

    finally:
        if context:
            context.close()
        pw.stop()
