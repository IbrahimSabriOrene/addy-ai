"""Documenter sinks (Observer pattern), copied from the orchestrator.

Each sink receives the same structured event dict; how it ships the event is
its own business. Sinks must never raise into the graph — a broken Graylog
connection must not fail a run — so the handler wraps emission in try/except
and sinks stay simple.

First sinks (PLAN.md): console + Graylog (the repo's docker-compose Graylog
stack serves it). Each event carries ``cost_cents`` for spend queries.
"""

from __future__ import annotations

import json
import logging


class ConsoleSink:
    """Local-dev sink: one line per checkpoint on stdout."""

    def emit(self, event: dict) -> None:
        print(f"[documenter] {json.dumps(event, default=str)}")


class GraylogSink:
    """Structured, queryable log entries shipped via GELF to Graylog.
    Uses ``graypy`` (optional dependency: install extra ``graylog``)."""

    def __init__(self, host: str, port: int = 12201, facility: str = "mobile-ad-maker"):
        import graypy

        self._logger = logging.getLogger(facility)
        self._logger.setLevel(logging.INFO)
        self._logger.addHandler(graypy.GELFUDPHandler(host, port))

    def emit(self, event: dict) -> None:
        self._logger.info(
            "checkpoint %s", event.get("checkpoint"), extra={"admaker": event}
        )


class NotifySink:
    """The same event as a one-way message into a NotificationChannel (e.g.
    the mobile app's live-progress feed). Never expects a reply."""

    def __init__(self, channel) -> None:
        self._channel = channel

    def emit(self, event: dict) -> None:
        checkpoint = event.get("checkpoint", "?")
        status = event.get("status", "ok")
        detail = event.get("detail", "")
        text = f"✅ {checkpoint}" if status == "ok" else f"❌ {checkpoint} — {status}"
        if detail:
            text += f"\n{detail}"
        self._channel.notify(text)
