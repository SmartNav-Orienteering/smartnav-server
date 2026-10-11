"""Line course: visit every control in order, fastest time wins."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from smartnav_sdk import ControlResult, Course, EventType, Result, Run, Visit, format_duration


class LineEvent(EventType):
    id = "line"
    name = "Line course"
    description = "Visit all controls in the set order. Fastest time wins."
    ordered = True
    params = []
    series_basis = "time"

    def score(
        self,
        run: Run,
        course: Course,
        params: dict[str, Any],
        visits: list[Visit],
        start_t: datetime,
        finish_t: datetime | None,
    ) -> Result:
        controls: list[ControlResult] = []
        prev_t = start_t
        missing = []
        for ctrl in course.controls:
            hit = next((v for v in visits if v.code == ctrl.code and v.t >= prev_t), None)
            if hit is None:
                earlier = any(v.code == ctrl.code for v in visits)
                controls.append(ControlResult(ctrl.code, "out_of_order" if earlier else "missed"))
                missing.append(ctrl.code)
                continue
            controls.append(
                ControlResult(ctrl.code, "ok", hit.t, round((hit.t - prev_t).total_seconds(), 1))
            )
            prev_t = hit.t

        elapsed = (finish_t - start_t).total_seconds() if finish_t else None
        if finish_t is None:
            status, display = "dnf", "DNF"
        elif missing:
            status, display = "mp", "MP"
        else:
            status, display = "ok", format_duration(elapsed)

        if status == "ok" and course.time_limit_min and elapsed > course.time_limit_min * 60:
            status, display = "ot", "OT"

        lines = []
        if status == "ok":
            lines.append(f"All {len(course.controls)} controls visited in order")
            legs = self._legs(controls, start_t, finish_t)
            if legs:
                fastest = min(legs, key=lambda x: x[1])
                lines.append(f"Fastest leg: {fastest[0]} ({format_duration(fastest[1])})")
        elif status == "mp":
            lines.append("Missing or out of order: " + ", ".join(missing))
        elif status == "dnf":
            lines.append("Finish not reached")
        return Result(status, elapsed, display, lines, None, controls)

    @staticmethod
    def _legs(controls, start_t, finish_t):
        legs = []
        prev_code, prev_t = "S", start_t
        for c in controls:
            if c.t is None:
                return []
            legs.append((f"{prev_code} → {c.code}", (c.t - prev_t).total_seconds()))
            prev_code, prev_t = c.code, c.t
        if finish_t:
            legs.append((f"{prev_code} → F", (finish_t - prev_t).total_seconds()))
        return legs
