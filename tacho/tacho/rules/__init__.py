"""Driving-time rules.

``driving_time`` is the only module here, and it is versioned: see
``driving_time.RULES_VERSION``. Any change that could alter a computed figure
requires a version bump, because stored calculations name the version that
produced them.
"""

from . import driving_time

__all__ = ["driving_time"]
