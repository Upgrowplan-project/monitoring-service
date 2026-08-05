"""
In-process periodic scheduler for the monitoring web dyno.

Why: production runs only a `web` dyno (no Celery worker/beat), so the periodic
Celery tasks (health checks, Redis cleanup, IMAP email fetch) never executed.
This lightweight asyncio scheduler runs them directly inside the web process —
zero extra dynos, zero extra cost.

Each tick runs the EXISTING Celery task function (called directly = synchronous
local execution) inside a thread executor. Running in a worker thread keeps the
web event loop responsive AND lets those functions use their internal
`asyncio.run(...)` calls safely (no running loop in the thread).

Disable by setting ENABLE_INPROCESS_SCHEDULER=false (e.g. if you later add real
worker/beat dynos).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.getenv("ENABLE_INPROCESS_SCHEDULER", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class InProcessScheduler:
    def __init__(self) -> None:
        self._tasks: List[asyncio.Task] = []
        # Created in start() so it binds to the app's running event loop.
        self._stop: Optional[asyncio.Event] = None

    async def _run_periodic(
        self, name: str, interval: float, func: Callable, initial_delay: float
    ) -> None:
        """Run `func` (a blocking callable) every `interval` seconds in a thread."""
        await asyncio.sleep(initial_delay)
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            started = loop.time()
            try:
                await loop.run_in_executor(None, func)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[SCHEDULER] task '{name}' failed: {e}")
            # Sleep the remainder of the interval, but wake early on stop.
            elapsed = loop.time() - started
            wait_for = max(1.0, interval - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait_for)
            except asyncio.TimeoutError:
                pass

    def start(self, config) -> None:
        if not _enabled():
            logger.info("[SCHEDULER] in-process scheduler disabled via env")
            return
        if self._tasks:
            return

        self._stop = asyncio.Event()

        # Import here so importing celery/tasks is deferred to runtime.
        from monitoring.tasks import (
            check_all_services_task,
            check_redis_memory_task,
            fetch_emails_task,
            cleanup_old_data_task,
            visibility_scan_task,
            geo_visibility_task,
        )

        health_int = float(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "300"))
        redis_int = float(os.getenv("REDIS_CHECK_INTERVAL_SECONDS", "120"))
        email_int = float(getattr(config, "IMAP_POLL_INTERVAL_SECONDS", 60) or 60)
        cleanup_int = float(os.getenv("CLEANUP_INTERVAL_SECONDS", str(24 * 3600)))
        # Visibility Monitor V1: 4ч ≈ 6×/день.
        visibility_int = float(os.getenv("VISIBILITY_SCAN_INTERVAL_SECONDS", str(4 * 3600)))
        # GEO Visibility: раз в день (Gemini free tier 1500 req/day).
        geo_int = float(os.getenv("GEO_SCAN_INTERVAL_SECONDS", str(24 * 3600)))

        loop = asyncio.get_running_loop()
        # Stagger initial delays so the first ticks don't all fire at once.
        self._tasks = [
            loop.create_task(
                self._run_periodic("health_checks", health_int, check_all_services_task, 5)
            ),
            loop.create_task(
                self._run_periodic("redis_memory", redis_int, check_redis_memory_task, 10)
            ),
            loop.create_task(
                self._run_periodic("fetch_emails", email_int, fetch_emails_task, 15)
            ),
            loop.create_task(
                self._run_periodic("cleanup_old_data", cleanup_int, cleanup_old_data_task, 60)
            ),
            loop.create_task(
                self._run_periodic("visibility_scan", visibility_int, visibility_scan_task, 30)
            ),
            loop.create_task(
                self._run_periodic("geo_visibility", geo_int, geo_visibility_task, 120)
            ),
        ]
        logger.info(
            f"[SCHEDULER] started: health={health_int}s, redis={redis_int}s, "
            f"email={email_int}s, cleanup={cleanup_int}s, visibility={visibility_int}s, geo={geo_int}s"
        )

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
        logger.info("[SCHEDULER] stopped")


# Singleton used by the FastAPI app lifecycle.
scheduler: Optional[InProcessScheduler] = InProcessScheduler()
