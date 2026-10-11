"""Import controls from KML/KMZ, map images from KMZ, and tracks from GPX."""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone

START_NAMES = {"s", "s1", "start", "st"}
FINISH_NAMES = {"f", "f1", "finish", "fin"}


class ImportError_(ValueError):
    pass


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


@dataclass
class KmlCourse:
    controls: list[dict] = field(default_factory=list)
    start: dict | None = None
    finish: dict | None = None
    skipped: list[str] = field(default_factory=list)


def parse_kml(data: bytes) -> KmlCourse:
    """Read Placemark points. The placemark name is the control code.
    Placemarks named S/Start and F/Finish become the start and finish."""
    try:
        root = _strip_ns(ET.fromstring(data))
    except ET.ParseError as e:
        raise ImportError_(f"The KML file could not be read: {e}") from e
    out = KmlCourse()
    for pm in root.iter("Placemark"):
        name = (pm.findtext("name") or "").strip()
        coords = pm.find(".//Point/coordinates")
        if coords is None or not (coords.text or "").strip():
            if name:
                out.skipped.append(name)
            continue
        parts = coords.text.strip().split()[0].split(",")
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            out.skipped.append(name or "(unnamed)")
            continue
        code = re.sub(r"\s+", "", name)
        if not code:
            out.skipped.append("(unnamed)")
            continue
        if code.lower() in START_NAMES:
            out.start = {"code": "S", "lat": lat, "lon": lon}
        elif code.lower() in FINISH_NAMES:
            out.finish = {"code": "F", "lat": lat, "lon": lon}
        else:
            out.controls.append({"code": code, "lat": lat, "lon": lon})
    if not out.controls and not out.start:
        raise ImportError_("No control points were found in the file.")
    return out


@dataclass
class KmzMap:
    image: bytes
    ext: str
    bounds: dict  # north, south, east, west, rotation
    course: KmlCourse | None = None


def parse_kmz(data: bytes) -> KmzMap:
    """Read a KMZ containing a GroundOverlay map image (and optionally
    control placemarks)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ImportError_("The KMZ file is not a valid zip archive.") from e
    kml_name = next((n for n in zf.namelist() if n.lower().endswith(".kml")), None)
    if not kml_name:
        raise ImportError_("The KMZ file does not contain a KML document.")
    root = _strip_ns(ET.fromstring(zf.read(kml_name)))
    go = root.find(".//GroundOverlay")
    if go is None:
        raise ImportError_("The KMZ file has no GroundOverlay (map image).")
    href = (go.findtext("Icon/href") or "").strip()
    box = go.find("LatLonBox")
    quad = go.find("LatLonQuad")
    if not href or (box is None and quad is None):
        raise ImportError_("The map overlay is missing its image or its corner coordinates.")
    if box is not None:
        bounds = {k: float(box.findtext(k)) for k in ("north", "south", "east", "west")}
        bounds["rotation"] = float(box.findtext("rotation") or 0)
    else:
        corners = [tuple(map(float, c.split(",")[:2])) for c in quad.findtext("coordinates").split()]
        lons, lats = [c[0] for c in corners], [c[1] for c in corners]
        bounds = {
            "north": max(lats), "south": min(lats), "east": max(lons), "west": min(lons),
            "rotation": 0.0, "quad": [[c[1], c[0]] for c in corners],
        }
    try:
        image = zf.read(href)
    except KeyError as e:
        raise ImportError_(f"The map image {href} is not inside the KMZ file.") from e
    ext = href.rsplit(".", 1)[-1].lower()
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        raise ImportError_("The map image must be JPEG, PNG, GIF or WebP.")
    course = None
    try:
        course = parse_kml(zf.read(kml_name))
    except ImportError_:
        pass
    return KmzMap(image=image, ext=ext, bounds=bounds, course=course)


def parse_gpx(data: bytes) -> list[tuple[datetime, float, float, float | None]]:
    """Track points from a GPX file: (time, lat, lon, elevation)."""
    try:
        root = _strip_ns(ET.fromstring(data))
    except ET.ParseError as e:
        raise ImportError_(f"The GPX file could not be read: {e}") from e
    pts = []
    for tp in root.iter("trkpt"):
        t = tp.findtext("time")
        if not t:
            continue
        ts = datetime.fromisoformat(t.strip().replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ele = tp.findtext("ele")
        pts.append((ts, float(tp.get("lat")), float(tp.get("lon")), float(ele) if ele else None))
    pts.sort(key=lambda p: p[0])
    if len(pts) < 2:
        raise ImportError_("The GPX file has no timed track points.")
    return pts
