"""Builds course packages and keeps every published version."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from smartnav_sdk import Control, Course
from sqlalchemy.orm import Session

from .db import Event, PackageVersion
from .plugins import get_event_type

DEFAULT_PARTICIPANT_FIELDS = [
    {"key": "name", "label": "Name", "required": True},
    {"key": "club", "label": "Club", "required": False},
    {"key": "year_of_birth", "label": "Year of birth", "required": True},
]


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def package_hash(pkg: dict) -> str:
    body = {k: v for k, v in pkg.items() if k != "package_hash"}
    return "sha256:" + hashlib.sha256(canonical(body)).hexdigest()


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def build_package(ev: Event, base_url: str) -> dict:
    et = get_event_type(ev.event_type)
    ordered = bool(et.ordered) if et else ev.event_type == "line"
    pkg = {
        "format": "smartnav.package",
        "format_version": 1,
        "event": {
            "id": ev.id,
            "name": ev.name,
            "club": ev.club,
            "opens_at": _iso(ev.opens_at),
            "closes_at": _iso(ev.closes_at),
            "timezone": ev.timezone,
            **({"info_url": ev.info_url} if ev.info_url else {}),
        },
        "server": {"submit_url": f"{base_url}/v1/events/{ev.id}/submissions"},
        "course": {
            "event_type": ev.event_type,
            "ordered": ordered,
            "time_limit_min": _num(ev.time_limit_min),
            "punch_radius_m": _num(ev.punch_radius_m),
            "start": _point(ev.start, "S"),
            "finish": _point(ev.finish or ev.start, "F"),
            "controls": [
                {"code": c["code"], "lat": round(c["lat"], 6), "lon": round(c["lon"], 6)}
                for c in ev.controls
            ],
        },
        "punching": {
            "max_accuracy_m": _num(ev.max_accuracy_m),
            "repunch_cooldown_s": _num(ev.repunch_cooldown_s),
        },
        "recording": {
            "interval_s": _num(ev.recording_interval_s),
            "max_duration_s": _num(ev.max_duration_s),
        },
        "alerts": ev.alerts or [],
        "participant_fields": ev.participant_fields or DEFAULT_PARTICIPANT_FIELDS,
    }
    pkg["package_hash"] = package_hash(pkg)
    return pkg


def _num(v):
    """Whole numbers as int, others as float, so the package hash does not
    change when a value round-trips through the database (15 vs 15.0)."""
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def _point(p: dict | None, code: str) -> dict:
    p = p or {"lat": 0, "lon": 0, "mode": "tap"}
    return {
        "code": p.get("code") or code,
        "lat": round(p["lat"], 6),
        "lon": round(p["lon"], 6),
        "mode": p.get("mode", "punch"),
    }


def course_from_package(pkg: dict) -> Course:
    c = pkg["course"]
    return Course(
        event_type=c["event_type"],
        ordered=c["ordered"],
        controls=[Control(x["code"], x["lat"], x["lon"]) for x in c["controls"]],
        start=Control(c["start"]["code"], c["start"]["lat"], c["start"]["lon"]),
        finish=Control(c["finish"]["code"], c["finish"]["lat"], c["finish"]["lon"]),
        punch_radius_m=c["punch_radius_m"],
        start_mode=c["start"].get("mode", "punch"),
        finish_mode=c["finish"].get("mode", "punch"),
        time_limit_min=c.get("time_limit_min"),
        max_accuracy_m=pkg.get("punching", {}).get("max_accuracy_m", 25),
    )


def course_from_event(ev: Event, base_url: str) -> Course:
    return course_from_package(build_package(ev, base_url))


def publish_version(db: Session, ev: Event, base_url: str) -> PackageVersion:
    """Record the current package (and host-only params) as a version if
    it changed. Returns the latest version."""
    pkg = build_package(ev, base_url)
    latest = ev.versions[-1] if ev.versions else None
    if latest and latest.package_hash == pkg["package_hash"] and latest.params == (ev.params or {}):
        return latest
    if latest and latest.package_hash == pkg["package_hash"]:
        latest.params = dict(ev.params or {})
        return latest
    v = PackageVersion(
        event_id=ev.id, package_hash=pkg["package_hash"], package=pkg, params=dict(ev.params or {})
    )
    ev.versions.append(v)
    db.flush()
    return v


def latest_version(ev: Event) -> PackageVersion | None:
    return ev.versions[-1] if ev.versions else None


def find_version(ev: Event, pkg_hash: str) -> PackageVersion | None:
    for v in reversed(ev.versions):
        if v.package_hash == pkg_hash:
            return v
    return None
