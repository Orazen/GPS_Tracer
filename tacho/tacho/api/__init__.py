"""Internal HTTP API for the tachograph service."""

from .app import create_app

__all__ = ["create_app"]
