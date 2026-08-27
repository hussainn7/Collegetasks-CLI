"""Telegram bot notification sender.

Formats course summaries and action items into rich Telegram messages
and sends them via the Bot API.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from rich.console import Console

from config import settings
from intelligence.summarizer import CourseSummary

console = Console()

_TELEGRAM_API = "https://api.telegram.org"

# Priority indicators
_PRIORITY = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
_CATEGORY = {
    "ASSIGNMENT": "📝", "EXAM": "📋", "READING": "📖",
    "MEETING": "🤝", "SCHEDULE_CHANGE": "📅", "LAB": "🔬",
    "PROJECT": "🏗️", "OTHER": "📌",
}


def _build_message(summaries: list[CourseSummary]) -> str:
    """Build a single Telegram message from course summaries.

    Uses Telegram's MarkdownV2 format for rich text.
    """
    lines: list[str] = []
    lines.append("📢 *New iCollege Announcements*")
    lines.append(f"_{datetime.now().strftime('%B %d, %Y at %I:%M %p')}_")
    lines.append("")

    for summary in summaries:
        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📚 *{_escape_md(summary.course_name[:60])}*")
        lines.append(f"_{_escape_md(summary.summary)}_")
        lines.append("")

        if summary.action_items:
            lines.append(f"🎯 *Action Items \\({len(summary.action_items)}\\):*")
            for item in summary.action_items:
                p_emoji = _PRIORITY.get(item.priority, "⚪")
                c_emoji = _CATEGORY.get(item.category, "📌")

                deadline_text = item.deadline
                if deadline_text == "No deadline specified":
                    deadline_text = "No deadline"

                lines.append(
                    f"  {p_emoji}{c_emoji} {_escape_md(item.task)}"
                )
                lines.append(
                    f"       📅 {_escape_md(deadline_text)} \\| "
                    f"Priority: *{_escape_md(item.priority)}*"
                )
            lines.append("")
        else:
            lines.append("✅ No action items found")
            lines.append("")

    return "\n".join(lines)


def _build_message_html(summaries: list[CourseSummary]) -> str:
    """Build a Telegram message using HTML format (more reliable than MD)."""
    lines: list[str] = []
    lines.append("📢 <b>New iCollege Announcements</b>")
    lines.append(f"<i>{datetime.now().strftime('%B %d, %Y at %I:%M %p')}</i>")
    lines.append("")

    for summary in summaries:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        course_label = summary.course_name[:60]
        lines.append(f"📚 <b>{_escape_html(course_label)}</b>")
        lines.append(f"<i>{_escape_html(summary.summary)}</i>")
        lines.append("")

        if summary.action_items:
            lines.append(
                f"🎯 <b>Action Items ({len(summary.action_items)}):</b>"
            )
            for item in summary.action_items:
                p_emoji = _PRIORITY.get(item.priority, "⚪")
                c_emoji = _CATEGORY.get(item.category, "📌")

                deadline_text = item.deadline
                if deadline_text == "No deadline specified":
                    deadline_text = "No deadline"

                lines.append(
                    f"  {p_emoji}{c_emoji} {_escape_html(item.task)}"
                )
                lines.append(
                    f"       📅 {_escape_html(deadline_text)} | "
                    f"Priority: <b>{_escape_html(item.priority)}</b>"
                )
            lines.append("")
        else:
            lines.append("✅ No action items found")
            lines.append("")

    return "\n".join(lines)


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    result = []
    for ch in text:
        if ch in special:
            result.append(f"\\{ch}")
        else:
            result.append(ch)
    return "".join(result)


def _escape_html(text: str) -> str:
    """Escape special characters for Telegram HTML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _get_chat_id(bot_token: str, username: str) -> str | None:
    """Resolve a Telegram username to a chat ID via getUpdates.

    If the username looks like a numeric chat ID already, return it as-is.
    """
    # If it's already a numeric ID (possibly negative for groups)
    stripped = username.lstrip("-")
    if stripped.isdigit():
        return username

    # Try getUpdates to find the chat ID from recent messages
    url = f"{_TELEGRAM_API}/bot{bot_token}/getUpdates"
    try:
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        target = username.lstrip("@").lower()
        for update in data.get("result", []):
            msg = update.get("message", {})
            chat = msg.get("chat", {})
            chat_username = (chat.get("username") or "").lower()
            if chat_username == target:
                return str(chat.get("id"))

            # Also check sender
            sender = msg.get("from", {})
            sender_username = (sender.get("username") or "").lower()
            if sender_username == target:
                return str(chat.get("id"))
    except Exception as exc:
        console.print(f"[yellow]⚠ Could not resolve username: {exc}[/yellow]")

    return None


def send_telegram_notification(summaries: list[CourseSummary]) -> bool:
    """Send course summaries to Telegram via Bot API.

    Returns True if the notification was sent successfully.
    """
    bot_token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id

    if not bot_token:
        console.print(
            "[yellow]⚠ No Telegram bot token configured. "
            "Skipping notification.[/yellow]"
        )
        return False

    if not chat_id:
        console.print(
            "[yellow]⚠ No Telegram chat ID configured. "
            "Skipping notification.[/yellow]"
        )
        return False

    # Resolve username to chat ID if needed
    resolved_id = _get_chat_id(bot_token, chat_id)
    if not resolved_id:
        console.print(
            f"[yellow]⚠ Could not resolve '{chat_id}' to a chat ID. "
            f"Make sure you've sent /start to the bot first, "
            f"or use a numeric chat ID.[/yellow]"
        )
        return False

    # Build the message (HTML is more reliable than MarkdownV2)
    message = _build_message_html(summaries)

    # Telegram has a 4096 char limit per message — split if needed
    chunks = _split_message(message, max_len=4000)
    success = True

    url = f"{_TELEGRAM_API}/bot{bot_token}/sendMessage"

    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": resolved_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            resp = httpx.post(url, json=payload, timeout=15.0)
            resp.raise_for_status()
            result = resp.json()

            if result.get("ok"):
                console.print(
                    f"[green]✓ Telegram notification sent[/green] "
                    f"[dim](part {i + 1}/{len(chunks)})[/dim]"
                )
            else:
                desc = result.get("description", "Unknown error")
                console.print(f"[red]✗ Telegram error: {desc}[/red]")
                success = False

        except httpx.HTTPStatusError as exc:
            console.print(
                f"[red]✗ Telegram HTTP error: {exc.response.status_code}[/red]"
            )
            try:
                err = exc.response.json()
                console.print(f"  [dim]{err.get('description', '')}[/dim]")
            except Exception:
                pass
            success = False
        except httpx.RequestError as exc:
            console.print(f"[red]✗ Telegram request failed: {exc}[/red]")
            success = False

    return success


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a message into chunks that fit Telegram's 4096 char limit."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Find a good split point (newline near the limit)
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks
