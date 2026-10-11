"""Helpers for testing plugins without a phone or a server.

    from smartnav_sdk.testing import course, walk
    run = walk(c, ["S", "31", "32", "F"], speed_mps=3)
    result = MyEvent().evaluate(run, c, params, [])
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

from .geo import distance_m
from .types import Control, Course, PhonePunch, Run, TrackPoint

T0 = datetime(2026, 10, 4, 0, 0, 0, tzinfo=timezone.utc)


def course(
    event_type: str,
    controls: dict[str, tuple[float, float]],
    start: tuple[float, float],
    finish: tuple[float, float] | None = None,
    ordered: bool = False,
    radius: float = 15,
    time_limit_min: float | None = None,
) -> Course:
    return Course(
        event_type=event_type,
        ordered=ordered,
        controls=[Control(k, *v) for k, v in controls.items()],
        start=Control("S", *start),
        finish=Control("F", *(finish or start)),
        punch_radius_m=radius,
        time_limit_min=time_limit_min,
    )


def walk(
    c: Course,
    route: list[str],
    speed_mps: float = 3.0,
    interval_s: float = 1.0,
    start: datetime = T0,
    phone_punches: bool = True,
    end_reason: str = "finish_punch",
    pause_s: float = 0.0,
) -> Run:
    """Simulate a runner going in straight lines between the named points.

    `route` uses "S" and "F" for start and finish and control codes otherwise.
    """
    pts_by_code = {"S": c.start, "F": c.finish, **{x.code: x for x in c.controls}}
    waypoints = [pts_by_code[r] for r in route]
    track: list[TrackPoint] = []
    punches: list[PhonePunch] = []
    t = start
    for i, wp in enumerate(waypoints):
        if i == 0:
            track.append(TrackPoint(t, wp.lat, wp.lon, 4.0))
            continue
        a = waypoints[i - 1]
        d = distance_m(a.lat, a.lon, wp.lat, wp.lon)
        steps = max(1, math.ceil(d / (speed_mps * interval_s)))
        for s in range(1, steps + 1):
            f = s / steps
            t = t + timedelta(seconds=interval_s)
            track.append(TrackPoint(t, a.lat + (wp.lat - a.lat) * f, a.lon + (wp.lon - a.lon) * f, 4.0))
        if phone_punches and route[i] not in ("S", "F"):
            punches.append(PhonePunch(route[i], t, wp.lat, wp.lon, 4.0, 0.0))
        if pause_s:
            t = t + timedelta(seconds=pause_s)
            track.append(TrackPoint(t, wp.lat, wp.lon, 4.0))
    return Run(
        submission_id=str(uuid.uuid4()),
        started_at=start,
        ended_at=t,
        start_method=c.start_mode,
        end_reason=end_reason,
        track=track,
        phone_punches=punches,
    )
