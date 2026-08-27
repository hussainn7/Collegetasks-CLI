"""SQLite state management for announcement deduplication.

Tracks which announcements have been seen and notified about,
ensuring the system only processes genuinely new content.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from rich.console import Console

from config import settings
from scraper.announcements import Announcement

console = Console()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_announcements (
    announcement_id TEXT PRIMARY KEY,
    course_id       TEXT NOT NULL,
    course_name     TEXT NOT NULL,
    title           TEXT NOT NULL,
    body_text       TEXT,
    body_html       TEXT,
    created_at      TEXT NOT NULL,
    first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
    notified        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_seen_course
    ON seen_announcements(course_id);

CREATE INDEX IF NOT EXISTS idx_seen_notified
    ON seen_announcements(notified);

CREATE INDEX IF NOT EXISTS idx_seen_created
    ON seen_announcements(created_at);
"""


class AnnouncementDB:
    """SQLite-backed announcement state tracker."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or settings.db_path
        settings.ensure_data_dir()
        self._init_db()

    def _init_db(self) -> None:
        """Create the database and tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    # ── Core Operations ───────────────────────────────────────────

    def is_new(self, announcement_id: str) -> bool:
        """Check if an announcement has NOT been seen before."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_announcements WHERE announcement_id = ?",
                (announcement_id,),
            ).fetchone()
            return row is None

    def mark_seen(self, announcement: Announcement) -> None:
        """Record an announcement as seen in the database."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO seen_announcements
                   (announcement_id, course_id, course_name, title,
                    body_text, body_html, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    announcement.announcement_id,
                    announcement.course_id,
                    announcement.course_name,
                    announcement.title,
                    announcement.body_text,
                    announcement.body_html,
                    announcement.created_date,
                ),
            )
            conn.commit()

    def mark_notified(self, announcement_ids: list[str]) -> None:
        """Mark announcements as having been sent via notification."""
        if not announcement_ids:
            return
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in announcement_ids)
            conn.execute(
                f"""UPDATE seen_announcements
                    SET notified = 1
                    WHERE announcement_id IN ({placeholders})""",
                announcement_ids,
            )
            conn.commit()

    def get_unnotified(self) -> list[dict]:
        """Fetch all announcements that haven't been notified yet."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM seen_announcements
                   WHERE notified = 0
                   ORDER BY created_at DESC"""
            ).fetchall()
            return [dict(row) for row in rows]

    # ── Filtering ─────────────────────────────────────────────────

    def filter_new(
        self, announcements: list[Announcement]
    ) -> list[Announcement]:
        """Filter a list of announcements to only those not yet seen.

        New announcements are automatically marked as seen in the DB.
        Returns only the genuinely new ones.
        """
        new_announcements: list[Announcement] = []

        for ann in announcements:
            if self.is_new(ann.announcement_id):
                self.mark_seen(ann)
                new_announcements.append(ann)

        if new_announcements:
            console.print(
                f"  [green]→ {len(new_announcements)} new[/green] "
                f"out of {len(announcements)} total"
            )
        elif len(announcements) == 0:
            console.print(
                "  [yellow]→ Scraper found 0 announcements on the page[/yellow]"
            )
        else:
            console.print(
                f"  [dim]→ All {len(announcements)} announcement(s) "
                f"already processed (no new ones)[/dim]"
            )

        return new_announcements

    # ── Stats ─────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return database statistics."""
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM seen_announcements"
            ).fetchone()[0]
            notified = conn.execute(
                "SELECT COUNT(*) FROM seen_announcements WHERE notified = 1"
            ).fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM seen_announcements WHERE notified = 0"
            ).fetchone()[0]
            courses = conn.execute(
                "SELECT COUNT(DISTINCT course_id) FROM seen_announcements"
            ).fetchone()[0]

            return {
                "total_seen": total,
                "notified": notified,
                "pending": pending,
                "courses_tracked": courses,
            }
