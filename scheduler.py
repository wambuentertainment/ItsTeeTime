import logging
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def check_course(app, course_id):
    with app.app_context():
        from models import db, GolfCourse, TeeTimeSnapshot, ReleaseEvent, TeeTimeAlert
        from scraper import (
            scrape_course, scrape_date_url, find_matching_slots,
            upcoming_desired_dates, has_date_param, _DAY_NAMES, _inject_date,
        )

        course = db.session.get(GolfCourse, course_id)
        if not course or not course.active:
            return

        # ── Standard scrape for change detection ──────────────────────────────
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

        course.last_checked_at = datetime.utcnow()
        course.last_check_status = "ok" if result["success"] else "error"
        db.session.add(snapshot)

        # ── Alert check ───────────────────────────────────────────────────────
        if course.has_time_preference:
            _run_alert_check(
                course, course_id, db, TeeTimeAlert,
                scrape_date_url, find_matching_slots,
                upcoming_desired_dates, has_date_param, _DAY_NAMES, _inject_date,
            )

        db.session.commit()
        logger.info("Checked %s: %d slots", course.name, len(result["slots"]))


def _run_alert_check(course, course_id, db, TeeTimeAlert,
                     scrape_date_url, find_matching_slots,
                     upcoming_desired_dates, has_date_param, _DAY_NAMES, _inject_date):
    today_str = date.today().isoformat()

    # Auto-dismiss alerts whose date has passed, or legacy alerts with no date
    stale = TeeTimeAlert.query.filter_by(course_id=course_id, dismissed=False).filter(
        db.or_(
            TeeTimeAlert.matched_for_date.is_(None),
            TeeTimeAlert.matched_for_date < today_str,
        )
    ).all()
    for a in stale:
        a.dismissed = True
        a.dismissed_at = datetime.utcnow()
        logger.info("Auto-dismissed stale alert #%d for %s", a.id, course.name)

    # Skip if a current undismissed alert already exists
    if TeeTimeAlert.query.filter_by(course_id=course_id, dismissed=False).filter(
        TeeTimeAlert.matched_for_date >= today_str
    ).first():
        return

    desired_day_nums = set(range(7))
    if course.desired_days_list:
        desired_day_nums = {
            _DAY_NAMES[d.lower()] for d in course.desired_days_list
            if d.lower() in _DAY_NAMES
        }

    rich_slots = []

    if has_date_param(course.url) and course.desired_days_list:
        for target_date in upcoming_desired_dates(desired_day_nums, weeks_ahead=3):
            date_result = scrape_date_url(course.url, target_date)
            if not date_result["success"] or not date_result["slots"]:
                continue
            matched_times = find_matching_slots(
                date_result["slots"],
                course.desired_start_time,
                course.desired_end_time,
            )
            for t in matched_times:
                rich_slots.append({
                    "time": t,
                    "date": target_date.isoformat(),
                    "label": f"{target_date.strftime('%a')} {target_date.strftime('%b')} {target_date.day}",
                    "url": date_result["resolved_url"],
                })
            if rich_slots:
                break  # alert on the nearest matching day
    else:
        from scraper import scrape_course
        r = scrape_course(course.url)
        if r["success"]:
            matched_times = find_matching_slots(
                r["slots"], course.desired_start_time, course.desired_end_time,
                course.desired_days_list or None,
            )
            for t in matched_times:
                rich_slots.append({
                    "time": t, "date": today_str,
                    "label": "", "url": course.url,
                })

    if rich_slots:
        earliest_date = min(s["date"] for s in rich_slots)
        alert = TeeTimeAlert(course_id=course_id, matched_for_date=earliest_date)
        alert.matched_slots = rich_slots
        db.session.add(alert)
        logger.info("ALERT for %s: %s", course.name,
                    [(s["label"], s["time"]) for s in rich_slots])


def add_course_job(app, course):
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
