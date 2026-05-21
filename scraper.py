import hashlib
import logging
import re
from datetime import datetime, time

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

DATE_PATTERNS = [
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
]

BOOKING_CLASSES = re.compile(
    r"tee.?time|time.?slot|booking.?time|available|tee_time|book.?slot", re.I
)

_DAY_NAMES = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def scrape_course(url):
    """
    Fetch a golf course booking page and extract available tee time info.
    Returns dict: success, content_hash, slots, error
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        html = response.text
        content_hash = hashlib.sha256(html.encode()).hexdigest()

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        slots = _extract_slots(text, soup)

        return {"success": True, "content_hash": content_hash, "slots": slots, "error": None}

    except requests.RequestException as e:
        logger.error("Failed to scrape %s: %s", url, e)
        return {"success": False, "content_hash": None, "slots": [], "error": str(e)}


def _extract_slots(text, soup):
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

    for pattern in DATE_PATTERNS:
        slots.update(re.findall(pattern, text, re.IGNORECASE)[:20])

    return sorted(slots)[:50]


def _parse_time(s):
    """Extract a time object from a string, or return None."""
    match = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM|am|pm)?", s)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    meridiem = match.group(4)
    if meridiem:
        meridiem = meridiem.upper()
        if meridiem == "PM" and hour != 12:
            hour += 12
        elif meridiem == "AM" and hour == 12:
            hour = 0
    try:
        return time(hour, minute)
    except ValueError:
        return None


def _parse_day(s):
    """Extract a weekday integer (0=Mon) from a string, or return None."""
    s_lower = s.lower()
    for name, num in _DAY_NAMES.items():
        if re.search(r"\b" + name + r"\b", s_lower):
            return num
    return None


def find_matching_slots(slots, start_time_str, end_time_str, desired_days=None):
    """
    Return slots whose time falls within [start_time_str, end_time_str] and,
    if desired_days is provided, whose day matches.

    start_time_str / end_time_str: "HH:MM" 24-hour strings
    desired_days: list of full day names e.g. ["Saturday", "Sunday"], or None for any day
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
        slot_time = _parse_time(slot)
        if slot_time is None:
            continue
        if not (window_start <= slot_time <= window_end):
            continue
        if desired_day_nums is not None:
            slot_day = _parse_day(slot)
            # If the slot string has no day info, let it pass (day filtering is best-effort)
            if slot_day is not None and slot_day not in desired_day_nums:
                continue
        matches.append(slot)

    return matches
