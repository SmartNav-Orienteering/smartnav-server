"""Builds the JSON documents the app receives (result, results list, track)."""
from __future__ import annotations

from datetime import timezone

from sqlalchemy.orm import Session

from .config import get_settings
from .db import Event, Submission
from .scoring import Entry, find_entry, ordinal, rank_event, run_from_raw, load_raw


def iso(d):
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if d else None


def headline(entry: Entry, first: Entry, n_ranked: int) -> str:
    r = entry.result or {}
    display = r.get("display", "")
    if entry is not first:
        return f"{display} — repeat run {entry.run_number} (unranked; only the first run counts)"
    if entry.ranked:
        if entry.age_class and entry.class_count:
            return f"{display} — {ordinal(entry.class_position)} of {entry.class_count} ({entry.age_class})"
        return f"{display} — {ordinal(entry.position)} of {n_ranked}"
    return display


def result_document(db: Session, sub: Submission) -> dict:
    ev = sub.event
    entries, n_ranked = rank_event(db, ev)
    entry, first = find_entry(entries, sub.id)
    base = get_settings().base_url
    doc = {
        "format": "smartnav.result",
        "format_version": 1,
        "submission_id": sub.id,
        "status": sub.status,
        "provisional": sub.status == "needs_review",
        "event_type": ev.event_type,
        "results_url": f"{base}/events/{ev.id}/results",
        "messages": [],
    }
    if sub.status == "rejected" or not sub.result or entry is None:
        doc["summary"] = {"headline": "Not scored", "lines": sub.review_reasons or []}
        doc["controls"] = []
        doc["messages"] = sub.review_reasons or []
        return doc
    r = sub.result
    doc["summary"] = {
        "headline": headline(entry, first, n_ranked),
        "lines": r.get("lines", []),
        "elapsed_s": r.get("elapsed_s"),
        "position": entry.position if entry is first else None,
        "of": n_ranked if entry is first else None,
        "score": r.get("score"),
        "age_class": entry.age_class or None,
        "first_run": entry is first,
    }
    doc["controls"] = r.get("controls", [])
    if sub.status == "needs_review":
        doc["messages"] = ["Provisional: the organiser will review this run."]
    return doc


def results_list(db: Session, ev: Event) -> dict:
    entries, n_ranked = rank_event(db, ev)

    def row(e: Entry, first: bool):
        r = e.result or {}
        return {
            "submission_id": e.sub.id,
            "position": e.position if first else None,
            "name": e.name,
            "club": e.club,
            "age_class": e.age_class,
            "status": r.get("status"),
            "display": r.get("display"),
            "elapsed_s": r.get("elapsed_s"),
            "score": r.get("score"),
            "provisional": e.sub.status == "needs_review",
            "run_number": e.run_number,
            "started_at": iso(e.sub.started_at),
            "track_url": f"/v1/submissions/{e.sub.id}/track",
        }

    rows = []
    for e in entries:
        rows.append({**row(e, True), "repeats": [row(r, False) for r in e.repeats]})
    return {
        "format": "smartnav.results",
        "format_version": 1,
        "event": {"id": ev.id, "name": ev.name, "event_type": ev.event_type},
        "ranked": n_ranked,
        "results": rows,
    }


def track_document(sub: Submission) -> dict:
    run = run_from_raw(load_raw(sub))
    t0 = run.started_at
    return {
        "format": "smartnav.track",
        "format_version": 1,
        "submission_id": sub.id,
        "name": sub.participant_name,
        "started_at": iso(run.started_at),
        "fields": ["t_s", "lat", "lon"],
        "points": [
            [round((p.t - t0).total_seconds(), 1), round(p.lat, 6), round(p.lon, 6)] for p in run.track
        ],
    }
