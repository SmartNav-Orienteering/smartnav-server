"""Database models (SQLite by default)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """SQLite drops time zones; store naive UTC and hand back aware datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="delegate")  # owner | delegate
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class Folder(Base):
    """Folders organise events. A folder marked as a series has standings."""

    __tablename__ = "folders"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    is_series: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    children: Mapped[list["Folder"]] = relationship(back_populates="parent")
    parent: Mapped["Folder | None"] = relationship(back_populates="children", remote_side=[id])
    events: Mapped[list["Event"]] = relationship(back_populates="folder")


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    club: Mapped[str] = mapped_column(String(200), default="")
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|published|archived
    event_type: Mapped[str] = mapped_column(String(50), default="line")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    opens_at: Mapped[datetime] = mapped_column(UTCDateTime())
    closes_at: Mapped[datetime] = mapped_column(UTCDateTime())
    timezone: Mapped[str] = mapped_column(String(64), default="Australia/Sydney")
    info_url: Mapped[str] = mapped_column(String(500), default="")
    time_limit_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    punch_radius_m: Mapped[float] = mapped_column(Float, default=15)
    start: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {code, lat, lon, mode}
    finish: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    controls: Mapped[list] = mapped_column(JSON, default=list)  # [{code, lat, lon}]
    max_accuracy_m: Mapped[float] = mapped_column(Float, default=25)
    repunch_cooldown_s: Mapped[float] = mapped_column(Float, default=30)
    recording_interval_s: Mapped[float] = mapped_column(Float, default=1)
    max_duration_s: Mapped[float] = mapped_column(Float, default=14400)
    alerts: Mapped[list] = mapped_column(JSON, default=list)
    participant_fields: Mapped[list] = mapped_column(JSON, default=list)
    map_image: Mapped[str | None] = mapped_column(String(300), nullable=True)
    map_bounds: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # north,south,east,west,rotation
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    folder: Mapped[Folder | None] = relationship(back_populates="events")
    versions: Mapped[list["PackageVersion"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="PackageVersion.id"
    )
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class PackageVersion(Base):
    """Every published version of a course package is kept, so a run is
    always scored against the course the participant downloaded."""

    __tablename__ = "package_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))
    package_hash: Mapped[str] = mapped_column(String(100), index=True)
    package: Mapped[dict] = mapped_column(JSON)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    event: Mapped[Event] = relationship(back_populates="versions")


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # submission_id UUID
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    package_hash: Mapped[str] = mapped_column(String(100))
    body_hash: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(20), default="app")  # app | gpx
    participant_name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200), index=True)
    participant: Mapped[dict] = mapped_column(JSON, default=dict)
    device: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime] = mapped_column(UTCDateTime())
    end_reason: Mapped[str] = mapped_column(String(30))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|scored|needs_review|rejected
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    disqualified: Mapped[bool] = mapped_column(Boolean, default=False)
    dsq_reason: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    review_reasons: Mapped[list] = mapped_column(JSON, default=list)
    raw_path: Mapped[str] = mapped_column(String(300))
    event: Mapped[Event] = relationship(back_populates="submissions")
    overrides: Mapped[list["ControlOverride"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )


class ControlOverride(Base):
    __tablename__ = "control_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    decision: Mapped[str] = mapped_column(String(20))  # accepted | denied
    reason: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    submission: Mapped[Submission] = relationship(back_populates="overrides")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_name: Mapped[str] = mapped_column(String(200), default="")
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str] = mapped_column(Text, default="")


_engine = None
_Session: sessionmaker | None = None


def init_engine(db_url: str):
    global _engine, _Session
    _engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(_engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session() -> Iterator[Session]:
    assert _Session is not None, "init_engine() not called"
    s = _Session()
    try:
        yield s
    finally:
        s.close()


def new_session() -> Session:
    assert _Session is not None
    return _Session()
