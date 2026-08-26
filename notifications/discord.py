"""Discord webhook notification sender.

Formats course summaries and action items into rich Discord embed
messages and sends them via webhook.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
from rich.console import Console

from config import settings
from intelligence.summarizer import CourseSummary, ActionItem

console = Console()

# Discord embed color constants
COLORS = {
    "HIGH": 0xED4245,     # Red
    "MEDIUM": 0xFEE75C,   # Yellow
    "LOW": 0x57F287,      # Green
    "INFO": 0x5865F2,     # Blurple
}


def _build_embeds(summaries: list[CourseSummary]) -> list[dict]:
    """Build Discord embed objects from course summaries."""
    embeds: list[dict] = []

    for summary in summaries:
        # Determine the highest priority for the embed color
        max_priority = "LOW"
        if any(a.priority == "HIGH" for a in summary.action_items):
            max_priority = "HIGH"
        elif any(a.priority == "MEDIUM" for a in summary.action_items):
            max_priority = "MEDIUM"

        # Build action items field text
        action_lines: list[str] = []
        for item in summary.action_items:
            deadline_str = (
                f"📅 {item.deadline}"
                if item.deadline != "No deadline specified"
                else "📅 No deadline"
            )
            action_lines.append(
                f"{item.priority_emoji} {item.category_emoji} **{item.task}**\n"
                f"  └ {deadline_str} • Priority: {item.priority}"
            )

        # Build the embed
        embed: dict = {
            "title": f"📚 {summary.course_name}",
            "description": summary.summary,
            "color": COLORS.get(max_priority, COLORS["INFO"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {
                "text": (
                    f"iCollege Scanner • "
                    f"{summary.announcement_count} announcement(s) processed"
                ),
            },
        }

        if action_lines:
            # Discord has a 1024 char limit per field value
            action_text = "\n\n".join(action_lines)
            # Split into multiple fields if necessary
            if len(action_text) <= 1024:
                embed["fields"] = [
                    {
                        "name": f"🎯 Action Items ({len(summary.action_items)})",
                        "value": action_text,
                        "inline": False,
                    }
                ]
            else:
                embed["fields"] = []
                for i, line in enumerate(action_lines):
                    embed["fields"].append(
                        {
                            "name": f"Action Item {i + 1}" if i > 0 else f"🎯 Action Items ({len(summary.action_items)})",
                            "value": line,
                            "inline": False,
                        }
                    )
        else:
            embed["fields"] = [
                {
                    "name": "✅ No Action Required",
                    "value": "No specific tasks or deadlines found.",
                    "inline": False,
                }
            ]

        embeds.append(embed)

    return embeds


def send_discord_notification(summaries: list[CourseSummary]) -> bool:
    """Send course summaries to Discord via webhook.

    Returns True if the notification was sent successfully.
    """
    webhook_url = settings.discord_webhook_url

    if not webhook_url:
        console.print(
            "[yellow]⚠ No Discord webhook URL configured. "
            "Skipping notification.[/yellow]"
        )
        return False

    embeds = _build_embeds(summaries)

    if not embeds:
        console.print("[dim]No embeds to send[/dim]")
        return False

    # Discord allows max 10 embeds per message
    # Send in batches if needed
    batch_size = 10
    success = True

    for i in range(0, len(embeds), batch_size):
        batch = embeds[i : i + batch_size]
        payload = {
            "username": "iCollege Scanner",
            "avatar_url": "https://www.gsu.edu/favicon.ico",
            "content": (
                "**📢 New iCollege Announcements**"
                if i == 0
                else None
            ),
            "embeds": batch,
        }

        # Remove None content
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            response = httpx.post(
                webhook_url,
                json=payload,
                timeout=15.0,
            )
            response.raise_for_status()
            console.print(
                f"[green]✓ Discord notification sent[/green] "
                f"[dim](batch {i // batch_size + 1})[/dim]"
            )
        except httpx.HTTPStatusError as exc:
            console.print(
                f"[red]✗ Discord webhook error: "
                f"HTTP {exc.response.status_code}[/red]"
            )
            success = False
        except httpx.RequestError as exc:
            console.print(f"[red]✗ Discord request failed: {exc}[/red]")
            success = False

    return success
