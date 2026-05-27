import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

BOOKING_CLASSES = re.compile(
    r"tee.?time|time.?slot|booking.?time|available|tee_time|book.?slot", re.I
)

DATE_PATTERNS = [
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
]

_DAY_NAMES = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

_MINIMAL_TEXT_THRESHOLD = 200  # chars; below this means JS-rendered


def scrape_course(url):
    """
    Fetch a golf course booking page and extract available tee time info.
    Automatically falls back to Playwright when the page is JS-rendered.
    Returns dict: success, content_hash, slots, error, used_playwright
    """
    html, error = _fetch_static(url)
    used_playwright = False

    if html and not error:
        if _is_js_rendered(html):
            logger.info("Static fetch got minimal content for %s — trying Playwright", url)
            pw_html, pw_error = _fetch_playwright(url)
            if pw_html:
                html, error = pw_html, pw_error
                used_playwright = True
            else:
                logger.warning("Playwright also failed for %s: %s", url, pw_error)

    if not html:
        return {"success": False, "content_hash": None, "slots": [], "error": error,
                "used_playwright": used_playwright}

    content_hash = hashlib.sha256(html.encode()).hexdigest()
    slots = _extract_slots(html)

    return {
        "success": True,
        "content_hash": content_hash,
        "slots": slots,
        "error": None,
        "used_playwright": used_playwright,
    }


def scrape_date_url(base_url, target_date):
    """
    Build a date-parameterized URL for target_date (if the URL has a date= param)
    and scrape it. Returns the scrape_course result dict, plus the resolved URL.
    """
    resolved_url = _inject_date(base_url, target_date)
    result = scrape_course(resolved_url)
    result["resolved_url"] = resolved_url
    result["target_date"] = target_date
    return result


def upcoming_desired_dates(desired_day_nums, weeks_ahead=3):
    """
    Return upcoming dates for each desired weekday, including today if it matches.
    Looks up to weeks_ahead weeks ahead. Sorted ascending.
    """
    today = date.today()
    dates = []
    for day_num in desired_day_nums:
        for week in range(weeks_ahead):
            days_ahead = (day_num - today.weekday()) % 7 + week * 7
            dates.append(today + timedelta(days=days_ahead))
    return sorted(set(dates))


def find_matching_slots(slots, start_time_str, end_time_str, desired_days=None):
    """
    Return slots whose time falls within [start_time_str, end_time_str].
    desired_days: list of full day names e.g. ["Friday", "Saturday"], or None for any day.

    Day matching uses dateutil to handle ISO datetimes (e.g. '2026-05-22T08:30:00')
    as well as plain day-name strings (e.g. 'Saturday 8:30 AM').
    """
    if not start_time_str or not end_time_str:
        return []

    try:
        window_start = datetime.strptime(start_time_str, "%H:%M").time()
        window_end = datetime.strptime(end_time_str, "%H:%M").time()
    except ValueError:
        return []

    desired_day_nums = None
    if desired_days:
        desired_day_nums = {_DAY_NAMES[d.lower()] for d in desired_days if d.lower() in _DAY_NAMES}

    matches = []
    for slot in slots:
        weekday, slot_time = _parse_slot(slot)

        if slot_time is None:
            continue
        if not (window_start <= slot_time <= window_end):
            continue
        if desired_day_nums is not None and weekday is not None:
            if weekday not in desired_day_nums:
                continue
        matches.append(slot)

    return matches


# ── internal helpers ──────────────────────────────────────────────────────────

def _fetch_static(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.text, None
    except requests.RequestException as e:
        return None, str(e)


def _fetch_playwright(url):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
            except PWTimeout:
                pass  # partial load is often good enough
            html = page.content()
            browser.close()
        return html, None
    except Exception as e:
        logger.error("Playwright error for %s: %s", url, e)
        return None, str(e)


def _is_js_rendered(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return len(soup.get_text(strip=True)) < _MINIMAL_TEXT_THRESHOLD


def _extract_slots(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    slots = set()

    for attr in ("data-date", "data-time", "data-datetime", "data-slot"):
        for el in soup.find_all(attrs={attr: True}):
            slots.add(el[attr])

    for el in soup.find_all("time"):
        val = el.get("datetime") or el.get_text(strip=True)
        if val:
            slots.add(val)

    for el in soup.find_all(class_=BOOKING_CLASSES):
        content = el.get_text(strip=True)
        if content and len(content) < 50:
            slots.add(content)

    text = soup.get_text(separator=" ", strip=True)
    for pattern in DATE_PATTERNS:
        slots.update(re.findall(pattern, text, re.IGNORECASE)[:20])

    # Time-only patterns (common in rendered booking grids)
    for m in re.finditer(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\b", text):
        slots.add(m.group(1).strip())

    return sorted(slots)[:100]


def _parse_slot(s):
    """
    Parse (weekday_int_or_None, time_or_None) from a slot string.
    Uses dateutil for ISO datetimes; falls back to regex for plain times.
    """
    # Try full datetime parse (handles ISO 8601, e.g. "2026-05-22T08:30:00")
    try:
        from dateutil import parser as dparser
        dt = dparser.parse(s, fuzzy=False)
        return dt.weekday(), dt.time().replace(second=0, microsecond=0)
    except Exception:
        pass

    # Regex time extraction
    return _parse_day_name(s), _parse_time_regex(s)


def _parse_time_regex(s):
    match = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM|am|pm)?", s)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    meridiem = (match.group(3) or "").upper()
    if meridiem == "PM" and hour != 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    try:
        return time(hour, minute)
    except ValueError:
        return None


def _parse_day_name(s):
    s_lower = s.lower()
    for name, num in _DAY_NAMES.items():
        if re.search(r"\b" + name + r"\b", s_lower):
            return num
    return None


def _inject_date(url, target_date):
    """Replace (or add) the date= query parameter in a URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["date"] = [target_date.strftime("%Y-%m-%d")]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


def has_date_param(url):
    """Return True if the URL contains a date= query parameter."""
    return "date" in parse_qs(urlparse(url).query)
