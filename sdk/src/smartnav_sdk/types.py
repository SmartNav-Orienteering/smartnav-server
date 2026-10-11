"""Data types shared by the SmartNav server and event-type plugins.

Plugins receive these objects and return a `Result`. They never touch the
database, HTTP requests or files, which keeps them easy to test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Control:
    code: str
    lat: float
    lon: float


@dataclass
class Course:
    """The course as the participant ran it (one published package version)."""

    event_type: str
    ordered: bool
    controls: list[Control]
    start: Control
    finish: Control
    punch_radius_m: float = 15.0
    start_mode: str = "punch"  # "punch" or "tap"
    finish_mode: str = "punch"  # "punch" or "tap"
    time_limit_min: float | None = None
    max_accuracy_m: float = 25.0

    def control(self, code: str) -> Control | None:
        for c in self.controls:
            if c.code == code:
                return c
        return None


@dataclass(frozen=True)
class TrackPoint:
    t: datetime
    lat: float
    lon: float
    acc_m: float | None = None
    alt_m: float | None = None


@dataclass(frozen=True)
class PhonePunch:
    """A punch the phone detected (and beeped for). Evidence only."""

    code: str
    t: datetime
    lat: float | None = None
    lon: float | None = None
    accuracy_m: float | None = None
    distance_m: float | None = None


@dataclass
class Run:
    """One participant's attempt, as submitted."""

    submission_id: str
    started_at: datetime
    ended_at: datetime
    start_method: str
    end_reason: str
    track: list[TrackPoint]
    phone_punches: list[PhonePunch] = field(default_factory=list)
    participant: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Visit:
    """A control visit detected by the server from the track."""

    code: str
    t: datetime
    distance_m: float
    source: str = "track"  # "track" or "organiser"


@dataclass(frozen=True)
class Override:
    """An organiser's decision on one control for one run."""

    code: str
    decision: str  # "accepted" or "denied"


@dataclass
class ControlResult:
    code: str
    status: str  # ok, missed, out_of_order, late, phone_only, accepted, denied
    t: datetime | None = None
    split_s: float | None = None
    points: int | None = None


@dataclass
class Result:
    """What a plugin returns for one run.

    `status` is one of: ok, mp (mispunch), dnf (did not finish),
    ot (over time), dsq (disqualified).
    `display` is the main figure shown to the participant, e.g. "29:44" or
    "120 pts". The server adds the position to make the headline.
    """

    status: str
    elapsed_s: float | None
    display: str
    lines: list[str] = field(default_factory=list)
    score: int | None = None
    controls: list[ControlResult] = field(default_factory=list)
    finish_t: datetime | None = None
    review_reasons: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
