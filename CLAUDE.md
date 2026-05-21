# It's Tee Time — Claude Context

## What this project is
A local web application that monitors golf course booking websites to detect when tee times become available. It stores historical release patterns so the user can learn when each course drops new tee times (e.g., "Course X releases times every Monday at 7am").

## How to run
```bash
source venv/bin/activate
python app.py
# Open http://localhost:5000
```

## Architecture
Single-process Python Flask app with a SQLite database and APScheduler for background jobs.

```
app.py          — Flask app factory, all HTTP routes, entry point
models.py       — SQLAlchemy models; also owns the db = SQLAlchemy() instance
scraper.py      — Stateless scraping functions (requests + BeautifulSoup)
scheduler.py    — APScheduler background jobs; imports from models inside functions to avoid circular imports
templates/      — Jinja2 HTML templates using Bootstrap 5 (CDN)
```

**Key design decision:** `db` is defined in `models.py` (not `app.py`), so `scheduler.py` can import it without touching `app.py` at module level. This sidesteps circular import issues.

## Database models
- `GolfCourse` — a course the user is monitoring (name, URL, check interval)
- `TeeTimeSnapshot` — one scrape result per course per check (hash, slot list, success/error)
- `ReleaseEvent` — recorded when new slots appear that weren't in the previous snapshot

## Scraper approach (Phase 1)
`scraper.py` uses `requests` + `BeautifulSoup`. It looks for:
- `data-date`, `data-time`, `data-datetime` attributes (common in JS booking platforms)
- `<time>` HTML elements
- CSS class names matching patterns like `tee-time`, `time-slot`, `available`
- Date/time regex patterns in page text

Many golf course sites are JavaScript-rendered and will return minimal content this way. Phase 2 should add Playwright support for those cases.

## GitHub workflow
- `main` branch is the stable branch — all work goes here via clean commits
- GitHub Actions CI runs on every push: flake8 lint + smoke test of app imports
- Commit messages should be descriptive — used for rollback reference
- Repository: https://github.com/wambuentertainment/ItsTeeTime

## Development conventions
- No comments unless the WHY is non-obvious
- Max line length: 100 characters (flake8 configured for this)
- Python 3.9+ compatible (local machine runs 3.9.6)
- No frontend build step — Bootstrap and icons loaded from CDN

## Planned improvements (Phase 2+)
- Playwright integration for JavaScript-heavy booking sites
- Email/SMS notifications when tee times drop
- Smarter slot extraction with site-specific parsers (GolfNow, TeeSnap, EZLinks, ForeUP, Chronogolf)
- Tests directory with pytest
- Configurable notification thresholds
