from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from collections import Counter
import json

db = SQLAlchemy()


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

    snapshots = db.relationship(
        "TeeTimeSnapshot",
        backref="course",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="TeeTimeSnapshot.checked_at.desc()",
    )
    release_events = db.relationship(
        "ReleaseEvent",
        backref="course",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="ReleaseEvent.detected_at.desc()",
    )

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
