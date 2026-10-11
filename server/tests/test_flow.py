import io
import zipfile
from datetime import timedelta

from smartnav_sdk.testing import T0, walk

from smartnav_server.packages import course_from_package

from .conftest import KML, csrf, post_json, run_to_submission


def make_event(c, name="Harcourt Hill Street-O", event_type="line", extra_details=None):
    tok = csrf(c, "/admin/events/new")
    r = c.post("/admin/events/new", data={"csrf": tok, "name": name, "event_type": event_type},
               follow_redirects=False)
    assert r.status_code == 303
    eid = r.headers["location"].rsplit("/", 1)[-1]
    tok = csrf(c, f"/admin/events/{eid}")
    r = c.post(f"/admin/events/{eid}/import", data={"csrf": tok},
               files={"file": ("course.kml", KML, "application/vnd.google-earth.kml+xml")})
    assert r.status_code == 200
    details = {"csrf": tok, "name": name, "club": "Example OC", "event_type": event_type,
               "timezone": "Australia/Sydney", "opens_at": "2026-10-01T08:00", "closes_at": "2030-12-31T18:00",
               "punch_radius_m": "15", "start_mode": "punch", "finish_mode": "punch", "time_limit_min": ""}
    details.update(extra_details or {})
    r = c.post(f"/admin/events/{eid}/details", data=details)
    assert r.status_code == 200
    return eid


def publish(c, eid):
    tok = csrf(c, f"/admin/events/{eid}")
    r = c.post(f"/admin/events/{eid}/publish", data={"csrf": tok})
    assert "Event published" in r.text, r.text[:3000]
    # straight after publishing there must be no "unpublished changes" notice
    assert "Publish changes" not in c.get(f"/admin/events/{eid}").text


