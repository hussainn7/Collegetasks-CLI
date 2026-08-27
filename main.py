"""iCollege Announcement Scraper — CLI Entry Point.

Usage:
    python main.py login              Interactive SSO login
    python main.py courses            List enrolled courses
    python main.py scan               Full scan pipeline
    python main.py scan --courses "CSC 1302,MATH 2211"
    python main.py stats              Show database statistics
    python main.py clean              Clear the announcement database
    python main.py chatid             Get your Telegram chat ID from the bot
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


def cmd_login(args: argparse.Namespace) -> None:
    """Run the interactive SSO login flow."""
    from auth.login import interactive_login
    interactive_login()


def cmd_courses(args: argparse.Namespace) -> None:
    """List enrolled courses."""
    from auth.session import authenticated_context
    from scraper.courses import fetch_courses, display_courses

    with authenticated_context() as page:
        courses = fetch_courses(page)
        display_courses(courses)


def cmd_scan(args: argparse.Namespace) -> None:
    """Full scan pipeline: scrape → filter → summarize → notify."""
    from auth.session import authenticated_context
    from scraper.courses import fetch_courses, filter_courses
    from scraper.announcements import scrape_course_announcements
    from state.db import AnnouncementDB
    from intelligence.summarizer import summarize_announcements, CourseSummary
    from notifications.telegram import send_telegram_notification

    # Parse course filter from CLI args
    cli_filters: list[str] = []
    if args.courses:
        cli_filters = [c.strip() for c in args.courses.split(",") if c.strip()]

    db = AnnouncementDB()

    console.print(
        Panel(
            "[bold cyan]iCollege Announcement Scanner[/bold cyan]\n"
            f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
            border_style="cyan",
        )
    )

    # ── Step 1: Authenticate and fetch courses ────────────────────
    console.print("\n[bold]Step 1:[/bold] Authenticating & fetching courses...")

    with authenticated_context() as page:
        courses = fetch_courses(page)

        if not courses:
            console.print("[red]No courses found. Exiting.[/red]")
            return

        # Apply filters
        courses = filter_courses(courses, cli_filters if cli_filters else None)

        if not courses:
            console.print(
                "[red]No courses match the filter. Exiting.[/red]"
            )
            return

        # ── Step 2: Scrape announcements ──────────────────────────
        console.print(
            f"\n[bold]Step 2:[/bold] Scanning {len(courses)} course(s) "
            "for announcements..."
        )

        all_announcements = []
        for course in courses:
            anns = scrape_course_announcements(page, course)
            all_announcements.extend(anns)

    # ── Step 3: Filter for new announcements ──────────────────────
    console.print(
        f"\n[bold]Step 3:[/bold] Filtering {len(all_announcements)} "
        "announcement(s) for new content..."
    )
    new_announcements = db.filter_new(all_announcements)

    if not new_announcements:
        console.print(
            Panel(
                "[green]✓ No new announcements found.[/green]\n"
                "All caught up! 🎉",
                title="Result",
                border_style="green",
            )
        )
        return

    # ── Step 4: Summarize via LLM ─────────────────────────────────
    console.print(
        f"\n[bold]Step 4:[/bold] Summarizing {len(new_announcements)} "
        "new announcement(s) via LLM..."
    )
    summaries = summarize_announcements(new_announcements)

    # ── Step 5: Display results ───────────────────────────────────
    console.print(f"\n[bold]Step 5:[/bold] Results\n")
    _display_summaries(summaries)

    # ── Step 6: Send notifications ────────────────────────────────
    console.print(f"\n[bold]Step 6:[/bold] Sending Telegram notification...")
    sent = send_telegram_notification(summaries)

    # Mark all new announcements as notified
    if sent or not args.notify_only:
        db.mark_notified([a.announcement_id for a in new_announcements])

    console.print(
        Panel(
            f"[bold green]✓ Scan complete![/bold green]\n"
            f"  • {len(new_announcements)} new announcement(s) processed\n"
            f"  • {sum(len(s.action_items) for s in summaries)} action item(s) found\n"
            f"  • Telegram: {'sent ✓' if sent else 'skipped (not configured)'}",
            title="Summary",
            border_style="green",
        )
    )


def cmd_stats(args: argparse.Namespace) -> None:
    """Show database statistics."""
    from state.db import AnnouncementDB

    db = AnnouncementDB()
    stats = db.get_stats()

    table = Table(title="📊 Database Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")
    table.add_row("Total Seen", str(stats["total_seen"]))
    table.add_row("Notified", str(stats["notified"]))
    table.add_row("Pending", str(stats["pending"]))
    table.add_row("Courses Tracked", str(stats["courses_tracked"]))
    console.print(table)


def cmd_clean(args: argparse.Namespace) -> None:
    """Clear the announcement database."""
    from state.db import AnnouncementDB
    from config import settings
    import os

    db_path = settings.db_path

    if not db_path.exists():
        console.print("[yellow]Database doesn't exist yet — nothing to clean.[/yellow]")
        return

    # Get stats before cleaning
    db = AnnouncementDB()
    stats = db.get_stats()

    os.remove(str(db_path))
    console.print(
        Panel(
            f"[bold green]✓ Database cleaned![/bold green]\n"
            f"  Removed {stats['total_seen']} announcement record(s)\n"
            f"  from {stats['courses_tracked']} course(s)\n\n"
            f"  [dim]Next scan will treat all announcements as new.[/dim]",
            title="🧹 Clean",
            border_style="green",
        )
    )


def cmd_chatid(args: argparse.Namespace) -> None:
    """Fetch and display the Telegram chat ID from the bot's recent messages."""
    import httpx
    from config import settings

    token = settings.telegram_bot_token
    if not token:
        console.print("[red]✗ TELEGRAM_BOT_TOKEN not set in .env[/red]")
        return

    console.print("[dim]Fetching recent messages from bot...[/dim]")
    console.print(
        "[yellow]Make sure you've sent [bold]/start[/bold] to your bot "
        "on Telegram first![/yellow]\n"
    )

    try:
        resp = httpx.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("ok"):
            console.print(f"[red]✗ Telegram API error: {data}[/red]")
            return

        updates = data.get("result", [])
        if not updates:
            console.print(
                "[yellow]No messages found. Send [bold]/start[/bold] "
                "to your bot on Telegram, then re-run this command.[/yellow]"
            )
            return

        # Show all unique chat IDs found
        seen_chats: set[str] = set()
        table = Table(title="💬 Telegram Chats Found")
        table.add_column("Chat ID", style="bold green")
        table.add_column("Username", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Type", style="dim")

        for update in updates:
            msg = update.get("message", {})
            chat = msg.get("chat", {})
            chat_id = str(chat.get("id", ""))

            if not chat_id or chat_id in seen_chats:
                continue
            seen_chats.add(chat_id)

            username = chat.get("username", "—")
            first = chat.get("first_name", "")
            last = chat.get("last_name", "")
            name = f"{first} {last}".strip() or "—"
            chat_type = chat.get("type", "—")

            table.add_row(chat_id, f"@{username}" if username != "—" else "—", name, chat_type)

        console.print(table)
        console.print(
            "\n[bold]Copy your Chat ID and add it to .env:[/bold]\n"
            "  TELEGRAM_CHAT_ID=<your chat id>"
        )

    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/red]")


