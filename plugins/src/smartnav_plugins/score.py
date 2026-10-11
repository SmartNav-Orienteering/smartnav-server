"""Score course: collect as many points as possible within the time limit.

Late penalty: points deducted for each started minute over the limit.
"""
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


class ScoreEvent(EventType):
    id = "score"
    name = "Score course"
    description = (
        "Visit any controls in any order within the time limit. Most points wins; "
        "ties go to the faster time. Late penalties per started minute."
    )
    ordered = False
    series_basis = "score"
    params = [
        Param("points", "Points per control", "points"),
        Param("default_points", "Default points for a control", "int", 10),
        Param("late_penalty_per_minute", "Late penalty per started minute", "int", 10),
        Param(
            "disqualify_after_min",
            "Score is zero this many minutes over the limit (blank = never)",
            "int",
            None,
        ),
        Param("finish_required", "Finish punch required", "bool", True),
    ]

    def validate(self, course: Course, params: dict[str, Any]) -> list[str]:
        problems = super().validate(course, params)
        if not course.time_limit_min:
            problems.append("A score course needs a time limit (typically 60 minutes).")
        codes = {c.code for c in course.controls}
        for code, pts in (params.get("points") or {}).items():
            if code not in codes:
                problems.append(f"Points are set for control {code}, which is not on the course.")
            if not isinstance(pts, int) or pts < 0:
                problems.append(f"Points for control {code} must be a whole number of 0 or more.")
        return problems

    def points_for(self, code: str, params: dict[str, Any]) -> int:
        table = params.get("points") or {}
        if code in table:
            return int(table[code])
        return int(params.get("default_points") or 0)

    def score(
        self,
        run: Run,
        course: Course,
        params: dict[str, Any],
        visits: list[Visit],
        start_t: datetime,
        finish_t: datetime | None,
    ) -> Result:
        first_visit: dict[str, Visit] = {}
        for v in visits:
            first_visit.setdefault(v.code, v)

        controls = []
        gross = 0
        for ctrl in course.controls:
            pts = self.points_for(ctrl.code, params)
            v = first_visit.get(ctrl.code)
            if v:
                gross += pts
                controls.append(
                    ControlResult(ctrl.code, "ok", v.t, round((v.t - start_t).total_seconds(), 1), pts)
                )
            else:
                controls.append(ControlResult(ctrl.code, "missed", points=pts))
        controls.sort(key=lambda c: (c.t is None, c.t or start_t))

        finish_required = params.get("finish_required", True)
        end_t = finish_t or run.ended_at
        elapsed = (end_t - start_t).total_seconds()
        limit = course.time_limit_min or 0
        over_min = self.started_minutes_over(elapsed, limit) if limit else 0
        per_min = int(params.get("late_penalty_per_minute") or 0)
        penalty = over_min * per_min
        net = max(0, gross - penalty)

        lines = [f"{sum(1 for c in controls if c.status == 'ok')} controls, {gross} points"]
        status = "ok"
        if finish_t is None and finish_required:
            status, net = "dnf", 0
            lines.append("Finish not reached: score is zero")
        if over_min:
            lines.append(f"{over_min} min late: −{penalty} points")
            dq = params.get("disqualify_after_min")
            if dq not in (None, "") and over_min > int(dq):
                status, net = "ot", 0
                lines.append(f"More than {dq} min over the limit: score is zero")

        display = f"{net} pts" if status == "ok" else status.upper()
        res = Result(status, elapsed if finish_t else None, display, lines, net, controls)
        res.extra = {"gross": gross, "penalty": penalty, "minutes_late": over_min}
        return res

    def rank_key(self, result: Result) -> tuple | None:
        if result.status != "ok" or result.score is None:
            return None
        return (-result.score, result.elapsed_s or 0)
