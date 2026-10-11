"""Discovers installed event-type plugins via the `smartnav.event_types`
entry point group. Installing a plugin package is enough to make it
available; restart the server afterwards."""
from __future__ import annotations

import logging
from functools import lru_cache
from importlib.metadata import entry_points

from smartnav_sdk import EventType

log = logging.getLogger(__name__)


@lru_cache
def registry() -> dict[str, EventType]:
    found: dict[str, EventType] = {}
    for ep in entry_points(group="smartnav.event_types"):
        try:
            cls = ep.load()
            inst = cls()
            found[inst.id or ep.name] = inst
        except Exception:  # a broken plugin must not stop the server
            log.exception("Could not load event type plugin %s", ep.name)
    return dict(sorted(found.items()))


def get_event_type(type_id: str) -> EventType | None:
    return registry().get(type_id)
