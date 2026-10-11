"""Default punch detection: find control visits in a GPS track."""
from __future__ import annotations

from datetime import datetime, timedelta

from .geo import closest_on_segment, distance_m
from .types import Control, Course, Override, Run, TrackPoint, Visit

# A runner must move this far beyond the radius before a re-entry counts as
# a new visit. Stops GPS jitter at the circle's edge creating many visits.
HYSTERESIS = 1.5


def usable_points(track: list[TrackPoint], max_accuracy_m: float) -> list[TrackPoint]:
    return [p for p in track if p.acc_m is None or p.acc_m <= max_accuracy_m]


def _interp(a: TrackPoint, b: TrackPoint, f: float) -> datetime:
    return a.t + (b.t - a.t) * f


def entries(points: list[TrackPoint], target: Control, radius_m: float) -> list[Visit]:
    """Every time the track enters the circle around `target`.

    Segments between fixes are checked too, so a runner who passes through
    the circle between two fixes is still credited.
    """
    found: list[Visit] = []
    inside = False
    for i, p in enumerate(points):
        d_here = distance_m(p.lat, p.lon, target.lat, target.lon)
        if i > 0 and not inside:
            prev = points[i - 1]
            d_seg, f = closest_on_segment(
                target.lat, target.lon, prev.lat, prev.lon, p.lat, p.lon
            )
            if d_seg <= radius_m:
                found.append(Visit(target.code, _interp(prev, p, f), round(d_seg, 1)))
                inside = True
        elif i == 0 and d_here <= radius_m:
            found.append(Visit(target.code, p.t, round(d_here, 1)))
            inside = True
        if inside and d_here > radius_m * HYSTERESIS:
            inside = False
    return found


def detect_visits(run: Run, course: Course, start_t: datetime, end_t: datetime) -> list[Visit]:
    """All control visits between start and end, in time order."""
    pts = [p for p in usable_points(run.track, course.max_accuracy_m) if start_t <= p.t <= end_t]
    visits: list[Visit] = []
    for c in course.controls:
        visits.extend(entries(pts, c, course.punch_radius_m))
    visits.sort(key=lambda v: v.t)
    return visits


def detect_finish(run: Run, course: Course, start_t: datetime) -> datetime | None:
    """Finish time, or None if the participant did not reach the finish.

    The phone ends recording at the finish punch or tap, so its end time is
    used. For uploads without a phone finish (e.g. GPX files), the last entry
    into the finish circle is used.
    """
    if run.end_reason in ("finish_punch", "finish_tap"):
        return run.ended_at
    pts = [p for p in usable_points(run.track, course.max_accuracy_m) if p.t >= start_t]
    found = entries(pts, course.finish, course.punch_radius_m)
    # Ignore an "entry" at the very start when start and finish coincide.
    found = [v for v in found if v.t > start_t + timedelta(seconds=30)]
    return found[-1].t if found else None


def finish_is_near_track_end(run: Run, course: Course, tolerance_m: float = 50) -> bool:
    """Sanity check that a phone finish happened at the finish circle."""
    pts = usable_points(run.track, course.max_accuracy_m)
    if not pts:
        return False
    last = pts[-1]
    return distance_m(last.lat, last.lon, course.finish.lat, course.finish.lon) <= (
        course.punch_radius_m + tolerance_m
    )


def closest_approach(run: Run, target: Control) -> tuple[datetime | None, float | None]:
    best_t, best_d = None, None
    pts = run.track
    for i, p in enumerate(pts):
        d = distance_m(p.lat, p.lon, target.lat, target.lon)
        if best_d is None or d < best_d:
            best_t, best_d = p.t, d
        if i > 0:
            d_seg, f = closest_on_segment(
                target.lat, target.lon, pts[i - 1].lat, pts[i - 1].lon, p.lat, p.lon
            )
            if d_seg < best_d:
                best_t, best_d = _interp(pts[i - 1], p, f), d_seg
    return best_t, (round(best_d, 1) if best_d is not None else None)


def apply_overrides(
    visits: list[Visit], overrides: list[Override], run: Run, course: Course
) -> list[Visit]:
    """Apply organiser decisions: denied removes a control's visits,
    accepted adds one (at the phone's punch time, or the closest approach)."""
    out = list(visits)
    for o in overrides:
        if o.decision == "denied":
            out = [v for v in out if v.code != o.code]
        elif o.decision == "accepted" and not any(v.code == o.code for v in out):
            ctrl = course.control(o.code)
            if ctrl is None:
                continue
            phone = [p for p in run.phone_punches if p.code == o.code]
            if phone:
                t, d = phone[0].t, phone[0].distance_m or 0.0
            else:
                t, d = closest_approach(run, ctrl)
            if t is not None:
                out.append(Visit(o.code, t, d or 0.0, source="organiser"))
    out.sort(key=lambda v: v.t)
    return out
