"""Per-course announcement scraper.

Uses a multi-strategy approach:
  1. PRIMARY — Direct API call: hit /d2l/api/le/1.74/<orgId>/news/ and parse
     the JSON response directly. This is the most reliable method.
  2. SECONDARY — Network interception: capture D2L's internal widget calls
     during page load.
  3. FALLBACK — DOM scraping: parse announcement elements from the rendered
     news page HTML.
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
        .replace("&#160;", " ")
    )
    return text


def _parse_api_items(
    items: list[dict],
    course: Course,
    base_url: str,
) -> list[Announcement]:
    """Parse D2L API news items into Announcement objects."""
    announcements: list[Announcement] = []

    for item in items:
        ann_id = str(item.get("Id", item.get("NewsId", "")))
        if not ann_id:
            continue

        # Body can be a dict with Text/Html keys or a plain string
        body_obj = item.get("Body", {})
        if isinstance(body_obj, dict):
            body_html = body_obj.get("Html", body_obj.get("Text", ""))
            body_text = body_obj.get("Text", _strip_html(body_html))
        elif isinstance(body_obj, str):
            body_html = body_obj
            body_text = _strip_html(body_obj)
        else:
            body_html = ""
            body_text = ""

        title = item.get("Title", "Untitled")
        created = item.get("CreatedDate", item.get("StartDate", ""))

        # Build author name if available
        author = ""
        created_by = item.get("CreatedBy", "")
        if isinstance(created_by, str):
            author = created_by
        elif isinstance(created_by, dict):
            author = created_by.get("DisplayName", str(created_by.get("Id", "")))

        announcements.append(
            Announcement(
                announcement_id=f"{course.org_unit_id}_{ann_id}",
                course_id=course.org_unit_id,
                course_name=course.name,
                title=title,
                body_html=body_html,
                body_text=body_text if body_text else _strip_html(body_html),
                created_date=_parse_d2l_date(created),
                author=str(author),
                url=f"{base_url}/d2l/lms/news/main.d2l?ou={course.org_unit_id}",
            )
        )

    return announcements


def scrape_announcements_api_direct(
    page: Page,
    course: Course,
) -> list[Announcement]:
    """Scrape announcements via a direct call to the D2L REST API.

    Navigates to /d2l/api/le/<version>/<orgUnitId>/news/ and parses
    the JSON response. This is the most reliable method since we
    know the exact endpoint.
    """
    base_url = settings.d2l_base_url.rstrip("/")

    # Try multiple API versions (newest first)
    for version in ["1.74", "1.75", "1.67", "1.48"]:
        api_url = f"{base_url}/d2l/api/le/{version}/{course.org_unit_id}/news/"
        try:
            response = page.goto(api_url, wait_until="domcontentloaded", timeout=15_000)
            if response and response.ok:
                body_text = page.inner_text("body")
                data = json.loads(body_text)

                items: list[dict] = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict) and "Items" in data:
                    items = data["Items"]
                elif isinstance(data, dict):
                    items = [data]

                if items:
                    return _parse_api_items(items, course, base_url)
                else:
                    # API returned successfully but 0 items — course has no announcements
                    return []
        except json.JSONDecodeError:
            continue
        except Exception:
            continue

    return []


def scrape_announcements_network(
    page: Page,
    course: Course,
) -> list[Announcement]:
    """Scrape announcements via network interception during page load.

    Navigates to the course homepage and intercepts API/widget calls
    that contain news data.
    """
    base_url = settings.d2l_base_url.rstrip("/")
    captured_items: list[dict] = []

    def handle_response(response: Response) -> None:
        """Capture D2L news API/widget responses."""
        url = response.url.lower()
        if not response.ok:
            return
        # Match both the REST API and widget endpoints
        if ("/news" in url and (
            "/api/le/" in url or
            "/le/news/widget/" in url or
            "refreshnews" in url
        )):
            try:
                data = response.json()
                if isinstance(data, list):
                    captured_items.extend(data)
                elif isinstance(data, dict) and "Items" in data:
                    captured_items.extend(data["Items"])
            except Exception:
                pass

    page.on("response", handle_response)
    try:
        course_home = f"{base_url}/d2l/home/{course.org_unit_id}"
        page.goto(course_home, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=20_000)
    finally:
        page.remove_listener("response", handle_response)

    if captured_items:
        return _parse_api_items(captured_items, course, base_url)

    return []


def scrape_announcements_dom(
    page: Page,
    course: Course,
) -> list[Announcement]:
    """Fallback: scrape announcements from the rendered DOM.

    Navigates to the course's news/announcements page and parses
    the HTML directly. Less reliable than API methods.
    """
    announcements: list[Announcement] = []
    base_url = settings.d2l_base_url.rstrip("/")

    # Navigate to the news page
    news_url = f"{base_url}/d2l/lms/news/main.d2l?ou={course.org_unit_id}"
    page.goto(news_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20_000)

    # D2L news items are often in table rows or list items
    selectors = [
        ".d2l-datalist-item",
        "table.d_gd tr.d_ggl1, table.d_gd tr.d_ggl2",  # D2L grid rows
        "[class*='news-item']",
        "d2l-card",
    ]

    for selector in selectors:
        items = page.query_selector_all(selector)
        if items:
            for i, item in enumerate(items):
                title_el = item.query_selector(
                    "h2, h3, h4, .d2l-heading, [class*='title'], a strong, a"
                )
                title = (title_el.inner_text() if title_el else "").strip()
                if not title:
                    title = f"Announcement #{i + 1}"

                body_el = item.query_selector(
                    ".d2l-htmlblock, [class*='body'], [class*='content'], p"
                )
                body_html = (body_el.inner_html() if body_el else "").strip()
                body_text = (body_el.inner_text() if body_el else "").strip()

                if not body_text:
                    body_text = item.inner_text().strip()
                    body_html = item.inner_html().strip()

                date_el = item.query_selector(
                    "[class*='date'], time, [class*='timestamp']"
                )
                date_text = ""
                if date_el:
                    date_text = (
                        date_el.get_attribute("datetime")
                        or date_el.inner_text().strip()
                    )

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
    """Scrape announcements for a single course using multi-strategy approach.

    Strategy order:
    1. Direct REST API call (most reliable)
    2. Network interception during page load
    3. DOM scraping (least reliable)
    """
    console.print(f"  [cyan]Scanning:[/cyan] {course.name}")

    # Strategy 1: Direct API call
    announcements = scrape_announcements_api_direct(page, course)
    if announcements:
        console.print(
            f"    [green]✓[/green] {len(announcements)} announcement(s) "
            f"[dim](via direct API)[/dim]"
        )
        return announcements

    # If API returned 200 with 0 items, the course truly has no announcements
    # But we should try network interception as a safety net

    # Strategy 2: Network interception
    announcements = scrape_announcements_network(page, course)
    if announcements:
        console.print(
            f"    [green]✓[/green] {len(announcements)} announcement(s) "
            f"[dim](via network interception)[/dim]"
        )
        return announcements

    # Strategy 3: DOM scraping
    console.print("    [dim]API methods returned empty, trying DOM scraping...[/dim]")
    announcements = scrape_announcements_dom(page, course)
    if announcements:
        console.print(
            f"    [green]✓[/green] {len(announcements)} announcement(s) "
            f"[dim](via DOM scraping)[/dim]"
        )
    else:
        console.print("    [dim]No announcements found for this course[/dim]")

    return announcements
