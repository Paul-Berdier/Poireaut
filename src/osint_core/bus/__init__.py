"""Async event bus — collectors publish discovered entities, others subscribe."""

from osint_core.bus.dispatcher import EventBus, Handler
from osint_core.bus.events import EntityDiscovered

__all__ = ["EntityDiscovered", "EventBus", "Handler"]
