import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def check_course(app, course_id):
    """Check a single course for new tee time slots and record any releases."""
    with app.app_context():
        from models import db, GolfCourse, TeeTimeSnapshot, ReleaseEvent
        from scraper import scrape_course

        course = db.session.get(GolfCourse, course_id)
        if not course or not course.active:
            return

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
            new_slots = set(result["slots"]) - set(prev.available_slots)
            if new_slots:
                event = ReleaseEvent(course_id=course_id, new_slot_count=len(new_slots))
                event.new_slots = sorted(new_slots)
                db.session.add(event)
                logger.info("New tee times for %s: %d slots", course.name, len(new_slots))

        course.last_checked_at = datetime.utcnow()
        course.last_check_status = "ok" if result["success"] else "error"

        db.session.add(snapshot)
        db.session.commit()
        logger.info("Checked %s: %d slots found", course.name, len(result["slots"]))


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
    """Remove a course's scheduled job if it exists."""
    job_id = f"course_{course_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def start_scheduler(app):
    """Start the background scheduler and enqueue all active courses."""
    with app.app_context():
        from models import GolfCourse

        for course in GolfCourse.query.filter_by(active=True).all():
            add_course_job(app, course)

    scheduler.start()
    logger.info("Scheduler started")
