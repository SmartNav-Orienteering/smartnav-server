"""Public pages: event list, results, track maps, series standings, GPX upload."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import check_csrf
from .config import get_settings
from .db import Event, Folder, Submission, get_session
from .importers import ImportError_, parse_gpx
from .maps import map_config
from .people import clean_name
from .scoring import rank_event, series_standings
from .submissions import accept_gpx
from .web import render

router = APIRouter()

PUBLIC = ("published", "archived")


def public_event(db: Session, event_id: str) -> Event:
    ev = db.get(Event, event_id)
    if ev is None or ev.status not in PUBLIC:
        raise HTTPException(404, "Event not found")
    return ev


@router.get("/")
def home(request: Request, db: Session = Depends(get_session)):
    events = db.scalars(select(Event).where(Event.status.in_(PUBLIC)).order_by(Event.opens_at.desc())).all()
    series = db.scalars(select(Folder).where(Folder.is_series.is_(True)).order_by(Folder.name)).all()
    from .scoring import get_setting

    return render(request, "public/home.html", events=events, series=series,
                  club_name=get_setting(db, "club_name", ""))


@router.get("/events/{event_id}")
def event_home(event_id: str):
    return RedirectResponse(f"/events/{event_id}/results", status_code=303)


@router.get("/events/{event_id}/results")
def results_page(request: Request, event_id: str, db: Session = Depends(get_session)):
    ev = public_event(db, event_id)
    entries, n_ranked = rank_event(db, ev)
    classes = sorted({e.age_class for e in entries if e.age_class})
    return render(request, "public/results.html", ev=ev, entries=entries, n_ranked=n_ranked, classes=classes)


@router.get("/events/{event_id}/tracks")
def tracks_page(request: Request, event_id: str, ids: str = "", db: Session = Depends(get_session)):
    ev = public_event(db, event_id)
    wanted = [i for i in ids.split(",") if i][:12]
    subs = [s for s in (db.get(Submission, i) for i in wanted) if s and s.event_id == ev.id and s.status != "rejected"]
    if not subs:
        return RedirectResponse(f"/events/{event_id}/results", status_code=303)
    return render(request, "public/tracks.html", ev=ev, subs=subs, map_cfg=map_config(ev, subs))


@router.get("/runs/{sub_id}")
def run_detail(request: Request, sub_id: str, db: Session = Depends(get_session)):
    sub = db.get(Submission, sub_id)
    if not sub or sub.status == "rejected" or sub.event.status not in PUBLIC:
        raise HTTPException(404, "Run not found")
    from .views import result_document

    doc = result_document(db, sub)
    return render(request, "public/run.html", sub=sub, ev=sub.event, doc=doc, map_cfg=map_config(sub.event, [sub]))


@router.get("/maps/{event_id}")
def map_image(event_id: str, db: Session = Depends(get_session)):
    ev = db.get(Event, event_id)
    if not ev or not ev.map_image:
        raise HTTPException(404, "No map")
    path = get_settings().maps_dir / ev.map_image
    if not path.exists():
        raise HTTPException(404, "No map")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/series/{folder_id}")
def series_page(request: Request, folder_id: int, db: Session = Depends(get_session)):
    f = db.get(Folder, folder_id)
    if not f or not f.is_series:
        raise HTTPException(404, "Series not found")
    events, rows = series_standings(db, f)
    return render(request, "public/series.html", folder=f, events=events, rows=rows)


@router.get("/events/{event_id}/upload")
def upload_form(request: Request, event_id: str, db: Session = Depends(get_session)):
    ev = public_event(db, event_id)
    if ev.status != "published":
        raise HTTPException(404, "This event is closed.")
    return render(request, "public/upload.html", ev=ev)


@router.post("/events/{event_id}/upload", dependencies=[Depends(check_csrf)])
async def upload_gpx(
    request: Request,
    event_id: str,
    name: str = Form(...),
    club: str = Form(""),
    year_of_birth: str = Form(""),
    consent: bool = Form(False),
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
):
    ev = public_event(db, event_id)
    if ev.status != "published":
        raise HTTPException(404, "This event is closed.")
    err = None
    if not clean_name(name):
        err = "Please enter your name."
    elif not consent:
        err = "Please confirm that your name, result and track will be public."
    data = await file.read()
    if not err and len(data) > get_settings().max_body_bytes:
        err = "The file is larger than 10 MB."
    if not err:
        try:
            points = parse_gpx(data)
        except ImportError_ as e:
            err = str(e)
    if err:
        return render(request, "public/upload.html", 400, ev=ev, error=err,
                      form={"name": name, "club": club, "year_of_birth": year_of_birth})
    participant = {"name": clean_name(name), "club": club.strip(), "year_of_birth": year_of_birth.strip()}
    sub = accept_gpx(db, ev, points, participant)
    return RedirectResponse(f"/runs/{sub.id}", status_code=303)
