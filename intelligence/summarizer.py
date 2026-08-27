"""LLM summarization pipeline using Google Gemini.

Takes new announcements, groups them by course, sends them through
the LLM for summarization and action extraction, and returns
structured results.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from rich.console import Console

from config import settings
from intelligence.prompts import SYSTEM_PROMPT, build_summarization_prompt
from scraper.announcements import Announcement

console = Console()


@dataclass
class ActionItem:
    """A single extracted action item from an announcement."""

    task: str
    deadline: str
    priority: str  # HIGH, MEDIUM, LOW
    category: str  # ASSIGNMENT, EXAM, READING, etc.

    @property
    def priority_emoji(self) -> str:
        return {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(
            self.priority, "⚪"
        )

    @property
    def category_emoji(self) -> str:
        return {
            "ASSIGNMENT": "📝",
            "EXAM": "📋",
            "READING": "📖",
            "MEETING": "🤝",
            "SCHEDULE_CHANGE": "📅",
            "LAB": "🔬",
            "PROJECT": "🏗️",
            "OTHER": "📌",
        }.get(self.category, "📌")


@dataclass
class CourseSummary:
    """Summarized results for a single course."""

    course_name: str
    summary: str
    action_items: list[ActionItem] = field(default_factory=list)
    announcement_count: int = 0
    error: str | None = None


def _group_by_course(
    announcements: list[Announcement],
) -> dict[str, list[Announcement]]:
    """Group announcements by course name."""
    groups: dict[str, list[Announcement]] = {}
    for ann in announcements:
        key = ann.course_name
        if key not in groups:
            groups[key] = []
        groups[key].append(ann)
    return groups


def _format_announcements_for_prompt(announcements: list[Announcement]) -> str:
    """Format a list of announcements into text for the LLM prompt."""
    parts: list[str] = []
    for i, ann in enumerate(announcements, 1):
        parts.append(
            f"**Announcement {i}: {ann.title}**\n"
            f"Date: {ann.created_date}\n"
            f"Author: {ann.author or 'Unknown'}\n\n"
            f"{ann.body_text}\n"
        )
    return "\n---\n".join(parts)


def _extract_json(text: str) -> dict | None:
    """Extract a JSON object from LLM response text.

    The LLM may wrap the JSON in markdown code fences or include
    preamble text — this function handles those cases.
    """
    # Try to find JSON in code fences
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to parse the entire response as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find a JSON object anywhere in the text
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def summarize_announcements(
    announcements: list[Announcement],
) -> list[CourseSummary]:
    """Summarize announcements through the Gemini LLM.

    Groups announcements by course, sends each group to the LLM,
    and returns structured CourseSummary objects.
    """
    if not announcements:
        return []

    if not settings.gemini_api_key:
        console.print(
            "[bold red]✗ GEMINI_API_KEY not set.[/bold red] "
            "Add it to your .env file."
        )
        return [
            CourseSummary(
                course_name="Error",
                summary="LLM API key not configured.",
                error="GEMINI_API_KEY missing",
            )
        ]

    # Import here to avoid import errors if the key isn't set
    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)
    model = "gemini-3.6-flash"

    groups = _group_by_course(announcements)
    summaries: list[CourseSummary] = []

    for course_name, course_anns in groups.items():
        console.print(f"  [cyan]Summarizing:[/cyan] {course_name}")

        announcements_text = _format_announcements_for_prompt(course_anns)
        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        prompt = build_summarization_prompt(
            course_name=course_name,
            announcements_text=announcements_text,
            announcement_count=len(course_anns),
            current_date=current_date,
        )

        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "temperature": 0.3,  # Lower temperature for factual extraction
                },
            )

            response_text = response.text or ""
            parsed = _extract_json(response_text)

            if parsed:
                action_items = [
                    ActionItem(
                        task=item.get("task", "Unknown task"),
                        deadline=item.get("deadline", "No deadline specified"),
                        priority=item.get("priority", "MEDIUM").upper(),
                        category=item.get("category", "OTHER").upper(),
                    )
                    for item in parsed.get("action_items", [])
                ]

                summaries.append(
                    CourseSummary(
                        course_name=course_name,
                        summary=parsed.get("summary", "No summary generated."),
                        action_items=action_items,
                        announcement_count=len(course_anns),
                    )
                )
                console.print(
                    f"    [green]✓[/green] {len(action_items)} action item(s)"
                )
            else:
                # Couldn't parse JSON — use raw text as summary
                summaries.append(
                    CourseSummary(
                        course_name=course_name,
                        summary=response_text[:500],
                        announcement_count=len(course_anns),
                        error="Failed to parse structured response",
                    )
                )
                console.print(
                    "    [yellow]⚠ Could not parse structured response[/yellow]"
                )

        except Exception as exc:
            console.print(f"    [red]✗ LLM error: {exc}[/red]")
            summaries.append(
                CourseSummary(
                    course_name=course_name,
                    summary=f"Error during summarization: {exc}",
                    announcement_count=len(course_anns),
                    error=str(exc),
                )
            )

    return summaries
