"""Configuration for the Leaflet map shown on admin and results pages."""
from __future__ import annotations

from .db import Event, Submission

COLOURS = ["#d7263d", "#1b6ca8", "#2e933c", "#f49d37", "#7b2cbf", "#00a6a6", "#c2185b", "#5d4037"]


def map_config(ev: Event, subs: list[Submission] | None = None, show_points: dict | None = None) -> dict:
    cfg = {
        "radius": ev.punch_radius_m,
        "controls": [{"code": c["code"], "lat": c["lat"], "lon": c["lon"],
                      **({"points": show_points.get(c["code"])} if show_points else {})} for c in ev.controls],
        "start": ev.start,
        "finish": ev.finish or ev.start,
        "ordered": ev.event_type == "line",
        "image": f"/maps/{ev.id}?v={int(ev.updated_at.timestamp())}" if ev.map_image else None,
        "bounds": ev.map_bounds,
        "tracks": [],
    }
    for i, s in enumerate(subs or []):
        cfg["tracks"].append(
            {"id": s.id, "name": s.participant_name, "colour": COLOURS[i % len(COLOURS)],
             "url": f"/v1/submissions/{s.id}/track"}
        )
    return cfg
