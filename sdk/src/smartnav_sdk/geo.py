"""Small geometry helpers. Distances in metres, WGS84 coordinates."""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle (haversine) distance between two points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def closest_on_segment(
    plat: float, plon: float, alat: float, alon: float, blat: float, blon: float
) -> tuple[float, float]:
    """Closest approach of point P to segment A-B.

    Returns (distance_m, fraction) where fraction is 0 at A and 1 at B.
    Uses a local flat projection, which is accurate over the few tens of
    metres between GPS fixes.
    """
    k = math.cos(math.radians(plat))
    ax, ay = (alon - plon) * k, alat - plat
    bx, by = (blon - plon) * k, blat - plat
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        f = 0.0
    else:
        f = max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
    cx, cy = ax + f * dx, ay + f * dy
    deg = math.hypot(cx, cy)
    return deg * (math.pi / 180) * EARTH_RADIUS_M, f
