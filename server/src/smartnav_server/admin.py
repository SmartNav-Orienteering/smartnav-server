"""Admin site: events, folders and series, imports, review tools, users."""
from __future__ import annotations

import csv
import io
import re
from datetime import timedelta
from urllib.parse import quote

import segno
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import (
    audit,
    check_csrf,
    current_user,
    hash_password,
    owner_required,
    verify_password,
)
from .config import get_settings
from .db import AuditLog, ControlOverride, Event, Folder, Setting, Submission, User, get_session, utcnow
from .importers import ImportError_, parse_kml, parse_kmz
from .maps import map_config
from .packages import build_package, course_from_event, latest_version, publish_version
from .people import DEFAULT_AGE_CLASSES, clean_name, name_key
from .plugins import get_event_type, registry
from .scoring import get_setting, rank_event, rescore_event, score_submission
from .web import flash, parse_local, render

router = APIRouter(prefix="/admin")

TIMEZONES = [
    "Australia/Sydney", "Australia/Melbourne", "Australia/Brisbane", "Australia/Adelaide",
    "Australia/Darwin", "Australia/Perth", "Australia/Hobart", "Pacific/Auckland", "Europe/London", "UTC",
]


def back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def get_event(db: Session, event_id: str) -> Event:
    ev = db.get(Event, event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    return ev


# ------------------------------------------------------------------ login
@router.get("/login")
def login_form(request: Request, next: str = "/admin", db: Session = Depends(get_session)):
    first_run = db.scalar(select(func.count(User.id))) == 0
    return render(request, "admin/login.html", next=next, first_run=first_run)


@router.post("/login", dependencies=[Depends(check_csrf)])
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/admin"),
    db: Session = Depends(get_session),
):
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if not user or not user.active or not verify_password(password, user.password_hash):
        return render(request, "admin/login.html", 401, next=next, error="Email or password is not correct.",
                      first_run=False)
    request.session["uid"] = user.id
    if not next.startswith("/admin"):
        next = "/admin"
    return back(next)


