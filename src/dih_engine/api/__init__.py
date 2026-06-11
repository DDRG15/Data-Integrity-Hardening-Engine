"""
dih-engine API service (Tier 2).

Run locally:
    uvicorn "dih_engine.api:create_app" --factory --port 8000

Every data endpoint requires the X-API-Key header matching the DIH_API_KEY
env var. The service fails closed: no key configured server-side means 503
on every authenticated route, never an open API.
"""
from .app import create_app

__all__ = ["create_app"]
