"""Connector registry.

Usage from inside a connector module:

    from src.connectors.base import BaseConnector
    from src.connectors.registry import register

    @register
    class MyConnector(BaseConnector):
        name = "my_tool"
        ...

The decorator instantiates the class once and stores it. The orchestrator
then queries the registry:

    from src.connectors.registry import registry
    connectors = registry.connectors_for(DataType.EMAIL)
"""
from __future__ import annotations

from typing import TypeVar

from src.connectors.base import BaseConnector
from src.db.types import DataType

T = TypeVar("T", bound=BaseConnector)


class _Registry:
    def __init__(self) -> None:
        self._by_name: dict[str, BaseConnector] = {}

    def register(self, cls: type[T]) -> type[T]:
        # Sanity-check the subclass declared the required ClassVars.
        for attr in ("name", "display_name", "category", "input_types", "output_types"):
            if not hasattr(cls, attr):
                raise TypeError(
                    f"Connector {cls.__name__} is missing required attribute {attr!r}"
                )
        instance = cls()  # Connectors are stateless → single instance is fine.
        if instance.name in self._by_name:
            raise ValueError(f"Duplicate connector name: {instance.name!r}")
        self._by_name[instance.name] = instance
        return cls

    def get(self, name: str) -> BaseConnector | None:
        return self._by_name.get(name)

    def all(self) -> list[BaseConnector]:
        return list(self._by_name.values())

    def connectors_for(self, data_type: DataType) -> list[BaseConnector]:
        """Return every registered connector that accepts `data_type` as input."""
        return [c for c in self._by_name.values() if c.accepts(data_type)]


registry = _Registry()


def register(cls: type[T]) -> type[T]:
    """Class decorator — see module docstring."""
    return registry.register(cls)