@router.post("/setup", dependencies=[Depends(check_csrf)])
def first_owner(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    """Creates the owner account when the server has no users yet."""
    if db.scalar(select(func.count(User.id))) > 0:
        raise HTTPException(403, "Setup has already been done.")
    if len(password) < 10:
        return render(request, "admin/login.html", 400, next="/admin", first_run=True,
                      error="Please use a password of at least 10 characters.")
    u = User(name=name.strip(), email=email.strip().lower(), password_hash=hash_password(password), role="owner")
    db.add(u)
    db.flush()
    audit(db, u, "create owner", u.email)
    db.commit()
    request.session["uid"] = u.id
    return back("/admin")


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return back("/admin/login")


# ------------------------------------------------------------- dashboard
def folder_tree(db: Session) -> tuple[list[Folder], list[Event]]:
    roots = db.scalars(select(Folder).where(Folder.parent_id.is_(None)).order_by(Folder.name)).all()
    loose = db.scalars(select(Event).where(Event.folder_id.is_(None)).order_by(Event.opens_at.desc())).all()
    return list(roots), list(loose)


@router.get("")
def dashboard(request: Request, user: User = Depends(current_user), db: Session = Depends(get_session)):
    roots, loose = folder_tree(db)
    review_count = db.scalar(select(func.count(Submission.id)).where(Submission.status == "needs_review"))
    return render(request, "admin/dashboard.html", roots=roots, loose=loose, review_count=review_count)


# --------------------------------------------------------------- folders
def all_folders(db: Session) -> list[tuple[Folder, str]]:
    out = []

    def walk(f: Folder, prefix: str):
        label = f"{prefix}{f.name}"
        out.append((f, label))
        for c in sorted(f.children, key=lambda x: x.name):
            walk(c, label + " / ")

    for r in db.scalars(select(Folder).where(Folder.parent_id.is_(None)).order_by(Folder.name)):
        walk(r, "")
    return out


@router.get("/folders/new")
def folder_new(request: Request, parent: int | None = None, user: User = Depends(current_user),
               db: Session = Depends(get_session)):
    return render(request, "admin/folder_form.html", folder=None, parent_id=parent, folders=all_folders(db))


@router.post("/folders/new", dependencies=[Depends(check_csrf)])
def folder_create(
    request: Request,
    name: str = Form(...),
    parent_id: str = Form(""),
    is_series: bool = Form(False),
    description: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    f = Folder(name=name.strip(), parent_id=int(parent_id) if parent_id else None, is_series=is_series,
               description=description.strip())
    db.add(f)
    db.flush()
    audit(db, user, "create folder", f.name)
    db.commit()
    flash(request, f"Folder “{f.name}” created.")
    return back("/admin")


@router.get("/folders/{folder_id}")
def folder_edit(request: Request, folder_id: int, user: User = Depends(current_user),
                db: Session = Depends(get_session)):
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(404, "Folder not found")
    choices = [(x, label) for x, label in all_folders(db) if not _is_descendant(x, f)]
    return render(request, "admin/folder_form.html", folder=f, parent_id=f.parent_id, folders=choices)


def _is_descendant(candidate: Folder, f: Folder) -> bool:
    x = candidate
    while x is not None:
        if x.id == f.id:
            return True
        x = x.parent
    return False


@router.post("/folders/{folder_id}", dependencies=[Depends(check_csrf)])
def folder_update(
    request: Request,
    folder_id: int,
    name: str = Form(...),
    parent_id: str = Form(""),
    is_series: bool = Form(False),
    description: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(404, "Folder not found")
    f.name, f.is_series, f.description = name.strip(), is_series, description.strip()
    new_parent = db.get(Folder, int(parent_id)) if parent_id else None
    if new_parent is None or not _is_descendant(new_parent, f):
        f.parent_id = new_parent.id if new_parent else None
    audit(db, user, "edit folder", f.name)
    db.commit()
    flash(request, "Folder saved.")
    return back("/admin")


@router.post("/folders/{folder_id}/delete", dependencies=[Depends(check_csrf)])
def folder_delete(request: Request, folder_id: int, user: User = Depends(current_user),
                  db: Session = Depends(get_session)):
    f = db.get(Folder, folder_id)
    if not f:
        raise HTTPException(404, "Folder not found")
    if f.children or f.events:
        flash(request, "Only empty folders can be deleted. Move its events and sub-folders first.", "error")
        return back(f"/admin/folders/{folder_id}")
    audit(db, user, "delete folder", f.name)
    db.delete(f)
    db.commit()
    flash(request, "Folder deleted.")
    return back("/admin")


# ---------------------------------------------------------------- events
def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:70] or "event"


@router.get("/events/new")
def event_new(request: Request, folder: int | None = None, user: User = Depends(current_user),
              db: Session = Depends(get_session)):
    return render(request, "admin/event_new.html", folders=all_folders(db), folder_id=folder,
                  types=registry(), club=get_setting(db, "club_name", ""))


@router.post("/events/new", dependencies=[Depends(check_csrf)])
def event_create(
    request: Request,
    name: str = Form(...),
    event_id: str = Form(""),
    event_type: str = Form(...),
    folder_id: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    eid = slugify(event_id or name)
    if db.get(Event, eid):
        base, n = eid, 2
        while db.get(Event, f"{base}-{n}"):
            n += 1
        eid = f"{base}-{n}"
    et = get_event_type(event_type)
    if et is None:
        raise HTTPException(400, "Unknown event type")
    now = utcnow().replace(second=0, microsecond=0)
    ev = Event(
        id=eid,
        name=name.strip(),
        club=get_setting(db, "club_name", ""),
        folder_id=int(folder_id) if folder_id else None,
        event_type=event_type,
        params=et.default_params(),
        opens_at=now,
        closes_at=now + timedelta(days=7),
        timezone=get_setting(db, "timezone", "Australia/Sydney"),
        punch_radius_m=float(get_setting(db, "default_radius_m", 15)),
        time_limit_min=60 if event_type == "score" else None,
        alerts=[{"before_limit_min": 10, "sound": "double"}, {"before_limit_min": 2, "sound": "long"}]
        if event_type == "score" else [],
    )
    db.add(ev)
    audit(db, user, "create event", eid)
    db.commit()
    flash(request, "Event created. Next, import the controls from a KML file.")
    return back(f"/admin/events/{eid}")


@router.get("/events/{event_id}")
def event_page(request: Request, event_id: str, user: User = Depends(current_user),
               db: Session = Depends(get_session)):
    ev = get_event(db, event_id)
    et = get_event_type(ev.event_type)
    problems = _problems(ev)
    latest = latest_version(ev)
    current_hash = build_package(ev, get_settings().base_url)["package_hash"] if ev.start else None
    unpublished_changes = ev.status == "published" and latest is not None and (
        latest.package_hash != current_hash or latest.params != (ev.params or {})
    )
    counts = {
        "runs": len(ev.submissions),
        "review": sum(1 for s in ev.submissions if s.status == "needs_review"),
    }
    join = join_link(ev)
    points = (ev.params or {}).get("points", {}) if ev.event_type == "score" else None
    return render(
        request,
        "admin/event.html",
        ev=ev,
        et=et,
        types=registry(),
        folders=all_folders(db),
        timezones=TIMEZONES,
        problems=problems,
        latest=latest,
        unpublished_changes=unpublished_changes,
        counts=counts,
        join=join,
        qr_svg=segno.make(join, error="m").svg_inline(scale=4, dark="#111"),
        map_cfg=map_config(ev, show_points=points),
    )


def join_link(ev: Event) -> str:
    base = get_settings().base_url
    return f"smartnav://join?server={quote(base, safe=':/')}&event={quote(ev.id)}"


def _problems(ev: Event) -> list[str]:
    problems = []
    if not ev.start:
        problems.append("The course has no start. Include a placemark named S or Start in the KML file.")
    if not ev.controls:
        problems.append("The course has no controls.")
    if ev.closes_at <= ev.opens_at:
        problems.append("The event closes before it opens.")
    et = get_event_type(ev.event_type)
    if et is None:
        problems.append(f"The event type {ev.event_type!r} is not installed.")
    elif ev.start and ev.controls:
        problems += et.validate(course_from_event(ev, get_settings().base_url), ev.params or {})
    return problems


@router.post("/events/{event_id}/details", dependencies=[Depends(check_csrf)])
def event_details(
    request: Request,
    event_id: str,
    name: str = Form(...),
    club: str = Form(""),
    folder_id: str = Form(""),
    event_type: str = Form(...),
    timezone_: str = Form(..., alias="timezone"),
    opens_at: str = Form(...),
    closes_at: str = Form(...),
    info_url: str = Form(""),
    time_limit_min: str = Form(""),
    punch_radius_m: float = Form(15),
    start_mode: str = Form("punch"),
    finish_mode: str = Form("punch"),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    ev = get_event(db, event_id)
    ev.name, ev.club, ev.info_url = name.strip(), club.strip(), info_url.strip()
    ev.folder_id = int(folder_id) if folder_id else None
    if event_type != ev.event_type and get_event_type(event_type):
        ev.event_type = event_type
        ev.params = {**get_event_type(event_type).default_params(), **{k: v for k, v in (ev.params or {}).items() if k == "points"}}
    ev.timezone = timezone_
    try:
        ev.opens_at, ev.closes_at = parse_local(opens_at, timezone_), parse_local(closes_at, timezone_)
    except ValueError:
        flash(request, "Please enter valid opening and closing times.", "error")
        return back(f"/admin/events/{event_id}")
    ev.time_limit_min = float(time_limit_min) if time_limit_min.strip() else None
    ev.punch_radius_m = max(3.0, min(100.0, punch_radius_m))
    if ev.start:
        ev.start = {**ev.start, "mode": start_mode}
    if ev.finish or ev.start:
        ev.finish = {**(ev.finish or {**ev.start, "code": "F"}), "mode": finish_mode}
    audit(db, user, "edit event", ev.id)
    db.commit()
    flash(request, "Event details saved.")
    return back(f"/admin/events/{event_id}#details")


@router.post("/events/{event_id}/import", dependencies=[Depends(check_csrf)])
async def event_import(
    request: Request,
    event_id: str,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    ev = get_event(db, event_id)
    data = await file.read()
    try:
        if (file.filename or "").lower().endswith(".kmz"):
            kmz = parse_kmz(data) if _has_overlay(data) else None
            if kmz:
                _save_map(ev, kmz)
                course = kmz.course
            else:
                import zipfile

                zf = zipfile.ZipFile(io.BytesIO(data))
                name = next(n for n in zf.namelist() if n.lower().endswith(".kml"))
                course = parse_kml(zf.read(name))
        else:
            course = parse_kml(data)
    except (ImportError_, StopIteration, Exception) as e:
        flash(request, f"Import failed: {e}", "error")
        return back(f"/admin/events/{event_id}#course")
    msg = []
    if course and course.controls:
        ev.controls = course.controls
        msg.append(f"{len(course.controls)} controls imported")
    if course and course.start:
        ev.start = {**course.start, "mode": (ev.start or {}).get("mode", "punch")}
        msg.append("start")
    if course and course.finish:
        ev.finish = {**course.finish, "mode": (ev.finish or {}).get("mode", "punch")}
        msg.append("finish")
    elif course and course.start and not ev.finish:
        ev.finish = {**course.start, "code": "F", "mode": "punch"}
        msg.append("finish set at the start")
    if ev.map_image and (file.filename or "").lower().endswith(".kmz"):
        msg.append("map image")
    if course and course.skipped:
        msg.append("skipped (no point): " + ", ".join(course.skipped[:10]))
    audit(db, user, "import course", ev.id, file.filename or "")
    db.commit()
    flash(request, "Imported: " + "; ".join(msg) if msg else "Nothing was imported.")
    return back(f"/admin/events/{event_id}#course")


def _has_overlay(data: bytes) -> bool:
    import zipfile

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        return any(b"GroundOverlay" in zf.read(n) for n in zf.namelist() if n.lower().endswith(".kml"))
    except Exception:
        return False


def _save_map(ev: Event, kmz) -> None:
    folder = get_settings().maps_dir
    for old in folder.glob(f"{ev.id}.*"):
        old.unlink()
    path = folder / f"{ev.id}.{kmz.ext}"
    path.write_bytes(kmz.image)
    ev.map_image = path.name
    ev.map_bounds = kmz.bounds
    ev.updated_at = utcnow()


@router.post("/events/{event_id}/map", dependencies=[Depends(check_csrf)])
async def event_map(
    request: Request,
    event_id: str,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    ev = get_event(db, event_id)
    try:
        kmz = parse_kmz(await file.read())
    except ImportError_ as e:
        flash(request, f"Map import failed: {e}", "error")
        return back(f"/admin/events/{event_id}#map-card")
    _save_map(ev, kmz)
    note = " The map is rotated in the KMZ; it is shown unrotated, so check its alignment." if kmz.bounds.get("rotation") else ""
    audit(db, user, "import map", ev.id, file.filename or "")
    db.commit()
    flash(request, "Map image imported." + note)
    return back(f"/admin/events/{event_id}#map-card")


@router.post("/events/{event_id}/map/delete", dependencies=[Depends(check_csrf)])
def event_map_delete(request: Request, event_id: str, user: User = Depends(current_user),
                     db: Session = Depends(get_session)):
    ev = get_event(db, event_id)
    for old in get_settings().maps_dir.glob(f"{ev.id}.*"):
        old.unlink()
    ev.map_image, ev.map_bounds = None, None
    db.commit()
    flash(request, "Map image removed.")
    return back(f"/admin/events/{event_id}#map-card")


@router.post("/events/{event_id}/scoring", dependencies=[Depends(check_csrf)])
async def event_scoring(request: Request, event_id: str, user: User = Depends(current_user),
                        db: Session = Depends(get_session)):
    ev = get_event(db, event_id)
    et = get_event_type(ev.event_type)
    form = await request.form()
    params = dict(ev.params or {})
    errors = []
    for p in et.params if et else []:
        if p.kind == "points":
            pts = {}
            for c in ev.controls:
                raw = str(form.get(f"points_{c['code']}", "")).strip()
                if raw:
                    try:
                        pts[c["code"]] = int(raw)
                    except ValueError:
                        errors.append(f"Points for {c['code']} must be a whole number.")
            params["points"] = pts
        elif p.kind == "bool":
            params[p.key] = form.get(p.key) == "on"
        else:
            raw = str(form.get(p.key, "")).strip()
            if raw == "":
                params[p.key] = None
            else:
                try:
                    params[p.key] = int(raw)
                except ValueError:
                    errors.append(f"{p.label} must be a whole number.")
    if errors:
        flash(request, " ".join(errors), "error")
        return back(f"/admin/events/{event_id}#scoring")
    ev.params = params
    audit(db, user, "edit scoring", ev.id)
    db.commit()
    flash(request, "Scoring settings saved.")
    return back(f"/admin/events/{event_id}#scoring")


@router.post("/events/{event_id}/publish", dependencies=[Depends(check_csrf)])
def event_publish(request: Request, event_id: str, user: User = Depends(current_user),
                  db: Session = Depends(get_session)):
    ev = get_event(db, event_id)
    problems = _problems(ev)
    if problems:
        flash(request, "Not published: " + " ".join(problems), "error")
        return back(f"/admin/events/{event_id}")
    was = ev.status
    v = publish_version(db, ev, get_settings().base_url)
    ev.status = "published"
    rescored = rescore_event(db, ev) if was == "published" else 0
    audit(db, user, "publish event", ev.id, v.package_hash)
    db.commit()
    flash(request, "Event published." + (f" {rescored} run(s) rescored." if rescored else ""))
    return back(f"/admin/events/{event_id}")


@router.post("/events/{event_id}/status", dependencies=[Depends(check_csrf)])
def event_status(request: Request, event_id: str, status: str = Form(...), user: User = Depends(current_user),
                 db: Session = Depends(get_session)):
    ev = get_event(db, event_id)
    if status not in ("draft", "archived", "published"):
        raise HTTPException(400, "Bad status")
    if status == "published" and not ev.versions:
        return event_publish(request, event_id, user, db)
    ev.status = status
    audit(db, user, f"set event {status}", ev.id)
    db.commit()
    labels = {"draft": "Event unpublished: hidden from the app and results.",
              "archived": "Event archived: results stay visible, new runs are refused.",
              "published": "Event re-opened."}
    flash(request, labels[status])
    return back(f"/admin/events/{event_id}")


@router.post("/events/{event_id}/delete", dependencies=[Depends(check_csrf)])
def event_delete(request: Request, event_id: str, confirm: str = Form(""), user: User = Depends(current_user),
                 db: Session = Depends(get_session)):
    ev = get_event(db, event_id)
    if confirm.strip() != ev.id:
        flash(request, "To delete, type the event ID exactly.", "error")
        return back(f"/admin/events/{event_id}#danger")
    import shutil

    shutil.rmtree(get_settings().submissions_dir / ev.id, ignore_errors=True)
    for old in get_settings().maps_dir.glob(f"{ev.id}.*"):
        old.unlink()
    audit(db, user, "delete event", ev.id, f"{len(ev.submissions)} runs")
    db.delete(ev)
    db.commit()
    flash(request, f"Event {event_id} deleted.")
    return back("/admin")


@router.get("/events/{event_id}/qr.svg")
def event_qr(event_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)):
    ev = get_event(db, event_id)
    buf = io.BytesIO()
    segno.make(join_link(ev), error="m").save(buf, kind="svg", scale=10, border=2)
    return Response(buf.getvalue(), media_type="image/svg+xml",
                    headers={"Content-Disposition": f'inline; filename="{ev.id}-qr.svg"'})


@router.get("/events/{event_id}/print")
def event_print(request: Request, event_id: str, user: User = Depends(current_user),
                db: Session = Depends(get_session)):
    ev = get_event(db, event_id)
    return render(request, "admin/print_qr.html", ev=ev, join=join_link(ev),
                  qr_svg=segno.make(join_link(ev), error="m").svg_inline(scale=8, dark="#000"))


# ------------------------------------------------------------------ runs
@router.get("/events/{event_id}/runs")
def event_runs(request: Request, event_id: str, show: str = "all", user: User = Depends(current_user),
               db: Session = Depends(get_session)):
    ev = get_event(db, event_id)
    entries, n_ranked = rank_event(db, ev)
    flat = []
    for e in entries:
        flat.append(e)
        flat.extend(e.repeats)
    if show == "review":
        flat = [e for e in flat if e.sub.status == "needs_review"]
    return render(request, "admin/runs.html", ev=ev, entries=flat, show=show, n_ranked=n_ranked)


@router.post("/events/{event_id}/rescore", dependencies=[Depends(check_csrf)])
def event_rescore(request: Request, event_id: str, user: User = Depends(current_user),
                  db: Session = Depends(get_session)):
    ev = get_event(db, event_id)
    n = rescore_event(db, ev)
    audit(db, user, "rescore event", ev.id, f"{n} runs")
    db.commit()
    flash(request, f"{n} run(s) rescored.")
    return back(f"/admin/events/{event_id}/runs")


@router.get("/events/{event_id}/export.csv")
def event_export(event_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)):
    ev = get_event(db, event_id)
    entries, _ = rank_event(db, ev)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Position", "Class position", "Name", "Club", "Class", "Status", "Result", "Time (s)",
                "Score", "Run", "Started (local)", "Provisional", "Submission ID"])
    from .web import local

    for e in entries:
        for x in [e, *e.repeats]:
            r = x.result or {}
            w.writerow([
                x.position if x is e and x.ranked else "",
                x.class_position if x is e and x.ranked else "",
                x.name, x.club, x.age_class, r.get("status", ""), r.get("display", ""),
                r.get("elapsed_s") if r.get("elapsed_s") is not None else "",
                r.get("score") if r.get("score") is not None else "",
                x.run_number, local(x.sub.started_at, ev.timezone, "%Y-%m-%d %H:%M:%S"),
                "yes" if x.sub.status == "needs_review" else "", x.sub.id,
            ])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{ev.id}-results.csv"'})


@router.get("/review")
def review_queue(request: Request, user: User = Depends(current_user), db: Session = Depends(get_session)):
    subs = db.scalars(
        select(Submission).where(Submission.status == "needs_review").order_by(Submission.received_at)
    ).all()
    return render(request, "admin/review.html", subs=subs)


@router.get("/runs/{sub_id}")
def run_page(request: Request, sub_id: str, user: User = Depends(current_user), db: Session = Depends(get_session)):
    sub = db.get(Submission, sub_id)
    if not sub:
        raise HTTPException(404, "Run not found")
    ev = sub.event
    overrides = {o.code: o for o in sub.overrides}
    history = db.scalars(
        select(AuditLog).where(AuditLog.target == sub.id).order_by(AuditLog.at.desc())
    ).all()
    others = db.scalars(
        select(Submission).where(Submission.event_id == ev.id, Submission.name_key == sub.name_key,
                                 Submission.id != sub.id).order_by(Submission.started_at)
    ).all()
    return render(request, "admin/run.html", sub=sub, ev=ev, overrides=overrides, history=history,
                  others=others, map_cfg=map_config(ev, [sub]))


def _get_sub(db, sub_id) -> Submission:
    sub = db.get(Submission, sub_id)
    if not sub:
        raise HTTPException(404, "Run not found")
    return sub


@router.post("/runs/{sub_id}/control", dependencies=[Depends(check_csrf)])
def run_control(
    request: Request,
    sub_id: str,
    code: str = Form(...),
    decision: str = Form(...),
    reason: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    sub = _get_sub(db, sub_id)
    if decision not in ("accepted", "denied", "clear"):
        raise HTTPException(400, "Bad decision")
    for o in list(sub.overrides):
        if o.code == code:
            sub.overrides.remove(o)
    if decision != "clear":
        sub.overrides.append(ControlOverride(code=code, decision=decision, reason=reason.strip(), user_id=user.id))
    db.flush()
    score_submission(db, sub)
    audit(db, user, f"control {code} {decision}", sub.id, reason.strip())
    db.commit()
    flash(request, f"Control {code}: {'decision cleared' if decision == 'clear' else decision}. Run rescored.")
    return back(f"/admin/runs/{sub_id}")


@router.post("/runs/{sub_id}/rename", dependencies=[Depends(check_csrf)])
def run_rename(
    request: Request,
    sub_id: str,
    name: str = Form(...),
    all_runs: bool = Form(False),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    sub = _get_sub(db, sub_id)
    new = clean_name(name)
    if not new:
        flash(request, "The name cannot be empty.", "error")
        return back(f"/admin/runs/{sub_id}")
    targets = [sub]
    if all_runs:
        targets = db.scalars(select(Submission).where(Submission.name_key == sub.name_key)).all()
    for s in targets:
        old = s.participant_name
        s.participant_name = new
        s.name_key = name_key(new)
        s.participant = {**(s.participant or {}), "name": new}
        audit(db, user, "rename participant", s.id, f"{old} → {new}")
    db.commit()
    flash(request, f"Name changed to “{new}” on {len(targets)} run(s). Rankings and series standings now use it.")
    return back(f"/admin/runs/{sub_id}")


@router.post("/runs/{sub_id}/dsq", dependencies=[Depends(check_csrf)])
def run_dsq(
    request: Request,
    sub_id: str,
    action: str = Form(...),
    reason: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    sub = _get_sub(db, sub_id)
    sub.disqualified = action == "dsq"
    sub.dsq_reason = reason.strip() if sub.disqualified else ""
    score_submission(db, sub)
    audit(db, user, "disqualify" if sub.disqualified else "reinstate", sub.id, reason.strip())
    db.commit()
    flash(request, "Run disqualified." if sub.disqualified else "Disqualification removed.")
    return back(f"/admin/runs/{sub_id}")


@router.post("/runs/{sub_id}/reviewed", dependencies=[Depends(check_csrf)])
def run_reviewed(request: Request, sub_id: str, user: User = Depends(current_user),
                 db: Session = Depends(get_session)):
    sub = _get_sub(db, sub_id)
    sub.reviewed = True
    score_submission(db, sub)
    audit(db, user, "mark reviewed", sub.id)
    db.commit()
    flash(request, "Marked as reviewed: the result is no longer provisional.")
    nxt = db.scalar(select(Submission).where(Submission.status == "needs_review",
                                             Submission.event_id == sub.event_id))
    return back(f"/admin/runs/{nxt.id}" if nxt else f"/admin/events/{sub.event_id}/runs")


@router.post("/runs/{sub_id}/delete", dependencies=[Depends(check_csrf)])
def run_delete(request: Request, sub_id: str, user: User = Depends(owner_required),
               db: Session = Depends(get_session)):
    sub = _get_sub(db, sub_id)
    ev_id = sub.event_id
    from pathlib import Path

    Path(sub.raw_path).unlink(missing_ok=True)
    audit(db, user, "delete run", sub.id, sub.participant_name)
    db.delete(sub)
    db.commit()
    flash(request, "Run deleted.")
    return back(f"/admin/events/{ev_id}/runs")


# ----------------------------------------------------------------- users
@router.get("/users")
def users_page(request: Request, user: User = Depends(owner_required), db: Session = Depends(get_session)):
    users = db.scalars(select(User).order_by(User.role.desc(), User.name)).all()
    return render(request, "admin/users.html", users=users)


@router.post("/users", dependencies=[Depends(check_csrf)])
def users_add(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("delegate"),
    user: User = Depends(owner_required),
    db: Session = Depends(get_session),
):
    email = email.strip().lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        flash(request, "A user with that email already exists.", "error")
        return back("/admin/users")
    if len(password) < 10:
        flash(request, "Please use a password of at least 10 characters.", "error")
        return back("/admin/users")
    u = User(name=name.strip(), email=email, password_hash=hash_password(password),
             role="owner" if role == "owner" else "delegate")
    db.add(u)
    audit(db, user, "add user", email, u.role)
    db.commit()
    flash(request, f"{u.name} added as {u.role}. Give them their password in person or by phone.")
    return back("/admin/users")


@router.post("/users/{uid}", dependencies=[Depends(check_csrf)])
def users_edit(
    request: Request,
    uid: int,
    action: str = Form(...),
    password: str = Form(""),
    user: User = Depends(owner_required),
    db: Session = Depends(get_session),
):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    if action == "password":
        if len(password) < 10:
            flash(request, "Please use a password of at least 10 characters.", "error")
            return back("/admin/users")
        u.password_hash = hash_password(password)
        msg = f"Password changed for {u.name}."
    elif action in ("deactivate", "activate"):
        if u.id == user.id:
            flash(request, "You cannot deactivate yourself.", "error")
            return back("/admin/users")
        u.active = action == "activate"
        msg = f"{u.name} {'re-activated' if u.active else 'deactivated'}."
    else:
        raise HTTPException(400, "Bad action")
    audit(db, user, f"user {action}", u.email)
    db.commit()
    flash(request, msg)
    return back("/admin/users")


@router.get("/account")
def account_page(request: Request, user: User = Depends(current_user)):
    return render(request, "admin/account.html")


@router.post("/account", dependencies=[Depends(check_csrf)])
def account_password(
    request: Request,
    current: str = Form(...),
    password: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    if not verify_password(current, user.password_hash):
        flash(request, "Your current password is not correct.", "error")
    elif len(password) < 10:
        flash(request, "Please use a password of at least 10 characters.", "error")
    else:
        u = db.get(User, user.id)
        u.password_hash = hash_password(password)
        audit(db, u, "change own password", u.email)
        db.commit()
        flash(request, "Password changed.")
    return back("/admin/account")


# -------------------------------------------------------------- settings
def classes_to_text(classes: list[dict]) -> str:
    lines = []
    for c in classes:
        lo = c.get("min_age")
        hi = c.get("max_age")
        lines.append(f"{c['name']}, {'' if lo is None else lo}, {'' if hi is None else hi}")
    return "\n".join(lines)


def text_to_classes(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        while len(parts) < 3:
            parts.append("")
        c = {"name": parts[0]}
        if parts[1]:
            c["min_age"] = int(parts[1])
        if parts[2]:
            c["max_age"] = int(parts[2])
        out.append(c)
    return out


@router.get("/settings")
def settings_page(request: Request, user: User = Depends(owner_required), db: Session = Depends(get_session)):
    return render(
        request,
        "admin/settings.html",
        club_name=get_setting(db, "club_name", ""),
        timezone=get_setting(db, "timezone", "Australia/Sydney"),
        timezones=TIMEZONES,
        default_radius=get_setting(db, "default_radius_m", 15),
        classes_text=classes_to_text(get_setting(db, "age_classes", DEFAULT_AGE_CLASSES)),
        plugins=registry(),
    )


@router.post("/settings", dependencies=[Depends(check_csrf)])
def settings_save(
    request: Request,
    club_name: str = Form(""),
    timezone_: str = Form("Australia/Sydney", alias="timezone"),
    default_radius: float = Form(15),
    classes: str = Form(""),
    user: User = Depends(owner_required),
    db: Session = Depends(get_session),
):
    try:
        parsed = text_to_classes(classes)
    except ValueError:
        flash(request, "Age classes: each line should be Name, minimum age, maximum age (ages are whole numbers).", "error")
        return back("/admin/settings")
    for key, value in (("club_name", club_name.strip()), ("timezone", timezone_),
                       ("default_radius_m", default_radius), ("age_classes", parsed)):
        s = db.get(Setting, key)
        if s:
            s.value = value
        else:
            db.add(Setting(key=key, value=value))
    audit(db, user, "edit settings")
    db.commit()
    flash(request, "Settings saved.")
    return back("/admin/settings")


@router.get("/audit")
def audit_page(request: Request, user: User = Depends(owner_required), db: Session = Depends(get_session)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(500)).all()
    return render(request, "admin/audit.html", rows=rows)