def test_requires_login(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and "/admin/login" in r.headers["location"]


def test_full_line_event_flow(admin):
    c = admin
    eid = make_event(c)
    # draft events are invisible to the app
    assert c.get(f"/v1/events/{eid}/package").status_code == 404
    publish(c, eid)

    lst = c.get("/v1/events").json()
    assert [e["id"] for e in lst["events"]] == [eid]

    r = c.get(f"/v1/events/{eid}/package")
    assert r.status_code == 200
    pkg = r.json()
    assert pkg["course"]["ordered"] is True
    assert [x["code"] for x in pkg["course"]["controls"]] == ["31", "32", "33"]
    assert "description" not in pkg["course"]["controls"][0]
    etag = r.headers["etag"]
    assert c.get(f"/v1/events/{eid}/package", headers={"If-None-Match": etag}).status_code == 304

    course = course_from_package(pkg)
    run = walk(course, ["S", "31", "32", "33", "F"], speed_mps=3, start=T0 + timedelta(days=3))
    doc = run_to_submission(run, eid, pkg["package_hash"])
    r = post_json(c, f"/v1/events/{eid}/submissions", doc)
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["status"] == "scored"
    assert res["summary"]["position"] == 1
    assert "1st of 1" in res["summary"]["headline"]
    assert res["summary"]["age_class"] == "Veteran"

    # retry of the same upload is idempotent
    r = post_json(c, f"/v1/events/{eid}/submissions", doc)
    assert r.status_code == 200
    # same id, different content is a conflict
    doc2 = dict(doc, participant={**doc["participant"], "club": "Other"})
    r = post_json(c, f"/v1/events/{eid}/submissions", doc2)
    assert r.status_code == 409 and r.json()["error"]["code"] == "submission_conflict"

    # a second, faster person
    fast = walk(course, ["S", "31", "32", "33", "F"], speed_mps=4, start=T0 + timedelta(days=3, hours=1))
    r = post_json(c, f"/v1/events/{eid}/submissions", run_to_submission(fast, eid, pkg["package_hash"], name="Bea Quick", yob="1990"))
    assert r.json()["summary"]["position"] == 1

    # Alex runs again, faster still: listed as an unranked repeat
    again = walk(course, ["S", "31", "32", "33", "F"], speed_mps=6, start=T0 + timedelta(days=4))
    r = post_json(c, f"/v1/events/{eid}/submissions", run_to_submission(again, eid, pkg["package_hash"], name="alex  citizen"))
    rep = r.json()
    assert rep["summary"]["first_run"] is False
    assert "repeat run 2" in rep["summary"]["headline"]

    results = c.get(f"/v1/events/{eid}/results").json()
    assert [x["name"] for x in results["results"]] == ["Bea Quick", "Alex Citizen"]
    assert results["results"][1]["position"] == 2
    assert len(results["results"][1]["repeats"]) == 1

    track = c.get(f"/v1/submissions/{doc['submission_id']}/track").json()
    assert len(track["points"]) == len(doc["track"]["points"])

    # public pages render
    assert "Bea Quick" in c.get(f"/events/{eid}/results").text
    ids = ",".join(x["submission_id"] for x in results["results"])
    assert c.get(f"/events/{eid}/tracks?ids={ids}").status_code == 200
    assert c.get(f"/runs/{doc['submission_id']}").status_code == 200

    # organiser denies control 32 for Bea: she becomes a mispunch
    bea = results["results"][0]["submission_id"]
    tok = csrf(c, f"/admin/runs/{bea}")
    c.post(f"/admin/runs/{bea}/control", data={"csrf": tok, "code": "32", "decision": "denied", "reason": "cut through"})
    r = c.get(f"/v1/submissions/{bea}/result").json()
    assert r["summary"]["headline"].startswith("MP")
    assert {x["code"]: x["status"] for x in r["controls"]}["32"] == "denied"
    alex = c.get(f"/v1/submissions/{doc['submission_id']}/result").json()
    assert alex["summary"]["position"] == 1
    # undo
    c.post(f"/admin/runs/{bea}/control", data={"csrf": tok, "code": "32", "decision": "clear"})
    assert c.get(f"/v1/submissions/{bea}/result").json()["summary"]["position"] == 1

    # name correction joins a misspelt run to the right person
    typo = walk(course, ["S", "31", "32", "33", "F"], speed_mps=2, start=T0 + timedelta(days=5))
    r = post_json(c, f"/v1/events/{eid}/submissions", run_to_submission(typo, eid, pkg["package_hash"], name="Bea Quik"))
    typo_id = r.json()["submission_id"]
    assert r.json()["summary"]["first_run"] is True
    c.post(f"/admin/runs/{typo_id}/rename", data={"csrf": tok, "name": "Bea Quick"})
    assert c.get(f"/v1/submissions/{typo_id}/result").json()["summary"]["first_run"] is False

    # CSV export
    csv_text = c.get(f"/admin/events/{eid}/export.csv").text
    assert "Bea Quick" in csv_text and "Position" in csv_text


def test_errors(admin):
    c = admin
    eid = make_event(c)
    publish(c, eid)
    pkg = c.get(f"/v1/events/{eid}/package").json()
    run = walk(course_from_package(pkg), ["S", "31", "F"], start=T0 + timedelta(days=3))
    doc = run_to_submission(run, eid, pkg["package_hash"])
    r = post_json(c, f"/v1/events/{eid}/submissions", {**doc, "format_version": 9})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_version"
    r = post_json(c, "/v1/events/nope/submissions", {**doc, "event_id": "nope"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "event_not_found"
    r = post_json(c, f"/v1/events/{eid}/submissions", {**doc, "participant": {"name": " "}})
    assert r.status_code == 400
    r = post_json(c, f"/v1/events/{eid}/submissions", {**doc, "submission_id": "../../etc/passwd-x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_submission"
    r = c.post(f"/v1/events/{eid}/submissions", content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_submission"
    # archived event refuses runs
    tok = csrf(c, f"/admin/events/{eid}")
    c.post(f"/admin/events/{eid}/status", data={"csrf": tok, "status": "archived"})
    r = post_json(c, f"/v1/events/{eid}/submissions", doc)
    assert r.status_code == 410 and r.json()["error"]["code"] == "event_closed"
    # results stay visible
    assert c.get(f"/events/{eid}/results").status_code == 200


def test_score_event_and_series(admin):
    c = admin
    # a series folder
    tok = csrf(c, "/admin/folders/new")
    c.post("/admin/folders/new", data={"csrf": tok, "name": "Summer Series", "is_series": "true"})
    eid = make_event(c, "Score One", "score", {"time_limit_min": "60"})
    tok = csrf(c, f"/admin/events/{eid}")
    r = c.post(f"/admin/events/{eid}/scoring", data={
        "csrf": tok, "points_31": "10", "points_32": "20", "points_33": "30", "default_points": "10",
        "late_penalty_per_minute": "10", "disqualify_after_min": "30", "finish_required": "on"})
    assert "Scoring settings saved" in r.text
    # put into the series folder
    details = {"csrf": tok, "name": "Score One", "club": "", "event_type": "score", "timezone": "Australia/Sydney",
               "opens_at": "2026-10-01T08:00", "closes_at": "2030-12-31T18:00", "punch_radius_m": "15",
               "start_mode": "tap", "finish_mode": "punch", "time_limit_min": "60", "folder_id": "1"}
    c.post(f"/admin/events/{eid}/details", data=details)
    publish(c, eid)
    pkg = c.get(f"/v1/events/{eid}/package").json()
    assert pkg["course"]["time_limit_min"] == 60
    assert "points" not in str(pkg["course"]["controls"])  # points never sent to the phone
    course = course_from_package(pkg)
    a = walk(course, ["S", "31", "32", "33", "F"], speed_mps=3, start=T0 + timedelta(days=3))
    b = walk(course, ["S", "33", "F"], speed_mps=3, start=T0 + timedelta(days=3))
    ra = post_json(c, f"/v1/events/{eid}/submissions", run_to_submission(a, eid, pkg["package_hash"], name="Ann")).json()
    rb = post_json(c, f"/v1/events/{eid}/submissions", run_to_submission(b, eid, pkg["package_hash"], name="Ben")).json()
    assert ra["summary"]["score"] == 60 and ra["summary"]["position"] == 1
    assert rb["summary"]["score"] == 30

    page = c.get("/series/1").text
    assert "Ann" in page and "100.0" in page and "50.0" in page

    # changing points and publishing changes rescores existing runs
    tok = csrf(c, f"/admin/events/{eid}")
    c.post(f"/admin/events/{eid}/scoring", data={
        "csrf": tok, "points_31": "10", "points_32": "20", "points_33": "90", "default_points": "10",
        "late_penalty_per_minute": "10", "disqualify_after_min": "30", "finish_required": "on"})
    publish(c, eid)
    rb2 = c.get(f"/v1/submissions/{rb['submission_id']}/result").json()
    assert rb2["summary"]["score"] == 90


def test_gpx_upload(admin):
    c = admin
    eid = make_event(c, "Scatter", "scatter")
    tok = csrf(c, f"/admin/events/{eid}")
    c.post(f"/admin/events/{eid}/scoring", data={"csrf": tok, "controls_required": "2", "finish_required": "on"})
    publish(c, eid)
    pkg = c.get(f"/v1/events/{eid}/package").json()
    run = walk(course_from_package(pkg), ["S", "S", "33", "31", "F"], start=T0 + timedelta(days=3), pause_s=30)
    gpx = ['<?xml version="1.0"?><gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>']
    for p in run.track:
        gpx.append(f'<trkpt lat="{p.lat}" lon="{p.lon}"><time>{p.t.isoformat().replace("+00:00", "Z")}</time></trkpt>')
    gpx.append("</trkseg></trk></gpx>")
    tok = csrf(c, f"/events/{eid}/upload")
    r = c.post(f"/events/{eid}/upload", data={"csrf": tok, "name": "Gail Watch", "club": "EOC",
                                              "year_of_birth": "1975", "consent": "true"},
               files={"file": ("run.gpx", "".join(gpx).encode(), "application/gpx+xml")})
    assert r.status_code == 200 and "Gail Watch" in r.text
    res = c.get(f"/v1/events/{eid}/results").json()["results"][0]
    assert res["status"] == "ok" and res["provisional"] is True


def test_kmz_map_import(admin):
    c = admin
    eid = make_event(c)
    kml = b"""<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><GroundOverlay>
    <Icon><href>files/map.png</href></Icon><LatLonBox><north>-35.22</north><south>-35.24</south>
    <east>149.09</east><west>149.07</west><rotation>0</rotation></LatLonBox></GroundOverlay></Document></kml>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.kml", kml)
        z.writestr("files/map.png", b"\x89PNG\r\n\x1a\nfake")
    tok = csrf(c, f"/admin/events/{eid}")
    r = c.post(f"/admin/events/{eid}/map", data={"csrf": tok}, files={"file": ("map.kmz", buf.getvalue(), "application/zip")})
    assert "Map image imported" in r.text
    publish(c, eid)
    assert c.get(f"/maps/{eid}").status_code == 200


def test_users_and_roles(admin):
    c = admin
    tok = csrf(c, "/admin/users")
    c.post("/admin/users", data={"csrf": tok, "name": "Dee", "email": "dee@example.org",
                                 "password": "delegate pass 1", "role": "delegate"})
    c.post("/admin/logout")
    tok = csrf(c)
    c.post("/admin/login", data={"csrf": tok, "email": "dee@example.org", "password": "delegate pass 1"})
    assert c.get("/admin").status_code == 200
    assert c.get("/admin/users").status_code == 403
