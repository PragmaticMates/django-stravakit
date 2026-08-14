"""Service layer.

Two kinds of module live here. Most (``activities``, ``analytics``, ``compare``,
``dashboard``, ``gear``) are *pure computation* over already-fetched ``Activity``/``Gear``
collections, so views stay thin orchestrators and the arithmetic is unit-testable in
isolation. ``sync`` is the write side: the API-and-DB orchestration that reconciles a row
with Strava (pull/push), kept out of the models for the same reason.
"""
from stravakit.services import activities, analytics, compare, dashboard, gear, sync

__all__ = ["activities", "analytics", "compare", "dashboard", "gear", "sync"]
