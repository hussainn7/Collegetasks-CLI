"""Session validation and headless browser context management.

This module loads a previously saved Playwright session state and
validates that it's still authenticated against D2L Brightspace
at gastate.view.usg.edu. It provides a context manager that yields
a ready-to-use Playwright Page object.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from playwright.sync_api import (
    sync_playwright,
    Page,
    BrowserContext,
    Browser,
    Playwright,
    TimeoutError as PwTimeout,
)
from rich.console import Console

from config import settings

console = Console()


def session_exists() -> bool:
    """Check if a session state file exists on disk."""
    return settings.session_path.is_file()


def validate_session(page: Page) -> bool:
    """Navigate to D2L and check if the session is still authenticated.

    Returns True if the session is valid (we land on a D2L page),
    False if we get redirected to SSO login.
    """
    try:
        # Navigate to the actual D2L homepage, not the WordPress landing page
        d2l_home = f"{settings.d2l_base_url.rstrip('/')}/d2l/home"
        response = page.goto(d2l_home, wait_until="domcontentloaded", timeout=30_000)

        # Wait for any redirects to settle
        page.wait_for_load_state("networkidle", timeout=15_000)

        current_url = page.url.lower()
        d2l_host = "gastate.view.usg.edu"

        # If we're still on the D2L host and on a real page, session is valid
        if d2l_host in current_url and "/d2l/" in current_url:
            # But check we didn't land on the login page
            if "initiate-login" in current_url or "auth/saml" in current_url:
                return False

            # Check page title for "Page not found" (404 within D2L)
            title = page.title().lower()
            if "not found" in title or "error" in title:
                # Could be a 404 but still authenticated — try the /d2l/lp/ path
                lp_url = f"{settings.d2l_base_url.rstrip('/')}/d2l/lp/ouHome.d2l"
                response2 = page.goto(lp_url, wait_until="domcontentloaded", timeout=15_000)
                page.wait_for_load_state("networkidle", timeout=10_000)
                current_url2 = page.url.lower()
                if d2l_host in current_url2 and "initiate-login" not in current_url2:
                    return True
                return False

            return True

        # If we got redirected to an SSO/IdP page, session has expired
        if any(
            marker in current_url
            for marker in ["idp.gsu.edu", "cas/login", "sso", "shibboleth", "initiate-login"]
        ):
            return False

        # If we're not on the D2L host at all, something went wrong
        if d2l_host not in current_url:
            return False

        # Fallback: check if response was OK
        if response and response.ok:
            return True

        return False

    except PwTimeout:
        console.print("[yellow]⚠ Session validation timed out[/yellow]")
        return False
    except Exception as exc:
        console.print(f"[yellow]⚠ Session validation error: {exc}[/yellow]")
        return False


@contextmanager
def authenticated_context(
    headless: bool | None = None,
) -> Generator[Page, None, None]:
    """Context manager that yields an authenticated Playwright Page.

    Usage:
        with authenticated_context() as page:
            page.goto("https://gastate.view.usg.edu/d2l/home")
            # ... scrape away

    If the session is invalid or missing, prints an error and exits.
    """
    if not session_exists():
        console.print(
            "[bold red]✗ No session found.[/bold red] "
            "Run [bold]python main.py login[/bold] first."
        )
        sys.exit(1)

    use_headless = headless if headless is not None else settings.headless

    pw: Playwright = sync_playwright().start()
    browser: Browser | None = None

    try:
        browser = pw.chromium.launch(
            headless=use_headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context: BrowserContext = browser.new_context(
            storage_state=str(settings.session_path),
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # Validate the session before yielding
        console.print("[dim]Validating session...[/dim]")
        if not validate_session(page):
            console.print(
                "[bold red]✗ Session expired.[/bold red] "
                "Run [bold]python main.py login[/bold] to re-authenticate."
            )
            sys.exit(1)

        console.print("[green]✓ Session valid[/green]")
        yield page

    finally:
        if browser:
            browser.close()
        pw.stop()
