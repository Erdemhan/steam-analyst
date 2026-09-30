"""
Event sink factory for progress and diagnostic logging during pipeline execution.

This module provides make_event_sink, which builds a concrete EventSink instance
that wraps storage.append_run_event with light throttling for high-frequency
progress events (info level) while ensuring error and warning events are never
silently dropped.
"""

import logging
import sqlite3
import time
from typing import Callable

from steam_analyst.storage.events import append_run_event
from steam_analyst.storage.types import EventSink

logger = logging.getLogger(__name__)

# Throttle interval for 'info'-level progress events (seconds).
# At most one info-level event per this interval is persisted; others are silently
# dropped by the throttle. Error and warning events bypass this throttle entirely.
INFO_THROTTLE_INTERVAL_SECONDS = 2.0


def make_event_sink(conn: sqlite3.Connection, run_id: str) -> EventSink:
    """Build an EventSink backed by storage.append_run_event.

    Args:
        conn: The same connection run_pipeline is using for this call. The sink
            does not open its own connection, since it is only ever called from
            the same thread and unit of work as the stage it reports for.
        run_id: The run to attach every event to.

    Returns:
        A callable satisfying storage.EventSink's Protocol (stage, level, message,
        progress) -> None, that calls storage.append_run_event(conn, run_id,
        stage=stage, level=level, message=message, progress=progress) with
        light throttling: at most one 'info'-level progress event per
        INFO_THROTTLE_INTERVAL_SECONDS is actually written; 'warning' and 'error'
        level events are never throttled and are always written immediately.

        The sink itself never raises -- an internal append_run_event failure is
        caught and logged, per storage.EventSink's own documented contract that
        a logging failure must never abort the pipeline stage using it.
    """
    # Track the last time an 'info'-level event was persisted, so we can throttle
    # subsequent 'info' events.
    last_info_persisted_time: float = 0.0

    def event_sink(
        *,
        stage: str,
        level: str,
        message: str,
        progress: float | None = None,
    ) -> None:
        """Report a progress or diagnostic event to storage.

        Args:
            stage: The pipeline stage reporting the event.
            level: Event severity; one of {'debug','info','warning','error'}.
            message: Human-readable event description.
            progress: Optional fractional progress (0.0 to 1.0).
        """
        nonlocal last_info_persisted_time

        # Determine whether this event should be persisted based on level and throttle.
        should_persist = True
        if level == "info":
            now = time.time()
            elapsed = now - last_info_persisted_time
            if elapsed < INFO_THROTTLE_INTERVAL_SECONDS:
                # Throttled: silently drop this info event.
                should_persist = False
            else:
                # This info event passes the throttle; update the timestamp.
                last_info_persisted_time = now

        if should_persist:
            try:
                append_run_event(
                    conn,
                    run_id,
                    stage=stage,
                    level=level,
                    message=message,
                    progress=progress,
                )
            except Exception as e:
                # Catch any exception from append_run_event (StorageError, sqlite3.Error,
                # or any other) and log it locally. Never propagate, so the stage's own
                # work is not aborted by a progress-reporting failure.
                logger.exception(
                    "Failed to append run event for run %s: %s",
                    run_id,
                    e,
                )

    return event_sink
