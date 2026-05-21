import logging
import os
from datetime import datetime

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import text

from models import db, DAYS_OF_WEEK, GolfCourse, TeeTimeSnapshot, ReleaseEvent, TeeTimeAlert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///itsteettime.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


def _run_migrations():
    """Add any new columns to existing tables without dropping data."""
    with db.engine.connect() as conn:
        existing = {r[1] for r in conn.execute(text("PRAGMA table_info(golf_courses)")).fetchall()}
        new_columns = {
            "desired_start_time": "VARCHAR(10)",
            "desired_end_time": "VARCHAR(10)",
            "desired_days": "VARCHAR(100) DEFAULT ''",
        }
        for col, col_type in new_columns.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE golf_courses ADD COLUMN {col} {col_type}"))
        conn.commit()


def _parse_time_prefs(form):
    """Extract and validate desired time window fields from a form submission."""
    start = form.get("desired_start_time", "").strip()
    end = form.get("desired_end_time", "").strip()
    days = form.getlist("desired_days")  # list of checked day names
    desired_days = ",".join(d for d in days if d in DAYS_OF_WEEK)
    return start or None, end or None, desired_days


@app.route("/")
def index():
    courses = GolfCourse.query.order_by(GolfCourse.created_at.desc()).all()
    active_alerts = (
        TeeTimeAlert.query.filter_by(dismissed=False)
        .order_by(TeeTimeAlert.detected_at.desc())
        .all()
    )
    return render_template("index.html", courses=courses, active_alerts=active_alerts)


@app.route("/courses/add", methods=["GET", "POST"])
def add_course():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        url = request.form.get("url", "").strip()
        interval = int(request.form.get("interval", 60))
        start_time, end_time, desired_days = _parse_time_prefs(request.form)

        if not name or not url:
            flash("Name and URL are required.", "error")
            return render_template("add_course.html", days=DAYS_OF_WEEK)

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        course = GolfCourse(
            name=name,
            url=url,
            check_interval_minutes=interval,
            desired_start_time=start_time,
            desired_end_time=end_time,
            desired_days=desired_days,
        )
        db.session.add(course)
        db.session.commit()

        from scheduler import add_course_job
        add_course_job(app, course)

        flash(f"Added {name}. First check will run at the next interval.", "success")
        return redirect(url_for("course_detail", course_id=course.id))

    return render_template("add_course.html", days=DAYS_OF_WEEK)


@app.route("/courses/<int:course_id>")
def course_detail(course_id):
    course = db.get_or_404(GolfCourse, course_id)
    snapshots = (
        TeeTimeSnapshot.query.filter_by(course_id=course_id)
        .order_by(TeeTimeSnapshot.checked_at.desc())
        .limit(50)
        .all()
    )
    events = (
        ReleaseEvent.query.filter_by(course_id=course_id)
        .order_by(ReleaseEvent.detected_at.desc())
        .limit(20)
        .all()
    )
    alerts = (
        TeeTimeAlert.query.filter_by(course_id=course_id)
        .order_by(TeeTimeAlert.detected_at.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "course.html", course=course, snapshots=snapshots, events=events, alerts=alerts
    )


@app.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
def edit_course(course_id):
    course = db.get_or_404(GolfCourse, course_id)

    if request.method == "POST":
        course.name = request.form.get("name", "").strip() or course.name
        url = request.form.get("url", "").strip()
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        if url:
            course.url = url
        course.check_interval_minutes = int(request.form.get("interval", course.check_interval_minutes))
        start_time, end_time, desired_days = _parse_time_prefs(request.form)
        course.desired_start_time = start_time
        course.desired_end_time = end_time
        course.desired_days = desired_days
        db.session.commit()

        from scheduler import add_course_job
        add_course_job(app, course)

        flash(f"Updated {course.name}.", "success")
        return redirect(url_for("course_detail", course_id=course_id))

    return render_template("edit_course.html", course=course, days=DAYS_OF_WEEK)


@app.route("/courses/<int:course_id>/check", methods=["POST"])
def check_now(course_id):
    course = db.get_or_404(GolfCourse, course_id)
    from scheduler import check_course
    check_course(app, course_id)
    flash(f"Manual check completed for {course.name}.", "success")
    return redirect(url_for("course_detail", course_id=course_id))


@app.route("/courses/<int:course_id>/toggle", methods=["POST"])
def toggle_course(course_id):
    course = db.get_or_404(GolfCourse, course_id)
    course.active = not course.active
    db.session.commit()

    from scheduler import add_course_job, remove_course_job
    if course.active:
        add_course_job(app, course)
    else:
        remove_course_job(course_id)

    status = "enabled" if course.active else "paused"
    flash(f"{course.name} {status}.", "success")
    return redirect(url_for("course_detail", course_id=course_id))


@app.route("/courses/<int:course_id>/delete", methods=["POST"])
def delete_course(course_id):
    course = db.get_or_404(GolfCourse, course_id)
    name = course.name

    from scheduler import remove_course_job
    remove_course_job(course_id)

    db.session.delete(course)
    db.session.commit()

    flash(f"Removed {name}.", "success")
    return redirect(url_for("index"))


@app.route("/alerts/<int:alert_id>/dismiss", methods=["POST"])
def dismiss_alert(alert_id):
    alert = db.get_or_404(TeeTimeAlert, alert_id)
    alert.dismissed = True
    alert.dismissed_at = datetime.utcnow()
    db.session.commit()
    return redirect(request.referrer or url_for("index"))


@app.route("/api/courses")
def api_courses():
    courses = GolfCourse.query.all()
    return jsonify(
        [
            {
                "id": c.id,
                "name": c.name,
                "url": c.url,
                "active": c.active,
                "last_checked_at": c.last_checked_at.isoformat() if c.last_checked_at else None,
                "last_check_status": c.last_check_status,
                "release_event_count": len(c.release_events),
                "active_alert_count": len(c.active_alerts),
            }
            for c in courses
        ]
    )


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        _run_migrations()

    from scheduler import start_scheduler
    start_scheduler(app)

    app.run(debug=True, host="0.0.0.0", port=8080, use_reloader=False)
