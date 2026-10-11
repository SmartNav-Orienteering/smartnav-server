import gzip
import json
import re
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTNAV_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SMARTNAV_BASE_URL", "http://testserver")
    from smartnav_server.config import get_settings

    get_settings.cache_clear()
    from smartnav_server.app import create_app

    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def csrf(client, path="/admin/login"):
    html = client.get(path).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def admin(client):
    tok = csrf(client)
    r = client.post("/admin/setup", data={"csrf": tok, "name": "Geoff", "email": "geoff@example.org",
                                           "password": "correct horse battery"}, follow_redirects=False)
    assert r.status_code == 303
    return client


KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>S</name><Point><coordinates>149.082310,-35.231020,0</coordinates></Point></Placemark>
<Placemark><name>31</name><Point><coordinates>149.085120,-35.228810,0</coordinates></Point></Placemark>
<Placemark><name>32</name><Point><coordinates>149.083400,-35.226470,0</coordinates></Point></Placemark>
<Placemark><name>33</name><Point><coordinates>149.079870,-35.229900,0</coordinates></Point></Placemark>
<Placemark><name>F</name><Point><coordinates>149.081990,-35.231450,0</coordinates></Point></Placemark>
</Document></kml>"""


def run_to_submission(run, event_id, package_hash, name="Alex Citizen", club="EOC", yob="1980", sub_id=None):
    t0 = run.track[0].t

    def iso(d):
        return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"

    return {
        "format": "smartnav.submission",
        "format_version": 1,
        "submission_id": sub_id or str(uuid.uuid4()),
        "event_id": event_id,
        "package_hash": package_hash,
        "participant": {"name": name, "club": club, "year_of_birth": yob},
        "device": {"install_id": str(uuid.uuid4()), "platform": "android", "os_version": "15",
                   "app_version": "1.0.0", "model": "Pixel 8"},
        "activity": {"started_at": iso(run.started_at), "ended_at": iso(run.ended_at),
                     "start_method": "punch", "end_reason": run.end_reason},
        "punches": [{"code": p.code, "t": iso(p.t), "lat": p.lat, "lon": p.lon, "accuracy_m": p.accuracy_m,
                     "distance_m": p.distance_m} for p in run.phone_punches],
        "track": {"epoch": iso(t0), "fields": ["dt_ms", "lat", "lon", "acc_m", "alt_m"],
                  "points": [[int((p.t - t0).total_seconds() * 1000), round(p.lat, 6), round(p.lon, 6), p.acc_m, None]
                             for p in run.track]},
        "app_log": [],
    }


def post_json(client, url, doc, gz=True):
    body = json.dumps(doc).encode()
    headers = {"Content-Type": "application/json"}
    if gz:
        body = gzip.compress(body)
        headers["Content-Encoding"] = "gzip"
    return client.post(url, content=body, headers=headers)
