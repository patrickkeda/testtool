"""Event bus providing sync/async publish-subscribe with simple topic patterns.

This module defines a minimal yet robust event bus that supports:
- Synchronous and asynchronous subscribers
- Topic pattern matching using Unix shell-style wildcards (fnmatch)
- Thread-safe subscription management
- Async publishing compatible with asyncio-based modules

Design notes:
- No global singletons. Instantiate `EventBus` and pass via DI.
- Handlers are isolated; one handler failure will be logged, not crash the bus.
- For high-throughput scenarios, consider batching on the caller side.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


SyncHandler = Callable[[Dict[str, Any]], None]
AsyncHandler = Callable[[Dict[str, Any]], Awaitable[None]]


@dataclass
class Subscription:
    """Represents a subscription that can be unsubscribed.

    Attributes:
        topic_pattern: Pattern this subscription matches
        is_async: Whether the handler is asynchronous
        handler_id: Internal identifier for handler lookup
    """

    topic_pattern: str
    is_async: bool
    handler_id: int


class EventBus:
    """Publish/subscribe event bus with sync/async handlers.

    Thread-safety: subscribing, unsubscribing, and reading handler maps are
    protected by a re-entrant lock. Handler invocation itself is not locked
    to avoid blocking other operations.
    """

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Initialize a new EventBus.

        Args:
            loop: Optional asyncio loop for async publishing. If not provided,
                  uses `asyncio.get_event_loop()` at publish time.
        """

        self._loop = loop
        self._lock = threading.RLock()
        self._next_id = 1
        self._sync_handlers: Dict[str, Dict[int, SyncHandler]] = {}
        self._async_handlers: Dict[str, Dict[int, AsyncHandler]] = {}

    def subscribe(self, topic_pattern: str, handler: SyncHandler) -> Subscription:
        """Subscribe a synchronous handler.

        Args:
            topic_pattern: Pattern like "test.*" or "config.changed"
            handler: Callable invoked with payload dict
        Returns:
            Subscription handle
        """

        with self._lock:
            handler_id = self._next_id
            self._next_id += 1
            self._sync_handlers.setdefault(topic_pattern, {})[handler_id] = handler
            logger.debug("Subscribed sync handler %s to %s", handler_id, topic_pattern)
            return Subscription(topic_pattern=topic_pattern, is_async=False, handler_id=handler_id)

    def subscribe_async(self, topic_pattern: str, handler: AsyncHandler) -> Subscription:
        """Subscribe an asynchronous handler."""

        with self._lock:
            handler_id = self._next_id
            self._next_id += 1
            self._async_handlers.setdefault(topic_pattern, {})[handler_id] = handler
            logger.debug("Subscribed async handler %s to %s", handler_id, topic_pattern)
            return Subscription(topic_pattern=topic_pattern, is_async=True, handler_id=handler_id)

    def unsubscribe(self, sub: Subscription) -> None:
        """Unsubscribe a previously registered handler."""

        with self._lock:
            if sub.is_async:
                bucket = self._async_handlers.get(sub.topic_pattern)
            else:
                bucket = self._sync_handlers.get(sub.topic_pattern)

            if bucket and sub.handler_id in bucket:
                del bucket[sub.handler_id]
                logger.debug("Unsubscribed handler %s from %s", sub.handler_id, sub.topic_pattern)

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """Publish an event synchronously.

        Sync handlers execute inline; async handlers are scheduled on the loop.
        """

        sync_handlers, async_handlers = self._collect_handlers(topic)

        # Invoke sync handlers
        for hid, h in sync_handlers:
            try:
                h(payload)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Sync handler %s for topic %s failed: %s", hid, topic, exc)

        # Schedule async handlers
        if async_handlers:
            loop = self._loop or asyncio.get_event_loop()
            for hid, h in async_handlers:
                loop.create_task(self._invoke_async_handler(hid, h, topic, payload))

    async def publish_async(self, topic: str, payload: Dict[str, Any]) -> None:
        """Publish an event and await async handlers completion.

        Sync handlers still execute inline in the calling thread.
        """

        sync_handlers, async_handlers = self._collect_handlers(topic)

        # Invoke sync handlers
        for hid, h in sync_handlers:
            try:
                h(payload)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Sync handler %s for topic %s failed: %s", hid, topic, exc)

        # Await async handlers
        tasks = [self._invoke_async_handler(hid, h, topic, payload) for hid, h in async_handlers]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _collect_handlers(self, topic: str) -> Tuple[List[Tuple[int, SyncHandler]], List[Tuple[int, AsyncHandler]]]:
        """Collect matching handlers for a topic.

        Matching uses fnmatch with stored topic patterns.
        """

        with self._lock:
            sync_list: List[Tuple[int, SyncHandler]] = []
            async_list: List[Tuple[int, AsyncHandler]] = []

            for pattern, handlers in self._sync_handlers.items():
                if fnmatch(topic, pattern):
                    sync_list.extend(list(handlers.items()))

            for pattern, handlers in self._async_handlers.items():
                if fnmatch(topic, pattern):
                    async_list.extend(list(handlers.items()))

            return sync_list, async_list

    async def _invoke_async_handler(self, hid: int, handler: AsyncHandler, topic: str, payload: Dict[str, Any]) -> None:
        try:
            await handler(payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Async handler %s for topic %s failed: %s", hid, topic, exc)


__all__ = ["EventBus", "Subscription"]


