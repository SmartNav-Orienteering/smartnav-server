"""Shared helpers for the HTML pages (admin and public)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates
from smartnav_sdk import format_duration

from .auth import csrf_token
from .config import get_settings

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def local(dt: datetime | None, tz: str = "Australia/Sydney", fmt: str = "%a %d %b %Y, %H:%M") -> str:
    if dt is None:
        return ""
    try:
        return dt.astimezone(ZoneInfo(tz)).strftime(fmt)
    except Exception:
        return dt.strftime(fmt)


def local_input(dt: datetime | None, tz: str) -> str:
    """Value for an <input type=datetime-local>."""
    return local(dt, tz, "%Y-%m-%dT%H:%M") if dt else ""


def parse_local(value: str, tz: str) -> datetime:
    naive = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    return naive.replace(tzinfo=ZoneInfo(tz))


STATUS_LABELS = {
    "ok": "OK",
    "mp": "Mispunch",
    "dnf": "Did not finish",
    "ot": "Over time",
    "dsq": "Disqualified",
}

CONTROL_STATUS_LABELS = {
    "ok": "OK",
    "missed": "Missed",
    "out_of_order": "Out of order",
    "late": "Late",
    "phone_only": "Phone only",
    "accepted": "Accepted by organiser",
    "denied": "Denied by organiser",
}

def natural_key(code: str):
    """Sort key so control codes run 1, 2, 10 (not 1, 10, 2) and letters still sort."""
    import re

    return [(0, int(p), "") if p.isdigit() else (1, 0, p.casefold()) for p in re.split(r"(\d+)", str(code)) if p]


def display_controls(controls: list, ordered: bool) -> list:
    """Controls as shown to organisers: course order for line courses,
    ascending code order for courses taken in any order."""
    if ordered:
        return list(controls)
    return sorted(controls, key=lambda c: natural_key(c["code"]))


TEMPLATES.env.globals.update(
    local=local,
    local_input=local_input,
    duration=format_duration,
    STATUS_LABELS=STATUS_LABELS,
    CONTROL_STATUS_LABELS=CONTROL_STATUS_LABELS,
    display_controls=display_controls,
)


def render(request: Request, name: str, status_code: int = 200, **ctx):
    ctx.setdefault("user", getattr(request.state, "user", None))
    ctx["csrf"] = csrf_token(request)
    ctx["base_url"] = get_settings().base_url
    ctx["flash"] = request.session.pop("flash", None)
    return TEMPLATES.TemplateResponse(request, name, ctx, status_code=status_code)


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = {"message": message, "kind": kind}
