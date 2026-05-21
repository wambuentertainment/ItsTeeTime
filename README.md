# It's Tee Time

A local web app that monitors golf course booking pages and tracks when tee times become available — so you can learn each course's release pattern and book before spots fill up.

## Features

- Add multiple golf course booking URLs
- Automatic background checks on a configurable schedule
- Detects and records when new tee time slots appear
- Learns and displays each course's release pattern (e.g., "Usually Mondays around 07:00")
- Check history and release event log per course
- Manual "Check Now" trigger from the dashboard

## Setup

```bash
# Clone the repo
git clone https://github.com/wambuentertainment/ItsTeeTime.git
cd ItsTeeTime

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate       # macOS/Linux
# venv\Scripts\activate        # Windows

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Open [http://localhost:8080](http://localhost:8080) in your browser.

## Usage

1. Click **Add Course** and paste the URL of the tee time booking page for a golf course
2. Choose how often to check (30 min to 6 hours)
3. The app starts monitoring in the background — check the course detail page for results
4. Over time, the app detects when new slots appear and surfaces a release pattern

## How it works

Each check, the app fetches the booking page and extracts any date/time-like data it can find (HTML data attributes, `<time>` elements, booking UI class names, regex patterns). When new slots appear that weren't in the previous check, it logs a **Release Event** with a timestamp. Patterns are derived from the day-of-week and hour distribution of those events.

> **Note:** Many golf booking sites use JavaScript rendering. If a course shows 0 slots consistently, the site likely requires a browser-based scraper (Playwright support planned for Phase 2).

## Stack

- **Python 3.9+** with Flask, SQLAlchemy, APScheduler
- **SQLite** for local storage (no database server needed)
- **Requests + BeautifulSoup** for web scraping
- **Bootstrap 5** for the UI (loaded from CDN)

## Contributing

Pull requests welcome. Run `flake8 .` before pushing — CI enforces linting on every commit to `main`.
