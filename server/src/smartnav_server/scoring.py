"""Scores runs with the event's plugin, and ranks an event's results.

Ranking rule (spec): only each participant's first run of an event is
ranked, in the event results and for the series. Later runs are listed
as unranked repeats."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from smartnav_sdk import Override, PhonePunch, Result, Run, TrackPoint
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Event, Folder, Setting, Submission
from .packages import course_from_package, find_version, latest_version
from .people import age_class
from .plugins import get_event_type

log = logging.getLogger(__name__)

GAP_LIMIT_S = 60
POOR_ACCURACY_SHARE = 0.20


# ----------------------------------------------------------------- loading
def load_raw(sub: Submission) -> dict:
    return json.loads(Path(sub.raw_path).read_text(encoding="utf-8"))


def _dt(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def run_from_raw(raw: dict) -> Run:
    tr = raw["track"]
    epoch = _dt(tr["epoch"])
    idx = {f: i for i, f in enumerate(tr["fields"])}
    pts = []
    for row in tr["points"]:
        acc = row[idx["acc_m"]] if "acc_m" in idx else None
        alt = row[idx["alt_m"]] if "alt_m" in idx else None
        pts.append(
            TrackPoint(
                epoch + timedelta(milliseconds=row[idx["dt_ms"]]),
                float(row[idx["lat"]]),
                float(row[idx["lon"]]),
                acc,
                alt,
            )
        )
    act = raw["activity"]
    punches = [
        PhonePunch(p["code"], _dt(p["t"]), p.get("lat"), p.get("lon"), p.get("accuracy_m"), p.get("distance_m"))
        for p in raw.get("punches", [])
    ]
    return Run(
        submission_id=raw["submission_id"],
        started_at=_dt(act["started_at"]),
        ended_at=_dt(act["ended_at"]),
        start_method=act.get("start_method", "tap"),
        end_reason=act["end_reason"],
        track=pts,
        phone_punches=punches,
        participant=raw.get("participant", {}),
    )


def track_checks(run: Run, max_accuracy_m: float) -> list[str]:
    reasons = []
    pts = run.track
    if not pts:
        return ["The track is empty."]
    gaps = [
        (b.t - a.t).total_seconds() for a, b in zip(pts, pts[1:]) if (b.t - a.t).total_seconds() > GAP_LIMIT_S
    ]
    if gaps:
        reasons.append(f"GPS track has {len(gaps)} gap(s) longer than {GAP_LIMIT_S} s (longest {int(max(gaps))} s).")
    poor = sum(1 for p in pts if p.acc_m is not None and p.acc_m > max_accuracy_m)
    if pts and poor / len(pts) > POOR_ACCURACY_SHARE:
        reasons.append(f"GPS accuracy was poor for {round(100 * poor / len(pts))}% of the track.")
    return reasons


# ----------------------------------------------------------------- scoring
def score_submission(db: Session, sub: Submission) -> None:
    """(Re)score one submission and store the result on it."""
    ev: Event = sub.event
    reasons: list[str] = []
    version = find_version(ev, sub.package_hash)
    if version is None:
        version = latest_version(ev)
        reasons.append("Run used a course version this server does not know; scored against the current course.")
    elif version is not latest_version(ev):
        reasons.append("The course has changed since this participant downloaded it; scored against the version they ran.")
    if version is None:
        sub.status, sub.result = "rejected", None
        sub.review_reasons = ["The event has no published course."]
        return

    et = get_event_type(version.package["course"]["event_type"])
    if et is None:
        sub.status = "needs_review"
        sub.review_reasons = [f"Event type {version.package['course']['event_type']!r} is not installed on this server."]
        sub.result = None
        return

    raw = load_raw(sub)
    run = run_from_raw(raw)
    course = course_from_package(version.package)
    overrides = [Override(o.code, o.decision) for o in sub.overrides]
    try:
        result = et.evaluate(run, course, dict(version.params or {}), overrides)
    except Exception as e:  # a plugin error must not lose the run
        log.exception("Scoring failed for %s", sub.id)
        sub.status = "needs_review"
        sub.review_reasons = [f"Scoring failed: {e}"]
        sub.result = None
        return

    if sub.disqualified:
        result.status = "dsq"
        result.display = "DSQ"
        result.lines = [f"Disqualified: {sub.dsq_reason}" if sub.dsq_reason else "Disqualified by the organiser"]

    if not (ev.opens_at - timedelta(minutes=5) <= run.started_at <= ev.closes_at):
        reasons.append("Run started outside the event window.")
    reasons += track_checks(run, course.max_accuracy_m)
    if sub.source == "gpx":
        reasons.append("Uploaded as a GPX file; start time taken from the track.")
    reasons += result.review_reasons

    sub.result = _result_to_json(result, ev)
    sub.review_reasons = reasons
    sub.status = "needs_review" if (reasons and not sub.reviewed) else "scored"


def _result_to_json(r: Result, ev: Event) -> dict:
    def iso(d):
        return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if d else None

    return {
        "status": r.status,
        "elapsed_s": r.elapsed_s,
        "display": r.display,
        "lines": r.lines,
        "score": r.score,
        "finish_t": iso(r.finish_t),
        "controls": [
            {"code": c.code, "status": c.status, "t": iso(c.t), "split_s": c.split_s, **({"points": c.points} if c.points is not None else {})}
            for c in r.controls
        ],
        "extra": r.extra,
    }


def result_from_json(d: dict) -> Result:
    return Result(
        status=d["status"],
        elapsed_s=d.get("elapsed_s"),
        display=d.get("display", ""),
        lines=d.get("lines", []),
        score=d.get("score"),
        extra=d.get("extra", {}),
    )


def rescore_event(db: Session, ev: Event) -> int:
    n = 0
    for sub in ev.submissions:
        score_submission(db, sub)
        n += 1
    return n


# ----------------------------------------------------------------- ranking
def get_setting(db: Session, key: str, default: Any = None) -> Any:
    s = db.get(Setting, key)
    return s.value if s else default


@dataclass
class Entry:
    sub: Submission
    name: str
    club: str
    age_class: str
    result: dict | None
    first_run: bool
    run_number: int
    ranked: bool = False
    position: int | None = None
    class_position: int | None = None
    class_count: int = 0
    repeats: list["Entry"] = field(default_factory=list)


def rank_event(db: Session, ev: Event) -> tuple[list[Entry], int]:
    """Returns (entries for first runs with their repeats attached, number ranked).

    Entries are sorted: ranked first by position, then unranked first runs."""
    classes = get_setting(db, "age_classes")
    et = get_event_type(ev.event_type)
    subs = [s for s in ev.submissions if s.status != "rejected"]
    subs.sort(key=lambda s: s.started_at)
    by_person: dict[str, list[Submission]] = {}
    for s in subs:
        by_person.setdefault(s.name_key, []).append(s)

    firsts: list[Entry] = []
    for runs in by_person.values():
        entries = []
        for i, s in enumerate(runs, start=1):
            p = s.participant or {}
            entries.append(
                Entry(
                    sub=s,
                    name=s.participant_name,
                    club=str(p.get("club") or ""),
                    age_class=age_class(p.get("year_of_birth"), s.started_at, classes),
                    result=s.result,
                    first_run=(i == 1),
                    run_number=i,
                )
            )
        first = entries[0]
        first.repeats = entries[1:]
        firsts.append(first)

    def key(e: Entry):
        if not e.result or et is None:
            return None
        return et.rank_key(result_from_json(e.result))

    ranked = [(key(e), e) for e in firsts]
    ranked_ok = sorted([x for x in ranked if x[0] is not None], key=lambda x: x[0])
    pos = 0
    prev_k = object()
    for i, (k, e) in enumerate(ranked_ok, start=1):
        if k != prev_k:
            pos = i
        e.ranked, e.position = True, pos
        prev_k = k
    # class positions
    by_class: dict[str, list[tuple]] = {}
    for k, e in ranked_ok:
        by_class.setdefault(e.age_class, []).append((k, e))
    for lst in by_class.values():
        cpos, prev = 0, object()
        for i, (k, e) in enumerate(lst, start=1):
            if k != prev:
                cpos = i
            e.class_position, e.class_count = cpos, len(lst)
            prev = k
    unranked = [e for k, e in ranked if k is None]
    unranked.sort(key=lambda e: (_status_order(e), e.name.casefold()))
    return [e for _, e in ranked_ok] + unranked, len(ranked_ok)


def _status_order(e: Entry) -> int:
    order = {"ok": 0, "ot": 1, "mp": 2, "dnf": 3, "dsq": 4}
    return order.get((e.result or {}).get("status", ""), 5)


def ordinal(n: int) -> str:
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def find_entry(entries: list[Entry], sub_id: str) -> tuple[Entry | None, Entry | None]:
    """Returns (entry for that run, its first-run entry)."""
    for e in entries:
        if e.sub.id == sub_id:
            return e, e
        for r in e.repeats:
            if r.sub.id == sub_id:
                return r, e
    return None, None


# ----------------------------------------------------------------- series
@dataclass
class SeriesRow:
    name: str
    club: str
    age_class: str
    total: float
    per_event: dict[str, float]
    position: int = 0


def series_standings(db: Session, folder: Folder) -> tuple[list[Event], list[SeriesRow]]:
    events = sorted(
        [e for e in folder.events if e.status in ("published", "archived")], key=lambda e: e.opens_at
    )
    people: dict[str, SeriesRow] = {}
    for ev in events:
        et = get_event_type(ev.event_type)
        entries, _ = rank_event(db, ev)
        ranked = [e for e in entries if e.ranked]
        if not ranked or et is None:
            continue
        winner = result_from_json(ranked[0].result)
        for e in ranked:
            pts = et.series_points(result_from_json(e.result), winner)
            row = people.setdefault(
                e.sub.name_key, SeriesRow(e.name, e.club, e.age_class, 0.0, {})
            )
            row.per_event[ev.id] = pts
            row.total = round(row.total + pts, 1)
            row.club = row.club or e.club
            row.age_class = row.age_class or e.age_class
    rows = sorted(people.values(), key=lambda r: (-r.total, r.name.casefold()))
    pos, prev = 0, None
    for i, r in enumerate(rows, start=1):
        if r.total != prev:
            pos = i
        r.position, prev = pos, r.total
    return events, rows
