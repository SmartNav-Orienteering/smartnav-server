"""`smartnav demo`: creates a sample series with simulated runs, so you can
try the admin and results pages before setting up a real event."""
from __future__ import annotations

import random
from datetime import timedelta

from smartnav_sdk.testing import walk

from .config import get_settings
from .db import Event, Folder, utcnow
from .packages import course_from_package, publish_version
from .submissions import accept_submission

CONTROLS = [
    {"code": "31", "lat": -35.228810, "lon": 149.085120},
    {"code": "32", "lat": -35.226470, "lon": 149.083400},
    {"code": "33", "lat": -35.229900, "lon": 149.079870},
    {"code": "34", "lat": -35.233640, "lon": 149.077450},
    {"code": "35", "lat": -35.234210, "lon": 149.084020},
]
START = {"code": "S", "lat": -35.231020, "lon": 149.082310, "mode": "punch"}
PEOPLE = [
    ("Anna Smith", "Example OC", 1988), ("Ben Okafor", "Example OC", 1974), ("Chloe Nguyen", "Bushwalkers", 2009),
    ("Dev Patel", "Example OC", 1995), ("Erin Walsh", "Hills OC", 1962), ("Farid Haddad", "Hills OC", 1981),
    ("Grace Liu", "Example OC", 2011), ("Hamish Brown", "Bushwalkers", 1958),
]


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _doc(run, ev, pkg_hash, name, club, yob):
    import uuid

    t0 = run.track[0].t
    rnd = random.Random(name)
    pts = []
    for p in run.track:
        jitter = 0.00002
        pts.append([int((p.t - t0).total_seconds() * 1000), round(p.lat + rnd.uniform(-jitter, jitter), 6),
                    round(p.lon + rnd.uniform(-jitter, jitter), 6), round(rnd.uniform(3, 8), 1), None])
    return {
        "format": "smartnav.submission", "format_version": 1, "submission_id": str(uuid.uuid4()),
        "event_id": ev.id, "package_hash": pkg_hash,
        "participant": {"name": name, "club": club, "year_of_birth": str(yob)},
        "device": {"platform": "android", "app_version": "demo"},
        "activity": {"started_at": _iso(run.started_at), "ended_at": _iso(run.ended_at),
                     "start_method": "punch", "end_reason": run.end_reason},
        "punches": [{"code": p.code, "t": _iso(p.t)} for p in run.phone_punches],
        "track": {"epoch": _iso(t0), "fields": ["dt_ms", "lat", "lon", "acc_m", "alt_m"], "points": pts},
    }


def create_demo(db) -> list[str]:
    base = get_settings().base_url
    folder = Folder(name="Demo Street-O Series", is_series=True,
                    description="Sample events created by `smartnav demo`. Delete them when you are done.")
    db.add(folder)
    db.flush()
    now = utcnow().replace(second=0, microsecond=0)
    made = []
    specs = [
        ("demo-line", "Demo Line Course", "line", {}, None, ["31", "32", "33", "34", "35"]),
        ("demo-score", "Demo Score Course", "score",
         {"points": {"31": 10, "32": 20, "33": 20, "34": 30, "35": 30}, "default_points": 10,
          "late_penalty_per_minute": 10, "disqualify_after_min": 30, "finish_required": True}, 20, None),
        ("demo-scatter", "Demo Scatter Course", "scatter", {"controls_required": 3, "finish_required": True}, None, None),
    ]
    for i, (eid, name, et, params, limit, order) in enumerate(specs):
        if db.get(Event, eid):
            continue
        ev = Event(id=eid, name=name, club="Example OC", folder_id=folder.id, event_type=et, params=params,
                   opens_at=now - timedelta(days=10 - i), closes_at=now + timedelta(days=20),
                   time_limit_min=limit, punch_radius_m=15, start=dict(START), finish={**START, "code": "F"},
                   controls=CONTROLS, status="published")
        db.add(ev)
        db.flush()
        v = publish_version(db, ev, base)
        db.commit()
        course = course_from_package(v.package)
        rnd = random.Random(eid)
        for j, (pname, club, yob) in enumerate(PEOPLE):
            codes = [c["code"] for c in CONTROLS]
            if order:
                route = list(order)
                if j == 5:
                    route.remove("33")  # one mispunch
            else:
                rnd.shuffle(codes)
                route = codes[: rnd.randint(2, 5)]
            run = walk(course, ["S", *route, "F"], speed_mps=rnd.uniform(1.6, 3.4),
                       start=ev.opens_at + timedelta(days=1, hours=j))
            accept_submission(db, ev.id, _doc(run, ev, v.package_hash, pname, club, yob))
        # a repeat run by the first person
        run = walk(course, ["S", *(order or ["31", "32", "35"]), "F"], speed_mps=3.8,
                   start=ev.opens_at + timedelta(days=3))
        accept_submission(db, ev.id, _doc(run, ev, v.package_hash, PEOPLE[0][0], PEOPLE[0][1], PEOPLE[0][2]))
        made.append(eid)
    db.commit()
    return made
