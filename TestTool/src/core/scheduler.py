"""Async scheduler supporting once/interval tasks with cancel, timeout, and retry.

Design goals:
- Minimal dependency: asyncio only
- Explicit cancellation via job id
- Per-job timeout and retry policy with exponential backoff
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional


logger = logging.getLogger(__name__)


CallableSyncOrAsync = Callable[[], Any | Awaitable[Any]]


@dataclass
class RetryPolicy:
    max_retries: int = 0
    base_delay_ms: int = 200
    max_delay_ms: int = 10_000


@dataclass
class Job:
    id: str
    name: str = ""
    interval_ms: Optional[int] = None
    cancelled: bool = False
    last_run_ts: Optional[float] = None
    _task: Optional[asyncio.Task] = field(default=None, repr=False)


class Scheduler:
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._jobs: Dict[str, Job] = {}

    def schedule_once(
        self,
        fn: CallableSyncOrAsync,
        delay_ms: int = 0,
        *,
        name: str = "",
        timeout_ms: Optional[int] = None,
        retry: RetryPolicy | None = None,
    ) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, name=name)
        job._task = self._loop.create_task(
            self._run_once(job, fn, delay_ms, timeout_ms, retry)
        )
        self._jobs[job_id] = job
        return job

    def schedule_interval(
        self,
        fn: CallableSyncOrAsync,
        interval_ms: int,
        *,
        name: str = "",
        initial_delay_ms: int = 0,
        timeout_ms: Optional[int] = None,
        retry: RetryPolicy | None = None,
        jitter_ms: int = 0,
    ) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, name=name, interval_ms=interval_ms)
        job._task = self._loop.create_task(
            self._run_interval(job, fn, initial_delay_ms, timeout_ms, retry, jitter_ms)
        )
        self._jobs[job_id] = job
        return job

    def cancel(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.cancelled = True
        if job._task and not job._task.done():
            job._task.cancel()
        logger.debug("Cancelled job %s (%s)", job_id, job.name)

    def cancel_all(self) -> None:
        for job_id in list(self._jobs.keys()):
            self.cancel(job_id)

    async def _maybe_call(self, fn: CallableSyncOrAsync) -> Any:
        result = fn()
        if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
            return await result  # type: ignore[no-any-return]
        return result

    async def _run_once(
        self,
        job: Job,
        fn: CallableSyncOrAsync,
        delay_ms: int,
        timeout_ms: Optional[int],
        retry: RetryPolicy | None,
    ) -> None:
        try:
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
            await self._execute_with_policy(job, fn, timeout_ms, retry)
        except asyncio.CancelledError:  # noqa: PERF203
            logger.debug("Job %s cancelled before completion", job.id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Job %s failed: %s", job.id, exc)
        finally:
            self._jobs.pop(job.id, None)

    async def _run_interval(
        self,
        job: Job,
        fn: CallableSyncOrAsync,
        initial_delay_ms: int,
        timeout_ms: Optional[int],
        retry: RetryPolicy | None,
        jitter_ms: int,
    ) -> None:
        if initial_delay_ms > 0:
            try:
                await asyncio.sleep(initial_delay_ms / 1000)
            except asyncio.CancelledError:  # noqa: PERF203
                return
        while not job.cancelled:
            started = time.time()
            try:
                await self._execute_with_policy(job, fn, timeout_ms, retry)
            except asyncio.CancelledError:  # noqa: PERF203
                return
            except Exception as exc:  # noqa: BLE001
                logger.exception("Interval job %s failed: %s", job.id, exc)

            job.last_run_ts = started
            # compute next sleep considering execution time
            elapsed_ms = int((time.time() - started) * 1000)
            sleep_ms = max(0, (job.interval_ms or 0) - elapsed_ms)
            if jitter_ms > 0:
                # simple symmetric jitter
                j = min(jitter_ms, sleep_ms)
                sleep_ms = max(0, sleep_ms - j)
            try:
                await asyncio.sleep(sleep_ms / 1000)
            except asyncio.CancelledError:  # noqa: PERF203
                return

    async def _execute_with_policy(
        self,
        job: Job,
        fn: CallableSyncOrAsync,
        timeout_ms: Optional[int],
        retry: RetryPolicy | None,
    ) -> None:
        attempts = 0
        retry = retry or RetryPolicy(max_retries=0)
        while True:
            try:
                coro = self._maybe_call(fn)
                if timeout_ms and timeout_ms > 0:
                    await asyncio.wait_for(coro, timeout=timeout_ms / 1000)
                else:
                    await coro
                return
            except asyncio.TimeoutError:
                attempts += 1
                logger.warning("Job %s timeout (attempt %s)", job.id, attempts)
            except Exception as exc:  # noqa: BLE001
                attempts += 1
                logger.warning("Job %s attempt %s failed: %s", job.id, attempts, exc)

            if attempts > retry.max_retries:
                raise
            delay = min(retry.max_delay_ms, retry.base_delay_ms * (2 ** (attempts - 1)))
            await asyncio.sleep(delay / 1000)


__all__ = ["Scheduler", "Job", "RetryPolicy"]


