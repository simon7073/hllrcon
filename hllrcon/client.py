"""Abstract base class for RCON clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class RconClient(ABC):
    """Abstract base class for auto-reconnecting RCON clients.

    Implementations must provide connection lifecycle management. High-level
    command wrappers live in :class:`hllrcon.commands.RconCommands` and its
    subclasses.
    """

    @abstractmethod
    def is_connected(self) -> bool:
        """Return ``True`` if the client is connected to the RCON server."""

    @abstractmethod
    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[None]:
        """Establish a connection, yielding once ready.

        The connection is torn down when the context manager exits.
        """
        yield

    @abstractmethod
    async def wait_until_connected(self) -> None:
        """Block until a connection has been established."""

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the RCON server."""
