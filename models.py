from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from collections import Counter
import json

db = SQLAlchemy()

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class GolfCourse(db.Model):
    __tablename__ = "golf_courses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    check_interval_minutes = db.Column(db.Integer, default=60)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_checked_at = db.Column(db.DateTime, nullable=True)
    last_check_status = db.Column(db.String(20), default="pending")

    desired_start_time = db.Column(db.String(10), nullable=True)
    desired_end_time = db.Column(db.String(10), nullable=True)
    desired_days = db.Column(db.String(100), default="")

    snapshots = db.relationship(
        "TeeTimeSnapshot", backref="course", lazy=True,
        cascade="all, delete-orphan", order_by="TeeTimeSnapshot.checked_at.desc()",
    )
    release_events = db.relationship(
        "ReleaseEvent", backref="course", lazy=True,
        cascade="all, delete-orphan", order_by="ReleaseEvent.detected_at.desc()",
    )
    alerts = db.relationship(
        "TeeTimeAlert", backref="course", lazy=True,
        cascade="all, delete-orphan", order_by="TeeTimeAlert.detected_at.desc()",
    )

    @property
    def desired_days_list(self):
        if not self.desired_days:
            return []
        return [d for d in self.desired_days.split(",") if d]

    @property
    def has_time_preference(self):
        return bool(self.desired_start_time and self.desired_end_time)

    @property
    def active_alerts(self):
        from datetime import date
        today = date.today().isoformat()
        return [
            a for a in self.alerts
            if not a.dismissed and (a.matched_for_date is None or a.matched_for_date >= today)
        ]

    def release_pattern_summary(self):
        if len(self.release_events) < 2:
            return "Not enough data yet — keep monitoring"
        days = Counter(e.detected_at.strftime("%A") for e in self.release_events)
        hours = Counter(e.detected_at.hour for e in self.release_events)
        top_day = days.most_common(1)[0][0]
        top_hour = hours.most_common(1)[0][0]
        return f"Usually {top_day}s around {top_hour:02d}:00"


class TeeTimeSnapshot(db.Model):
    __tablename__ = "tee_time_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("golf_courses.id"), nullable=False)
    checked_at = db.Column(db.DateTime, default=datetime.utcnow)
    content_hash = db.Column(db.String(64), nullable=True)
    slot_count = db.Column(db.Integer, default=0)
    _available_slots = db.Column("available_slots", db.Text, default="[]")
    scrape_success = db.Column(db.Boolean, default=True)
    error_message = db.Column(db.Text, nullable=True)

    @property
    def available_slots(self):
        return json.loads(self._available_slots or "[]")

    @available_slots.setter
    def available_slots(self, value):
        self._available_slots = json.dumps(value)


class ReleaseEvent(db.Model):
    __tablename__ = "release_events"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("golf_courses.id"), nullable=False)
    detected_at = db.Column(db.DateTime, default=datetime.utcnow)
    new_slot_count = db.Column(db.Integer, default=0)
    _new_slots = db.Column("new_slots", db.Text, default="[]")

    @property
    def new_slots(self):
        return json.loads(self._new_slots or "[]")

    @new_slots.setter
    def new_slots(self, value):
        self._new_slots = json.dumps(value)


class TeeTimeAlert(db.Model):
    __tablename__ = "tee_time_alerts"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("golf_courses.id"), nullable=False)
    detected_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Stored as JSON list of dicts: [{time, date, label, url}, ...]
    _matched_slots = db.Column("matched_slots", db.Text, default="[]")
    # Earliest date covered by this alert ("YYYY-MM-DD"); used for auto-expiry
    matched_for_date = db.Column(db.String(10), nullable=True)
    dismissed = db.Column(db.Boolean, default=False)
    dismissed_at = db.Column(db.DateTime, nullable=True)

    @property
    def matched_slots(self):
        return json.loads(self._matched_slots or "[]")

    @matched_slots.setter
    def matched_slots(self, value):
        self._matched_slots = json.dumps(value)

    @property
    def slot_links(self):
        """Return slots normalised as dicts with time/label/url, handles legacy strings."""
        result = []
        for s in self.matched_slots:
            if isinstance(s, dict):
                result.append(s)
            else:
                result.append({"time": s, "label": "", "date": None, "url": None})
        return result
