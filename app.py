import logging
import os

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

from models import db, GolfCourse, TeeTimeSnapshot, ReleaseEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///itsteettime.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


@app.route("/")
def index():
    courses = GolfCourse.query.order_by(GolfCourse.created_at.desc()).all()
    return render_template("index.html", courses=courses)


@app.route("/courses/add", methods=["GET", "POST"])
def add_course():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        url = request.form.get("url", "").strip()
        interval = int(request.form.get("interval", 60))

        if not name or not url:
            flash("Name and URL are required.", "error")
            return render_template("add_course.html")

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        course = GolfCourse(name=name, url=url, check_interval_minutes=interval)
        db.session.add(course)
        db.session.commit()

        from scheduler import add_course_job
        add_course_job(app, course)

        flash(f"Added {name}. First check will run at the next interval.", "success")
        return redirect(url_for("course_detail", course_id=course.id))

    return render_template("add_course.html")


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
    return render_template("course.html", course=course, snapshots=snapshots, events=events)


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
            }
            for c in courses
        ]
    )


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    from scheduler import start_scheduler
    start_scheduler(app)

    app.run(debug=True, host="0.0.0.0", port=8080, use_reloader=False)
