"""Participant names and age classes.

Runs are matched to the same person by name only (decision in the spec).
Matching ignores case, accents and extra spaces, so "anna  smith" and
"Anna Smith" are the same person."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

DEFAULT_AGE_CLASSES = [
    {"name": "Junior", "max_age": 20},
    {"name": "Open", "min_age": 21, "max_age": 44},
    {"name": "Veteran", "min_age": 45},
]


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def name_key(name: str) -> str:
    n = unicodedata.normalize("NFKD", clean_name(name))
    n = "".join(ch for ch in n if not unicodedata.combining(ch))
    return n.casefold()


def age_class(year_of_birth, event_date: datetime, classes: list[dict] | None) -> str:
    """Orienteering convention: age is the age reached during the event's year."""
    try:
        yob = int(year_of_birth)
    except (TypeError, ValueError):
        return ""
    age = event_date.year - yob
    for c in classes or DEFAULT_AGE_CLASSES:
        if c.get("min_age") is not None and age < int(c["min_age"]):
            continue
        if c.get("max_age") is not None and age > int(c["max_age"]):
            continue
        return c["name"]
    return ""
