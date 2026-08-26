"""Per-course announcement scraper.

Uses a hybrid strategy:
  1. PRIMARY — Network interception: capture D2L's internal API calls
     to /d2l/api/le/*/news/ and parse the JSON directly.
  2. FALLBACK — DOM scraping: parse announcement elements from the
     rendered HTML if the API call isn't intercepted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from playwright.sync_api import Page, Response
from rich.console import Console

from config import settings
from scraper.courses import Course

console = Console()


@dataclass
class Announcement:
    """A single course announcement."""

    announcement_id: str
    course_id: str
    course_name: str
    title: str
    body_html: str
    body_text: str
    created_date: str          # ISO 8601 string
    author: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_d2l_date(date_str: str) -> str:
    """Parse a D2L API date string into ISO 8601 format.

    D2L dates come in formats like:
        "2026-08-25T14:30:00.000Z"
        "2026-08-25T14:30:00.000+00:00"
    """
    if not date_str:
        return datetime.now(timezone.utc).isoformat()

    # Strip any trailing 'Z' and replace with +00:00 for fromisoformat
    cleaned = date_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        return dt.isoformat()
    except ValueError:
        return date_str


def _strip_html(html: str) -> str:
    """Simple HTML tag stripping for text extraction."""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Decode common HTML entities
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    return text


def scrape_announcements_api(
    page: Page,
    course: Course,
) -> list[Announcement]:
    """Scrape announcements via D2L API network interception.

    Navigates to the course homepage and intercepts the internal
    API call to /d2l/api/le/<version>/<orgUnitId>/news/.
    """
    announcements: list[Announcement] = []
    captured_responses: list[dict] = []

    def handle_response(response: Response) -> None:
        """Capture D2L news API responses."""
        url = response.url
        if "/api/le/" in url and "/news" in url and response.ok:
            try:
                data = response.json()
                if isinstance(data, list):
                    captured_responses.extend(data)
                elif isinstance(data, dict) and "Items" in data:
                    captured_responses.extend(data["Items"])
                elif isinstance(data, dict):
                    captured_responses.append(data)
            except Exception:
                pass  # Response wasn't JSON

    # Attach the response interceptor
    page.on("response", handle_response)

    try:
        # Navigate to the course homepage
        base_url = settings.icollege_url.rstrip("/")
        course_home = f"{base_url}/d2l/home/{course.org_unit_id}"
        page.goto(course_home, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=20_000)

        # Also try navigating to the news page directly if no API calls captured
        if not captured_responses:
            news_url = f"{base_url}/d2l/lms/news/main.d2l?ou={course.org_unit_id}"
            page.goto(news_url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=20_000)

    finally:
        page.remove_listener("response", handle_response)

    # Parse captured API responses into Announcement objects
    for item in captured_responses:
        ann_id = str(item.get("Id", item.get("NewsId", "")))
        if not ann_id:
            continue

        body_html = item.get("Body", {})
        if isinstance(body_html, dict):
            body_html = body_html.get("Html", body_html.get("Text", ""))

        title = item.get("Title", "Untitled")
        created = item.get("CreatedDate", item.get("StartDate", ""))

        announcements.append(
            Announcement(
                announcement_id=f"{course.org_unit_id}_{ann_id}",
                course_id=course.org_unit_id,
                course_name=course.name,
                title=title,
                body_html=body_html,
                body_text=_strip_html(body_html),
                created_date=_parse_d2l_date(created),
                author=item.get("CreatedBy", ""),
                url=f"{base_url}/d2l/lms/news/main.d2l?ou={course.org_unit_id}",
            )
        )

    return announcements


def scrape_announcements_dom(
    page: Page,
    course: Course,
) -> list[Announcement]:
    """Fallback: scrape announcements from the rendered DOM.

    Navigates to the course's news/announcements page and parses
    the HTML directly. Less reliable than API interception.
    """
    announcements: list[Announcement] = []
    base_url = settings.icollege_url.rstrip("/")

    # Navigate to the news page
    news_url = f"{base_url}/d2l/lms/news/main.d2l?ou={course.org_unit_id}"
    page.goto(news_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20_000)

    # D2L announcement items are typically in elements with specific classes
    # These selectors target common D2L Brightspace news item patterns
    selectors = [
        ".d2l-datalist-item",           # Common D2L list item
        "[class*='news-item']",         # News-specific class
        ".d2l-htmlblock",               # Content block
        "d2l-card",                     # Web component card
    ]

    for selector in selectors:
        items = page.query_selector_all(selector)
        if items:
            for i, item in enumerate(items):
                # Try to extract title
                title_el = (
                    item.query_selector("h2, h3, h4, .d2l-heading, [class*='title']")
                )
                title = (title_el.inner_text() if title_el else "").strip()
                if not title:
                    title = f"Announcement #{i + 1}"

                # Try to extract body
                body_el = item.query_selector(
                    ".d2l-htmlblock, [class*='body'], [class*='content'], p"
                )
                body_html = (body_el.inner_html() if body_el else "").strip()
                body_text = (body_el.inner_text() if body_el else "").strip()

                if not body_text:
                    body_text = item.inner_text().strip()
                    body_html = item.inner_html().strip()

                # Try to extract date
                date_el = item.query_selector(
                    "[class*='date'], time, [class*='timestamp']"
                )
                date_text = ""
                if date_el:
                    date_text = (
                        date_el.get_attribute("datetime")
                        or date_el.inner_text().strip()
                    )

                # Generate a stable ID from course + title + position
                ann_id = f"{course.org_unit_id}_dom_{i}_{hash(title) & 0xFFFFFFFF:08x}"

                announcements.append(
                    Announcement(
                        announcement_id=ann_id,
                        course_id=course.org_unit_id,
                        course_name=course.name,
                        title=title,
                        body_html=body_html,
                        body_text=body_text,
                        created_date=date_text or datetime.now(timezone.utc).isoformat(),
                        url=news_url,
                    )
                )

            break  # Stop after first successful selector

    return announcements


def scrape_course_announcements(
    page: Page,
    course: Course,
) -> list[Announcement]:
    """Scrape announcements for a single course using the hybrid strategy.

    Tries API interception first, falls back to DOM scraping.
    """
    console.print(f"  [cyan]Scanning:[/cyan] {course.name}")

    # Primary: API interception
    announcements = scrape_announcements_api(page, course)

    if announcements:
        console.print(
            f"    [green]✓[/green] {len(announcements)} announcement(s) "
            f"[dim](via API)[/dim]"
        )
        return announcements

    # Fallback: DOM scraping
    console.print("    [dim]API interception missed, trying DOM scraping...[/dim]")
    announcements = scrape_announcements_dom(page, course)

    if announcements:
        console.print(
            f"    [green]✓[/green] {len(announcements)} announcement(s) "
            f"[dim](via DOM)[/dim]"
        )
    else:
        console.print("    [dim]No announcements found[/dim]")

    return announcements
