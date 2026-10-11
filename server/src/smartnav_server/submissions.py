"""Accepting runs: from the phone app (JSON) or uploaded GPX files."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from smartnav_sdk.detect import entries
from sqlalchemy.orm import Session

from .config import get_settings
from .contract import SUPPORTED_SUBMISSION_VERSIONS, ApiError, SubmissionIn
from .db import Event, Submission
from .packages import canonical, course_from_package, latest_version
from .people import clean_name, name_key
from .scoring import score_submission


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def accept_submission(db: Session, event_id: str, raw: dict) -> tuple[Submission, bool]:
    """Validate, store and score. Returns (submission, created)."""
    if raw.get("format_version") not in SUPPORTED_SUBMISSION_VERSIONS:
        raise ApiError(
            400,
            "unsupported_version",
            "This server accepts submission format version 1. Please update the SmartNav app.",
        )
    try:
        sub_in = SubmissionIn.model_validate(raw)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first["loc"])
        raise ApiError(400, "invalid_submission", f"Invalid submission ({where}): {first['msg']}")

    if sub_in.event_id != event_id:
        raise ApiError(400, "invalid_submission", "event_id does not match the URL.")
    ev = db.get(Event, event_id)
    if ev is None or ev.status == "draft":
        raise ApiError(404, "event_not_found", "This event is not known to the server.")
    if ev.status == "archived":
        raise ApiError(410, "event_closed", f"Entries for {ev.name} are closed.")

    _check_track(sub_in)
    name = clean_name(str(sub_in.participant.get("name", "")))
    if not name:
        raise ApiError(400, "invalid_submission", "Participant name is required.")

    body_hash = hashlib.sha256(canonical(raw)).hexdigest()
    existing = db.get(Submission, sub_in.submission_id)
    if existing:
        if existing.body_hash == body_hash and existing.event_id == event_id:
            return existing, False
        raise ApiError(409, "submission_conflict", "A different run with this submission_id already exists.")

    sub = _store(db, ev, raw, sub_in.submission_id, body_hash, name, "app")
    sub.device = sub_in.device.model_dump()
    score_submission(db, sub)
    db.commit()
    return sub, True


def _check_track(s: SubmissionIn) -> None:
    idx = {f: i for i, f in enumerate(s.track.fields)}
    prev = -1
    for row in s.track.points:
        try:
            dt, lat, lon = row[idx["dt_ms"]], row[idx["lat"]], row[idx["lon"]]
        except IndexError:
            raise ApiError(400, "invalid_submission", "A track point has too few values.")
        if dt is None or lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ApiError(400, "invalid_submission", "Track contains an invalid point.")
        if dt < prev:
            raise ApiError(400, "invalid_submission", "Track times must increase.")
        prev = dt
    if not s.track.points:
        raise ApiError(400, "invalid_submission", "The track is empty.")


def _store(db, ev, raw, sub_id, body_hash, name, source) -> Submission:
    settings = get_settings()
    folder = settings.submissions_dir / ev.id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sub_id}.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    act = raw["activity"]
    sub = Submission(
        id=sub_id,
        event_id=ev.id,
        package_hash=raw["package_hash"],
        body_hash=body_hash,
        source=source,
        participant_name=name,
        name_key=name_key(name),
        participant={**raw.get("participant", {}), "name": name},
        started_at=datetime.fromisoformat(act["started_at"].replace("Z", "+00:00")),
        ended_at=datetime.fromisoformat(act["ended_at"].replace("Z", "+00:00")),
        end_reason=act["end_reason"],
        raw_path=str(path),
    )
    db.add(sub)
    db.flush()
    db.refresh(sub)
    return sub


def accept_gpx(
    db: Session, ev: Event, points: list, participant: dict
) -> Submission:
    """Turn a GPX track into a submission. The start time is the moment the
    runner leaves the start circle (or the first point)."""
    version = latest_version(ev)
    if version is None:
        raise ValueError("This event has no published course.")
    course = course_from_package(version.package)
    from smartnav_sdk import TrackPoint

    tps = [TrackPoint(t, lat, lon, None) for t, lat, lon, _ in points]
    start_t = tps[0].t
    # last moment inside the start circle before moving off
    inside_idx = None
    from smartnav_sdk.geo import distance_m

    for i, p in enumerate(tps):
        if distance_m(p.lat, p.lon, course.start.lat, course.start.lon) <= course.punch_radius_m:
            inside_idx = i
        elif inside_idx is not None:
            break
    if inside_idx is not None:
        start_t = tps[inside_idx].t
    tps = [p for p in tps if p.t >= start_t]
    epoch = tps[0].t
    sub_id = str(uuid.uuid4())
    raw = {
        "format": "smartnav.submission",
        "format_version": 1,
        "submission_id": sub_id,
        "event_id": ev.id,
        "package_hash": version.package_hash,
        "participant": participant,
        "device": {"platform": "gpx-upload"},
        "activity": {
            "started_at": _iso(start_t),
            "ended_at": _iso(tps[-1].t),
            "start_method": "gpx",
            "end_reason": "gpx_upload",
        },
        "punches": [],
        "track": {
            "epoch": _iso(epoch),
            "fields": ["dt_ms", "lat", "lon", "acc_m", "alt_m"],
            "points": [
                [int((p.t - epoch).total_seconds() * 1000), p.lat, p.lon, None, alt]
                for p, (_, _, _, alt) in zip(tps, points[len(points) - len(tps):])
            ],
        },
        "app_log": [],
    }
    name = clean_name(participant.get("name", ""))
    sub = _store(db, ev, raw, sub_id, hashlib.sha256(canonical(raw)).hexdigest(), name, "gpx")
    score_submission(db, sub)
    db.commit()
    return sub
