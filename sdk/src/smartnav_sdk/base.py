"""Base class for event types (scoring plugins).

A plugin subclasses `EventType`, sets `id` and `name`, and implements
`score()`. Everything else has sensible defaults. Register it in your
package's pyproject.toml:

    [project.entry-points."smartnav.event_types"]
    goat = "my_club_plugins.goat:GoatEvent"
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import detect
from .types import Course, Override, Result, Run, Visit


@dataclass
class Param:
    """Describes one host-only parameter, for the admin form and validation."""

    key: str
    label: str
    kind: str = "int"  # int, bool, points
    default: Any = None
    required: bool = False
    help: str = ""


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class EventType:
    id: str = ""
    name: str = ""
    description: str = ""
    #: Whether the phone must take controls in order.
    ordered: bool = False
    #: Host-only parameters this event type accepts.
    params: list[Param] = []
    #: "time" (lower is better) or "score" (higher is better), used for
    #: default series points.
    series_basis: str = "time"

    # ----- configuration -------------------------------------------------
    def default_params(self) -> dict[str, Any]:
        return {p.key: p.default for p in self.params if p.kind != "points"}

    def validate(self, course: Course, params: dict[str, Any]) -> list[str]:
        """Return a list of problems with the course or parameters.
        An empty list means the event can be published."""
        problems = []
        if not course.controls:
            problems.append("The course has no controls.")
        codes = [c.code for c in course.controls]
        dupes = sorted({c for c in codes if codes.count(c) > 1})
        if dupes:
            problems.append("Duplicate control codes: " + ", ".join(dupes))
        for p in self.params:
            if p.required and params.get(p.key) in (None, ""):
                problems.append(f"{p.label} is required.")
        return problems

    # ----- scoring -------------------------------------------------------
    def start_time(self, run: Run, course: Course) -> datetime:
        return run.started_at

    def detect_visits(
        self, run: Run, course: Course, start_t: datetime, end_t: datetime
    ) -> list[Visit]:
        return detect.detect_visits(run, course, start_t, end_t)

    def detect_finish(self, run: Run, course: Course, start_t: datetime) -> datetime | None:
        return detect.detect_finish(run, course, start_t)

    def evaluate(
        self, run: Run, course: Course, params: dict[str, Any], overrides: list[Override]
    ) -> Result:
        """Full pipeline used by the server: detect, apply overrides, score,
        then flag anything the organiser should look at."""
        start_t = self.start_time(run, course)
        finish_t = self.detect_finish(run, course, start_t)
        end_t = finish_t or run.ended_at
        visits = self.detect_visits(run, course, start_t, end_t)
        visits = detect.apply_overrides(visits, overrides, run, course)
        result = self.score(run, course, params, visits, start_t, finish_t)
        result.finish_t = finish_t
        self._mark_overrides_and_phone_only(result, run, visits, overrides)
        if run.end_reason == "finish_punch" and not detect.finish_is_near_track_end(run, course):
            result.review_reasons.append("Phone finished the run away from the finish circle.")
        return result

    def score(
        self,
        run: Run,
        course: Course,
        params: dict[str, Any],
        visits: list[Visit],
        start_t: datetime,
        finish_t: datetime | None,
    ) -> Result:
        raise NotImplementedError

    def rank_key(self, result: Result) -> tuple | None:
        """Sort key for ranking; None means the run is not ranked."""
        if result.status != "ok" or result.elapsed_s is None:
            return None
        return (result.elapsed_s,)

    def series_points(self, result: Result, winner: Result) -> float:
        """Default series points: 100 for the winner, scaled for others."""
        if self.rank_key(result) is None:
            return 0.0
        if self.series_basis == "score":
            top = winner.score or 0
            return round(100 * (result.score or 0) / top, 1) if top > 0 else 0.0
        if not result.elapsed_s or not winner.elapsed_s:
            return 0.0
        return round(100 * winner.elapsed_s / result.elapsed_s, 1)

    # ----- helpers -------------------------------------------------------
    @staticmethod
    def _mark_overrides_and_phone_only(
        result: Result, run: Run, visits: list[Visit], overrides: list[Override]
    ) -> None:
        decided = {o.code: o.decision for o in overrides}
        for cr in result.controls:
            if cr.code in decided:
                cr.status = decided[cr.code]
        credited = {v.code for v in visits}
        listed = {cr.code for cr in result.controls}
        for pp in run.phone_punches:
            if pp.code in ("S", "F") or pp.code in credited or pp.code in decided:
                continue
            if pp.code not in listed:
                continue
            for cr in result.controls:
                if cr.code == pp.code and cr.status == "missed":
                    cr.status = "phone_only"
                    cr.t = pp.t
            result.review_reasons.append(
                f"Phone beeped at control {pp.code} but the track does not confirm it."
            )

    @staticmethod
    def started_minutes_over(elapsed_s: float, limit_min: float) -> int:
        over = elapsed_s - limit_min * 60
        return max(0, math.ceil(over / 60)) if over > 0 else 0
