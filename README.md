# iCollege Announcement Scraper

Automated tool to scrape GSU iCollege (D2L Brightspace) course announcements, detect new items, summarize them via LLM, and deliver actionable notifications.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp .env.example .env
# Edit .env with your settings

# 3. Login (interactive — opens a browser window)
python main.py login

# 4. List your courses
python main.py courses

# 5. Scan for new announcements
python main.py scan

# 6. Scan specific courses only
python main.py scan --courses "CSC 1302,MATH 2211"
```

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `ICOLLEGE_URL` | Yes | Your iCollege URL (default: `https://icollege.gsu.edu`) |
| `GEMINI_API_KEY` | Yes | Google Gemini API key |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook for notifications |
| `HEADLESS` | No | Run browser headless during scan (default: `true`) |
| `DB_PATH` | No | Path to SQLite database (default: `data/icollege.db`) |
| `SESSION_PATH` | No | Path to session state file (default: `data/session_state.json`) |

## Architecture

```
auth/          → SSO login + session persistence
scraper/       → Course parsing + announcement extraction
state/         → SQLite-based deduplication
intelligence/  → LLM summarization + action extraction
notifications/ → Discord webhook delivery
```
