# server

The SmartNav host application.

Planned stack:

- Python 3.12+ with FastAPI for the API in `docs/contract-v1.md`
- Pydantic models for the package, submission and result formats
- SQLite (via SQLAlchemy) for events and results; tracks stored as files
- Server-rendered admin and results pages (Jinja + HTMX, Leaflet for maps)
- Distributed as a Docker image and as a `pip install smartnav-server` package

No code yet.
