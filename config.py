"""iCollege Announcement Scraper — Configuration."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field


# Project root is the directory containing this file
PROJECT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    # ── iCollege ──────────────────────────────────────
    # The landing/info page (WordPress) — NOT the actual D2L instance
    icollege_url: str = Field(
        default="https://icollege.gsu.edu",
        description="iCollege landing page URL (used for reference only).",
    )

    # The actual D2L Brightspace LMS instance
    d2l_base_url: str = Field(
        default="https://gastate.view.usg.edu",
        description="Base URL for the D2L Brightspace LMS instance.",
    )

    # SAML SSO login entry point
    saml_login_url: str = Field(
        default=(
            "https://gastate.view.usg.edu/d2l/lp/auth/saml/initiate-login"
            "?entityId=https://idp.gsu.edu/idp/shibboleth"
        ),
        description="SAML SSO login URL for initiating authentication.",
    )

    # ── LLM ───────────────────────────────────────────
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API key for LLM summarization.",
    )

    # ── Notifications ─────────────────────────────────
    discord_webhook_url: str = Field(
        default="",
        description="Discord webhook URL for sending notifications.",
    )

    # ── Browser ───────────────────────────────────────
    headless: bool = Field(
        default=True,
        description="Run Playwright in headless mode during scans.",
    )

    # ── Storage ───────────────────────────────────────
    db_path: Path = Field(
        default=PROJECT_ROOT / "data" / "icollege.db",
        description="Path to the SQLite database file.",
    )
    session_path: Path = Field(
        default=PROJECT_ROOT / "data" / "session_state.json",
        description="Path to the Playwright session state JSON file.",
    )

    # ── Course Filter ─────────────────────────────────
    course_filter: str = Field(
        default="",
        description="Comma-separated course name substrings to scan. Empty = all.",
    )

    model_config = {
        "env_file": PROJECT_ROOT / ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    # ── Helpers ───────────────────────────────────────

    @property
    def course_filter_list(self) -> list[str]:
        """Parse the comma-separated course filter into a list of substrings."""
        if not self.course_filter.strip():
            return []
        return [c.strip() for c in self.course_filter.split(",") if c.strip()]

    def ensure_data_dir(self) -> None:
        """Create the data directory if it doesn't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_path.parent.mkdir(parents=True, exist_ok=True)


# Singleton instance
settings = Settings()
