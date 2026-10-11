"""Scatter course: visit a set number of controls in any order, then finish.
Fastest time wins."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from smartnav_sdk import (
    ControlResult,
    Course,
    EventType,
    Param,
    Result,
    Run,
    Visit,
    format_duration,
)


class ScatterEvent(EventType):
    id = "scatter"
    name = "Scatter course"
    description = "Visit the required number of controls in any order, then finish. Fastest time wins."
    ordered = False
    series_basis = "time"
    params = [
        Param("controls_required", "Number of controls required", "int", None, required=True),
        Param("finish_required", "Finish punch required", "bool", True),
    ]

    def validate(self, course: Course, params: dict[str, Any]) -> list[str]:
        problems = super().validate(course, params)
        n = params.get("controls_required")
        if n not in (None, ""):
            try:
                n = int(n)
            except (TypeError, ValueError):
                problems.append("Number of controls required must be a whole number.")
                return problems
            if n < 1 or n > len(course.controls):
                problems.append(
                    f"Number of controls required must be between 1 and {len(course.controls)}."
                )
        return problems

    def score(
        self,
        run: Run,
        course: Course,
        params: dict[str, Any],
        visits: list[Visit],
        start_t: datetime,
        finish_t: datetime | None,
    ) -> Result:
        required = int(params.get("controls_required") or len(course.controls))
        first_visit: dict[str, Visit] = {}
        for v in visits:
            first_visit.setdefault(v.code, v)

        controls = []
        for ctrl in course.controls:
            v = first_visit.get(ctrl.code)
            if v:
                controls.append(
                    ControlResult(ctrl.code, "ok", v.t, round((v.t - start_t).total_seconds(), 1))
                )
            else:
                controls.append(ControlResult(ctrl.code, "missed"))
        controls.sort(key=lambda c: (c.t is None, c.t or start_t))

        n_ok = len(first_visit)
        elapsed = (finish_t - start_t).total_seconds() if finish_t else None
        lines = [f"{n_ok} of {required} required controls visited"]
        if finish_t is None and params.get("finish_required", True):
            status = "dnf"
            lines.append("Finish not reached")
        elif n_ok < required:
            status = "mp"
            lines.append(f"{required - n_ok} more control(s) needed")
        else:
            status = "ok"
        if status == "ok" and course.time_limit_min and elapsed and elapsed > course.time_limit_min * 60:
            status = "ot"
            lines.append("Over the time limit")
        display = format_duration(elapsed) if status == "ok" else status.upper()
        return Result(status, elapsed, display, lines, None, controls)
