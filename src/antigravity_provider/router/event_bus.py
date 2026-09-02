"""Hermes Hub — Typed Asynchronous EventBus with Thread-Safe UI Dispatching."""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("hermes.router.event_bus")


# ── Typed Event Constants ──
EVENT_ACCOUNT_UPDATED = "ACCOUNT_UPDATED"
EVENT_ACCOUNT_ADDED = "ACCOUNT_ADDED"
EVENT_ACCOUNT_REMOVED = "ACCOUNT_REMOVED"
EVENT_ACCOUNT_AUTH_CHANGED = "ACCOUNT_AUTH_CHANGED"

EVENT_QUOTA_UPDATED = "QUOTA_UPDATED"

EVENT_ROUTING_UPDATED = "ROUTING_UPDATED"
EVENT_AGENT_UPDATED = "AGENT_UPDATED"
EVENT_SYSTEM_READINESS_CHANGED = "SYSTEM_READINESS_CHANGED"

EVENT_REFRESH_STARTED = "REFRESH_STARTED"
EVENT_REFRESH_COMPLETED = "REFRESH_COMPLETED"
EVENT_REFRESH_FAILED = "REFRESH_FAILED"

EVENT_AGY_ELIGIBILITY_CHANGED = "AGY_ELIGIBILITY_CHANGED"


class EventBus:
    """Central thread-safe EventBus for decoupling backend state changes from UI rendering."""

    _instance: Optional[EventBus] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._listeners: Dict[str, List[Callable[[str, Any], None]]] = {}
        self._lock = threading.RLock()
        self.events_published_total: int = 0

    @classmethod
    def get(cls) -> EventBus:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def subscribe(self, event_name: str, callback: Callable[[str, Any], None]) -> None:
        """Register a callback for a specific event name or '*' for wildcard."""
        with self._lock:
            self._listeners.setdefault(event_name, []).append(callback)

    def unsubscribe(self, event_name: str, callback: Callable[[str, Any], None]) -> None:
        """Unregister a callback."""
        with self._lock:
            if event_name in self._listeners and callback in self._listeners[event_name]:
                self._listeners[event_name].remove(callback)

    def publish(self, event_name: str, data: Any = None) -> None:
        """Publish event to all registered synchronous subscribers."""
        with self._lock:
            self.events_published_total += 1
            callbacks = list(self._listeners.get(event_name, [])) + list(self._listeners.get("*", []))

        for cb in callbacks:
            try:
                cb(event_name, data)
            except Exception as e:
                logger.error("Error in EventBus listener for %s: %s", event_name, e)

    def publish_to_ui(self, root_widget: Any, event_name: str, data: Any = None) -> None:
        """Safely schedule event dispatch on the Tkinter main UI thread via root.after(0, ...)."""
        if root_widget is None:
            self.publish(event_name, data)
            return

        def _dispatch():
            self.publish(event_name, data)

        try:
            root_widget.after(0, _dispatch)
        except Exception:
            # Fallback direct invocation if root is shutting down or not standard Tk
            self.publish(event_name, data)
