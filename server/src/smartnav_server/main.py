"""ASGI entry point: `uvicorn smartnav_server.main:app`."""
from .app import create_app

app = create_app()