def _display_summaries(summaries: list) -> None:
    """Print formatted summaries to the terminal."""
    for summary in summaries:
        # Course header
        console.print(
            Panel(
                f"[bold]{summary.summary}[/bold]",
                title=f"📚 {summary.course_name}",
                subtitle=f"{summary.announcement_count} announcement(s)",
                border_style="cyan",
            )
        )

        if summary.action_items:
            table = Table(show_header=True, header_style="bold")
            table.add_column("", width=4)  # Priority emoji
            table.add_column("Task", style="white", max_width=50)
            table.add_column("Deadline", style="yellow")
            table.add_column("Priority", width=8)
            table.add_column("Category", style="dim")

            for item in summary.action_items:
                priority_style = {
                    "HIGH": "bold red",
                    "MEDIUM": "yellow",
                    "LOW": "green",
                }.get(item.priority, "white")

                table.add_row(
                    f"{item.priority_emoji}{item.category_emoji}",
                    item.task,
                    item.deadline,
                    Text(item.priority, style=priority_style),
                    item.category,
                )

            console.print(table)
        else:
            console.print("  [dim]No action items found[/dim]")

        console.print()


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate command."""
    parser = argparse.ArgumentParser(
        description="iCollege Announcement Scraper & Summarizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # login
    subparsers.add_parser("login", help="Interactive SSO login").set_defaults(func=cmd_login)

    # courses
    subparsers.add_parser("courses", help="List enrolled courses").set_defaults(func=cmd_courses)

    # scan
    scan_parser = subparsers.add_parser("scan", help="Scan for new announcements")
    scan_parser.add_argument(
        "--courses", type=str, default="",
        help='Comma-separated course filter (e.g., "CSC 1302,MATH 2211")',
    )
    scan_parser.add_argument(
        "--notify-only", action="store_true",
        help="Only mark announcements as notified if Telegram succeeds",
    )
    scan_parser.set_defaults(func=cmd_scan)

    # stats
    subparsers.add_parser("stats", help="Show database stats").set_defaults(func=cmd_stats)

    # clean
    subparsers.add_parser("clean", help="Clear the announcement database").set_defaults(func=cmd_clean)

    # chatid
    subparsers.add_parser("chatid", help="Get your Telegram chat ID").set_defaults(func=cmd_chatid)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
