from datetime import timedelta

from smartnav_sdk import Override
from smartnav_sdk.testing import course, walk
from smartnav_plugins.line import LineEvent
from smartnav_plugins.scatter import ScatterEvent
from smartnav_plugins.score import ScoreEvent

START = (-35.231020, 149.082310)
CONTROLS = {
    "31": (-35.228810, 149.085120),
    "32": (-35.226470, 149.083400),
    "33": (-35.229900, 149.079870),
}


def line_course():
    return course("line", CONTROLS, START, (-35.231450, 149.081990), ordered=True)


def test_line_clean_run():
    c = line_course()
    run = walk(c, ["S", "31", "32", "33", "F"])
    r = LineEvent().evaluate(run, c, {}, [])
    assert r.status == "ok"
    assert [x.status for x in r.controls] == ["ok", "ok", "ok"]
    assert r.elapsed_s == (run.ended_at - run.started_at).total_seconds()
    assert LineEvent().rank_key(r) == (r.elapsed_s,)


def test_line_missed_control_is_mispunch():
    c = line_course()
    run = walk(c, ["S", "31", "33", "F"])
    r = LineEvent().evaluate(run, c, {}, [])
    assert r.status == "mp"
    assert {x.code: x.status for x in r.controls}["32"] == "missed"
    assert LineEvent().rank_key(r) is None


def test_line_out_of_order():
    c = line_course()
    run = walk(c, ["S", "32", "31", "33", "F"])
    r = LineEvent().evaluate(run, c, {}, [])
    assert r.status == "mp"


def test_organiser_accepts_missed_control():
    c = line_course()
    run = walk(c, ["S", "31", "33", "F"])
    r = LineEvent().evaluate(run, c, {}, [Override("32", "accepted")])
    # 32 was never near the track, accepted at closest approach - but that is
    # after 31 and before 33 only if the route passed nearer; check status set.
    assert {x.code: x.status for x in r.controls}["32"] == "accepted"


def test_organiser_denies_control():
    c = line_course()
    run = walk(c, ["S", "31", "32", "33", "F"])
    r = LineEvent().evaluate(run, c, {}, [Override("32", "denied")])
    assert r.status == "mp"
    assert {x.code: x.status for x in r.controls}["32"] == "denied"


def test_phone_only_flagged_for_review():
    c = line_course()
    run = walk(c, ["S", "31", "33", "F"])
    from smartnav_sdk import PhonePunch

    run.phone_punches.append(PhonePunch("32", run.started_at + timedelta(minutes=3)))
    r = LineEvent().evaluate(run, c, {}, [])
    assert {x.code: x.status for x in r.controls}["32"] == "phone_only"
    assert any("32" in reason for reason in r.review_reasons)


def score_course(limit=60):
    return course("score", CONTROLS, START, time_limit_min=limit)


PARAMS = {
    "points": {"31": 10, "32": 20, "33": 30},
    "default_points": 10,
    "late_penalty_per_minute": 10,
    "disqualify_after_min": 30,
    "finish_required": True,
}


def test_score_on_time():
    c = score_course()
    run = walk(c, ["S", "31", "32", "S"], speed_mps=3)
    r = ScoreEvent().evaluate(run, c, PARAMS, [])
    assert r.status == "ok"
    assert r.score == 30
    assert r.extra["penalty"] == 0


def test_score_late_penalty_per_started_minute():
    c = score_course(limit=5)  # runner takes ~8.6 minutes at 2 m/s
    run = walk(c, ["S", "31", "32", "33", "S"], speed_mps=2)
    r = ScoreEvent().evaluate(run, c, PARAMS, [])
    over_s = r.elapsed_s - 300
    import math

    assert r.extra["minutes_late"] == math.ceil(over_s / 60)
    assert r.score == max(0, 60 - 10 * r.extra["minutes_late"])


def test_score_ranks_by_points_then_time():
    ev = ScoreEvent()
    c = score_course()
    fast = ev.evaluate(walk(c, ["S", "33", "S"], speed_mps=4), c, PARAMS, [])
    slow = ev.evaluate(walk(c, ["S", "33", "S"], speed_mps=2), c, PARAMS, [])
    more = ev.evaluate(walk(c, ["S", "31", "33", "S"], speed_mps=2), c, PARAMS, [])
    ranked = sorted([fast, slow, more], key=ev.rank_key)
    assert ranked == [more, fast, slow]


def test_score_validate_unknown_control():
    c = score_course()
    problems = ScoreEvent().validate(c, {"points": {"99": 10}})
    assert any("99" in p for p in problems)


def scatter_course():
    return course("scatter", CONTROLS, START)


def test_scatter_complete():
    c = scatter_course()
    run = walk(c, ["S", "33", "31", "S"])
    r = ScatterEvent().evaluate(run, c, {"controls_required": 2}, [])
    assert r.status == "ok"


def test_scatter_too_few_is_mispunch():
    c = scatter_course()
    run = walk(c, ["S", "33", "S"])
    r = ScatterEvent().evaluate(run, c, {"controls_required": 2}, [])
    assert r.status == "mp"


def test_scatter_validate_range():
    c = scatter_course()
    assert ScatterEvent().validate(c, {"controls_required": 4})
    assert not ScatterEvent().validate(c, {"controls_required": 3})


def test_gpx_style_finish_detection():
    c = scatter_course()
    run = walk(c, ["S", "33", "31", "S"], end_reason="max_duration")
    r = ScatterEvent().evaluate(run, c, {"controls_required": 2}, [])
    assert r.status == "ok"
    assert r.finish_t is not None
