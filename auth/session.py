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
    """Check if the saved session is still authenticated against D2L.

    Uses a lightweight API endpoint to avoid full page loads and
    networkidle waits that can time out on slow connections.

    Returns True if the session is valid, False otherwise.
    """
    d2l_base = settings.d2l_base_url.rstrip("/")

    try:
        # Use a lightweight API endpoint — the "whoami" call is fast
        # and clearly tells us if we're authenticated
        whoami_url = f"{d2l_base}/d2l/api/lp/1.43/users/whoami"
        response = page.goto(whoami_url, wait_until="domcontentloaded", timeout=20_000)

        if response:
            current_url = page.url.lower()

            # If we got redirected to SSO, session is expired
            if any(marker in current_url for marker in [
                "idp.gsu.edu", "initiate-login", "shibboleth", "cas/login"
            ]):
                return False

            # If API returned 200, we're authenticated
            if response.status == 200:
                return True

            # 403 means the cookies are there but the session expired
            if response.status == 403:
                return False

        # Fallback: try loading the D2L homepage
        response2 = page.goto(f"{d2l_base}/d2l/home", wait_until="domcontentloaded", timeout=20_000)
        current_url = page.url.lower()

        if "gastate.view.usg.edu" in current_url and "/d2l/" in current_url:
            if "initiate-login" not in current_url:
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
