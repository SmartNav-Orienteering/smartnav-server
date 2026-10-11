"""Pydantic models for the app–server contract v1 (docs/contract-v1.md).

Unknown fields are ignored, as the compatibility rules require."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SUPPORTED_SUBMISSION_VERSIONS = {1}


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Device(_Lenient):
    install_id: str = ""
    platform: str = ""
    os_version: str = ""
    app_version: str = ""
    model: str = ""


class Activity(_Lenient):
    started_at: datetime
    ended_at: datetime
    start_method: str = "tap"
    end_reason: str


class PunchIn(_Lenient):
    code: str
    t: datetime
    lat: float | None = None
    lon: float | None = None
    accuracy_m: float | None = None
    distance_m: float | None = None


class TrackIn(_Lenient):
    epoch: datetime
    fields: list[str]
    points: list[list[float | None]]

    @field_validator("fields")
    @classmethod
    def _need_basic_columns(cls, v):
        missing = {"dt_ms", "lat", "lon"} - set(v)
        if missing:
            raise ValueError("track.fields must include dt_ms, lat and lon")
        return v


class SubmissionIn(_Lenient):
    format: str
    format_version: int
    # Used in a file name, so only letters, digits and hyphens (a UUID).
    submission_id: str = Field(min_length=8, max_length=40, pattern=r"^[A-Za-z0-9-]+$")
    event_id: str
    package_hash: str
    participant: dict[str, Any]
    device: Device = Device()
    activity: Activity
    punches: list[PunchIn] = []
    track: TrackIn
    app_log: list[str] = []

    @field_validator("format")
    @classmethod
    def _format(cls, v):
        if v != "smartnav.submission":
            raise ValueError('format must be "smartnav.submission"')
        return v


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}
