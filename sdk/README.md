# smartnav-sdk

`smartnav-sdk` is the small, stable package that event-type plugins depend on. Plugins receive plain data objects and return a `Result`; they never touch the database, files or the web.

## What the server does for you

For every run, the server:

1. Detects control visits from the GPS track: every time the track enters a control's circle, including when the runner passed through the circle between two GPS fixes. Fixes with accuracy worse than the event's limit are ignored.
2. Finds the finish: the phone's finish punch or tap, or, for GPX uploads, the last entry into the finish circle.
3. Applies the organiser's decisions (accepted or denied controls).
4. Calls your plugin's `score()` and ranks the results with `rank_key()`.
5. Flags anything the organiser should check, such as a control the phone beeped for but the track does not confirm.

## Writing an event type

```python
from smartnav_sdk import ControlResult, EventType, Param, Result, format_duration


class GoatEvent(EventType):
    id = "goat"
    name = "Goat (any order, all controls)"
    description = "Visit every control in any order. Fastest time wins."
    ordered = False                       # the phone accepts controls in any order
    params = [Param("finish_required", "Finish punch required", "bool", True)]

    def score(self, run, course, params, visits, start_t, finish_t):
        seen = {}
        for v in visits:
            seen.setdefault(v.code, v)
        controls = [
            ControlResult(c.code, "ok", seen[c.code].t) if c.code in seen else ControlResult(c.code, "missed")
            for c in course.controls
        ]
        elapsed = (finish_t - start_t).total_seconds() if finish_t else None
        if finish_t is None:
            return Result("dnf", None, "DNF", ["Finish not reached"], controls=controls)
        if len(seen) < len(course.controls):
            return Result("mp", elapsed, "MP", ["Not all controls visited"], controls=controls)
        return Result("ok", elapsed, format_duration(elapsed), controls=controls)
```

Register it in your package's `pyproject.toml`:

```toml
[project.entry-points."smartnav.event_types"]
goat = "my_club_plugins.goat:GoatEvent"
```

Install the package where the server runs and restart it. The new type appears in the admin site's event type list.

### Hooks you can override

| Method | Default |
| --- | --- |
| `score(...)` | Required. Returns a `Result` |
| `rank_key(result)` | Rank by elapsed time; `None` means unranked |
| `validate(course, params)` | Checks for controls and required parameters; return a list of problems |
| `series_points(result, winner)` | 100 for the winner, scaled by time or score |
| `detect_visits`, `detect_finish`, `start_time` | The standard detection described above |

`Result.status` is one of `ok`, `mp` (mispunch), `dnf`, `ot` (over time) or `dsq`. `Result.display` is the main figure the participant sees, such as `29:44` or `120 pts`; the server adds the position.

## Testing without a phone

```python
from smartnav_sdk.testing import course, walk

c = course("goat", {"31": (-35.2288, 149.0851), "32": (-35.2265, 149.0834)}, start=(-35.2310, 149.0823))
run = walk(c, ["S", "32", "31", "S"], speed_mps=3)
result = GoatEvent().evaluate(run, c, {"finish_required": True}, [])
assert result.status == "ok"
```

`walk()` simulates a runner moving in straight lines between the named points, with a GPS fix every second. The built-in `line`, `score` and `scatter` plugins in `../plugins` are complete examples with tests.
