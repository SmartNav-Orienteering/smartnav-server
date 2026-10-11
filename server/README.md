# server

The SmartNav host application: FastAPI, SQLAlchemy with SQLite, Jinja templates and a bundled copy of Leaflet for maps.

| Module | Purpose |
| --- | --- |
| `api_v1.py` | The `/v1` API for the phone app (see `docs/contract-v1.md`) |
| `admin.py` | Admin site: events, folders, imports, review tools, users, settings |
| `public.py` | Public results, track maps, series standings, GPX upload |
| `submissions.py` | Validating, storing and idempotent handling of runs; GPX conversion |
| `scoring.py` | Running the event-type plugin, review flags, first-run ranking, series |
| `packages.py` | Building course packages and keeping every published version |
| `importers.py` | KML, KMZ (map overlay) and GPX readers |
| `plugins.py` | Discovers event types through the `smartnav.event_types` entry point |
| `db.py` | Database models |
| `cli.py` | The `smartnav` command |

Raw submissions are stored as JSON files under `data/submissions/<event>/`, so runs can always be rescored, even after scoring rules change.

Run the tests from the repository root:

```
python -m pytest server/tests plugins/tests
```
