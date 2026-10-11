"""The /v1 API used by the phone app (docs/contract-v1.md)."""
from __future__ import annotations

import gzip
import json

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .contract import ApiError
from .db import Event, Submission, get_session, utcnow
from .packages import latest_version
from .submissions import accept_submission
from .views import iso, result_document, results_list, track_document

router = APIRouter(prefix="/v1")


def _public_event(db: Session, event_id: str) -> Event:
    ev = db.get(Event, event_id)
    if ev is None or ev.status == "draft":
        raise ApiError(404, "event_not_found", "This event is not known to the server.")
    return ev


@router.get("/events")
def list_events(db: Session = Depends(get_session)):
    now = utcnow()
    evs = db.scalars(
        select(Event).where(Event.status == "published", Event.closes_at > now).order_by(Event.opens_at)
    ).all()
    base = get_settings().base_url
    return {
        "format": "smartnav.events",
        "format_version": 1,
        "events": [
            {
                "id": e.id,
                "name": e.name,
                "club": e.club,
                "event_type": e.event_type,
                "opens_at": iso(e.opens_at),
                "closes_at": iso(e.closes_at),
                "package_url": f"{base}/v1/events/{e.id}/package",
            }
            for e in evs
            if latest_version(e)
        ],
    }


@router.get("/events/{event_id}/package")
def get_package(event_id: str, request: Request, db: Session = Depends(get_session)):
    ev = _public_event(db, event_id)
    v = latest_version(ev)
    if v is None:
        raise ApiError(404, "event_not_found", "This event has no published course yet.")
    etag = f'"{v.package_hash}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse(v.package, headers={"ETag": etag, "Cache-Control": "no-cache"})


@router.post("/events/{event_id}/submissions")
async def post_submission(event_id: str, request: Request, db: Session = Depends(get_session)):
    limit = get_settings().max_body_bytes
    body = await request.body()
    if request.headers.get("content-encoding", "").lower() == "gzip":
        try:
            body = _gunzip_limited(body, limit)
        except OSError:
            raise ApiError(400, "invalid_submission", "The gzip body could not be decompressed.")
    if len(body) > limit:
        raise ApiError(413, "too_large", "The submission is larger than 10 MB.")
    try:
        raw = json.loads(body)
        if not isinstance(raw, dict):
            raise ValueError
    except ValueError:
        raise ApiError(400, "invalid_submission", "The body is not valid JSON.")
    sub, created = accept_submission(db, event_id, raw)
    return JSONResponse(result_document(db, sub), status_code=201 if created else 200)


def _gunzip_limited(data: bytes, limit: int) -> bytes:
    d = gzip.GzipFile(fileobj=__import__("io").BytesIO(data))
    out = d.read(limit + 1)
    if len(out) > limit:
        raise ApiError(413, "too_large", "The submission is larger than 10 MB.")
    return out


@router.get("/submissions/{submission_id}/result")
def get_result(submission_id: str, db: Session = Depends(get_session)):
    sub = db.get(Submission, submission_id)
    if sub is None:
        raise ApiError(404, "submission_not_found", "This run is not known to the server.")
    return result_document(db, sub)


@router.get("/events/{event_id}/results")
def get_results(event_id: str, db: Session = Depends(get_session)):
    return results_list(db, _public_event(db, event_id))


@router.get("/submissions/{submission_id}/track")
def get_track(submission_id: str, db: Session = Depends(get_session)):
    sub = db.get(Submission, submission_id)
    if sub is None or sub.status == "rejected":
        raise ApiError(404, "submission_not_found", "This run is not known to the server.")
    return track_document(sub)
