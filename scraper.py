import hashlib
import logging
import re

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

    # Data attributes used by common booking platforms
    for attr in ("data-date", "data-time", "data-datetime", "data-slot"):
        for el in soup.find_all(attrs={attr: True}):
            slots.add(el[attr])

    # HTML5 time elements
    for el in soup.find_all("time"):
        val = el.get("datetime") or el.get_text(strip=True)
        if val:
            slots.add(val)

    # Class-based elements common in booking UIs
    for el in soup.find_all(class_=BOOKING_CLASSES):
        content = el.get_text(strip=True)
        if content and len(content) < 50:
            slots.add(content)

    # Regex scan for date patterns
    for pattern in DATE_PATTERNS:
        slots.update(re.findall(pattern, text, re.IGNORECASE)[:20])

    return sorted(slots)[:50]
