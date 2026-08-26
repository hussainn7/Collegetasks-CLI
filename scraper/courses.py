"""Dashboard parser — extracts enrolled courses from D2L Brightspace.

Parses the D2L Brightspace "My Courses" widget at gastate.view.usg.edu
to extract course names, org unit IDs, and URLs. Supports filtering by
semester and user-specified course name substrings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from playwright.sync_api import Page, Response
from rich.console import Console
from rich.table import Table

from config import settings

console = Console()


@dataclass
class Course:
    """Represents an enrolled course on iCollege."""

    name: str
    org_unit_id: str
    url: str
    semester: str = ""
    code: str = ""

    def matches_filter(self, filters: list[str]) -> bool:
        """Check if this course matches any of the given filter substrings."""
        if not filters:
            return True  # No filter = match all
        name_lower = self.name.lower()
        code_lower = self.code.lower()
        return any(
            f.lower() in name_lower or f.lower() in code_lower
            for f in filters
        )


def _extract_org_unit_id(url: str) -> str | None:
    """Extract the D2L org unit ID from a course URL.

    D2L course URLs follow the pattern:
        /d2l/home/12345
        /d2l/le/content/12345/...
    """
    match = re.search(r"/d2l/(?:home|le/content)/(\d+)", url)
    return match.group(1) if match else None


def _parse_course_name(raw_name: str) -> tuple[str, str, str]:
    """Parse a D2L course name into (full_name, code, semester).

    D2L course names often follow patterns like:
        "CSC 1302 - Principles of Computer Science II (Fall 2026)"
        "90498 - PRINCIPLES COMPUTER SCI LAB II - Fall 2026"
    """
    # Try to extract semester
    semester = ""
    semester_match = re.search(
        r"((?:Spring|Summer|Fall|Winter)\s+\d{4})", raw_name, re.IGNORECASE
    )
    if semester_match:
        semester = semester_match.group(1)

    # Try to extract course code (e.g., "CSC 1302" or "MATH 2211")
    code = ""
    code_match = re.search(r"([A-Z]{2,4}\s*\d{4}[A-Z]?)", raw_name.upper())
    if code_match:
        code = code_match.group(1).strip()

    return raw_name.strip(), code, semester


def fetch_courses(page: Page) -> list[Course]:
    """Navigate to the D2L dashboard and extract all enrolled courses.

    Uses multiple strategies to find courses:
    1. Network interception of D2L enrollment API calls
    2. D2L "My Courses" widget course card links
    3. Fallback: any link matching /d2l/home/<id>
    """
    courses: list[Course] = []
    seen_ids: set[str] = set()
    captured_enrollments: list[dict] = []

    base_url = settings.d2l_base_url.rstrip("/")

    # ── Strategy 0: Intercept enrollment API calls ────────────────
    def handle_response(response: Response) -> None:
        """Capture D2L enrollment API responses."""
        url = response.url
        if "/enrollments/" in url and response.ok:
            try:
                data = response.json()
                if isinstance(data, dict) and "Items" in data:
                    captured_enrollments.extend(data["Items"])
                elif isinstance(data, list):
                    captured_enrollments.extend(data)
            except Exception:
                pass

    page.on("response", handle_response)

    try:
        # Navigate to the D2L homepage
        page.goto(f"{base_url}/d2l/home", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=20_000)
    finally:
        page.remove_listener("response", handle_response)

    # Parse captured enrollment API data
    if captured_enrollments:
        console.print(
            f"[dim]Captured {len(captured_enrollments)} enrollment(s) via API[/dim]"
        )
        for item in captured_enrollments:
            org_info = item.get("OrgUnit", {})
            org_id = str(org_info.get("Id", ""))
            if not org_id or org_id in seen_ids:
                continue

            raw_name = org_info.get("Name", f"Course {org_id}")
            org_type = org_info.get("Type", {}).get("Name", "")

            # Filter to only course offerings (not groups, departments, etc.)
            if org_type and org_type.lower() not in [
                "course offering", "course", ""
            ]:
                continue

            name, code, semester = _parse_course_name(raw_name)
            course_url = f"{base_url}/d2l/home/{org_id}"

            courses.append(
                Course(
                    name=name,
                    org_unit_id=org_id,
                    url=course_url,
                    semester=semester,
                    code=code,
                )
            )
            seen_ids.add(org_id)

    # ── Strategy 1: D2L course card links ─────────────────────────
    if not courses:
        course_links = page.query_selector_all('a[href*="/d2l/home/"]')

        for link in course_links:
            href = link.get_attribute("href") or ""
            org_id = _extract_org_unit_id(href)
            if not org_id or org_id in seen_ids:
                continue

            # Get the link text as the course name
            raw_name = (link.inner_text() or "").strip()
            if not raw_name or len(raw_name) < 3:
                # Try parent element for the name
                parent = link.query_selector("xpath=..")
                if parent:
                    raw_name = (parent.inner_text() or "").strip()

            if not raw_name or len(raw_name) < 3:
                raw_name = f"Course {org_id}"

            name, code, semester = _parse_course_name(raw_name)

            # Build the full URL
            full_url = href if href.startswith("http") else f"{base_url}{href}"

            courses.append(
                Course(
                    name=name,
                    org_unit_id=org_id,
                    url=full_url,
                    semester=semester,
                    code=code,
                )
            )
            seen_ids.add(org_id)

    # ── Strategy 2: Fallback — broader link search ────────────────
    if not courses:
        console.print(
            "[yellow]⚠ No courses found via API or course cards, "
            "trying broader link search...[/yellow]"
        )
        all_links = page.query_selector_all("a")
        for link in all_links:
            href = link.get_attribute("href") or ""
            org_id = _extract_org_unit_id(href)
            if not org_id or org_id in seen_ids:
                continue

            raw_name = (link.inner_text() or "").strip()
            if not raw_name or len(raw_name) < 3:
                continue

            name, code, semester = _parse_course_name(raw_name)
            full_url = href if href.startswith("http") else f"{base_url}{href}"

            courses.append(
                Course(
                    name=name,
                    org_unit_id=org_id,
                    url=full_url,
                    semester=semester,
                    code=code,
                )
            )
            seen_ids.add(org_id)

    # ── Strategy 3: Direct API call ───────────────────────────────
    if not courses:
        console.print(
            "[yellow]⚠ Trying direct enrollment API call...[/yellow]"
        )
        # Try multiple API versions
        for version in ["1.47", "1.43", "1.28"]:
            api_url = (
                f"{base_url}/d2l/api/lp/{version}/enrollments/myenrollments/"
                "?sortBy=OrgUnitName&isActive=true"
            )
            try:
                response = page.goto(api_url, wait_until="domcontentloaded")
                if response and response.ok:
                    body_text = page.inner_text("body")
                    data = json.loads(body_text)
                    items = data.get("Items", data if isinstance(data, list) else [])
                    for item in items:
                        org_info = item.get("OrgUnit", item)
                        org_id = str(org_info.get("Id", ""))
                        if not org_id or org_id in seen_ids:
                            continue
                        raw_name = org_info.get("Name", f"Course {org_id}")
                        name, code, semester = _parse_course_name(raw_name)
                        courses.append(
                            Course(
                                name=name,
                                org_unit_id=org_id,
                                url=f"{base_url}/d2l/home/{org_id}",
                                semester=semester,
                                code=code,
                            )
                        )
                        seen_ids.add(org_id)
                    if courses:
                        console.print(
                            f"[dim]Found {len(courses)} course(s) via "
                            f"API v{version}[/dim]"
                        )
                        break
            except Exception:
                continue

    console.print(f"[dim]Found {len(courses)} enrolled course(s)[/dim]")
    return courses


def filter_courses(
    courses: list[Course],
    filters: list[str] | None = None,
) -> list[Course]:
    """Filter courses by user-specified name/code substrings.

    If filters is None or empty, returns all courses.
    """
    active_filters = filters if filters else settings.course_filter_list
    if not active_filters:
        return courses

    filtered = [c for c in courses if c.matches_filter(active_filters)]
    console.print(
        f"[dim]Filtered to {len(filtered)} course(s) matching: "
        f"{', '.join(active_filters)}[/dim]"
    )
    return filtered


def display_courses(courses: list[Course]) -> None:
    """Print a rich table of courses to the console."""
    table = Table(title="📚 Enrolled Courses", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Course", style="cyan bold")
    table.add_column("Code", style="green")
    table.add_column("Semester", style="yellow")
    table.add_column("Org ID", style="dim")

    for i, course in enumerate(courses, 1):
        table.add_row(
            str(i),
            course.name[:60],
            course.code or "—",
            course.semester or "—",
            course.org_unit_id,
        )

    console.print(table)
