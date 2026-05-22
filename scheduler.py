import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def check_course(app, course_id):
    """
    Check a course for new tee time slots and for slots matching the desired
    time window. When a match is found, creates a TeeTimeAlert.

    Strategy:
    - If the URL has a date= param and desired days are set, scrape each upcoming
      desired day's URL directly (much more reliable than scraping today's page).
    - Otherwise, scrape the stored URL and compare snapshots for new slots.
    """
    with app.app_context():
        from models import db, GolfCourse, TeeTimeSnapshot, ReleaseEvent, TeeTimeAlert
        from scraper import (
            scrape_course, scrape_date_url, find_matching_slots,
            upcoming_desired_dates, has_date_param, _DAY_NAMES,
        )

        course = db.session.get(GolfCourse, course_id)
        if not course or not course.active:
            return

        # ── 1. Standard scrape of the stored URL (for change detection) ──
        result = scrape_course(course.url)

        prev = (
            TeeTimeSnapshot.query.filter_by(course_id=course_id)
            .order_by(TeeTimeSnapshot.checked_at.desc())
            .first()
        )

        snapshot = TeeTimeSnapshot(
            course_id=course_id,
            content_hash=result["content_hash"],
            slot_count=len(result["slots"]),
            scrape_success=result["success"],
            error_message=result["error"],
        )
        snapshot.available_slots = result["slots"]

        if prev and prev.scrape_success and result["success"]:
            new_slots = sorted(set(result["slots"]) - set(prev.available_slots))
            if new_slots:
                event = ReleaseEvent(course_id=course_id, new_slot_count=len(new_slots))
                event.new_slots = new_slots
                db.session.add(event)
                logger.info("New content detected for %s", course.name)

        course.last_checked_at = datetime.utcnow()
        course.last_check_status = "ok" if result["success"] else "error"
        db.session.add(snapshot)

        # ── 2. Desired-time-window alert check ──
        if course.has_time_preference:
            _check_for_alerts(app, course, course_id, db, TeeTimeAlert,
                              scrape_date_url, find_matching_slots,
                              upcoming_desired_dates, has_date_param, _DAY_NAMES)

        db.session.commit()
        logger.info("Checked %s: %d slots", course.name, len(result["slots"]))


def _check_for_alerts(app, course, course_id, db, TeeTimeAlert,
                      scrape_date_url, find_matching_slots,
                      upcoming_desired_dates, has_date_param, _DAY_NAMES):
    """Determine if any upcoming desired slots are available and create an alert."""
    # Skip if an undismissed alert already exists — user hasn't acted yet
    if TeeTimeAlert.query.filter_by(course_id=course_id, dismissed=False).first():
        return

    desired_day_nums = set(range(7))  # default: any day
    if course.desired_days_list:
        desired_day_nums = {
            _DAY_NAMES[d.lower()] for d in course.desired_days_list
            if d.lower() in _DAY_NAMES
        }

    all_matched = []

    if has_date_param(course.url) and course.desired_days_list:
        # URL has a date param — scrape each upcoming desired day directly
        for target_date in upcoming_desired_dates(desired_day_nums, weeks_ahead=3):
            date_result = scrape_date_url(course.url, target_date)
            if not date_result["success"] or not date_result["slots"]:
                logger.debug("No slots for %s on %s", course.name, target_date)
                continue
            matched = find_matching_slots(
                date_result["slots"],
                course.desired_start_time,
                course.desired_end_time,
                # Day already guaranteed by the URL — no further day filter needed
            )
            for slot in matched:
                all_matched.append(f"{target_date.strftime('%a %b %d')} {slot}")

            if all_matched:
                break  # one hit is enough for one alert
    else:
        # No date param — check current slots against window
        from scraper import scrape_course
        result = scrape_course(course.url)
        if result["success"]:
            all_matched = find_matching_slots(
                result["slots"],
                course.desired_start_time,
                course.desired_end_time,
                course.desired_days_list or None,
            )

    if all_matched:
        alert = TeeTimeAlert(course_id=course_id)
        alert.matched_slots = all_matched
        db.session.add(alert)
        logger.info("ALERT created for %s: %s", course.name, all_matched)


def add_course_job(app, course):
    """Schedule (or reschedule) periodic checks for a course."""
    job_id = f"course_{course.id}"
    scheduler.add_job(
        check_course,
        trigger=IntervalTrigger(minutes=course.check_interval_minutes),
        id=job_id,
        args=[app, course.id],
        replace_existing=True,
    )
    logger.info("Scheduled %s every %d min", course.name, course.check_interval_minutes)


def remove_course_job(course_id):
    job_id = f"course_{course_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def start_scheduler(app):
    with app.app_context():
        from models import GolfCourse
        for course in GolfCourse.query.filter_by(active=True).all():
            add_course_job(app, course)
    scheduler.start()
    logger.info("Scheduler started")
