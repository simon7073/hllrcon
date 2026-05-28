"""High-level connection wrapper around :class:`RconProtocol`."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from typing_extensions import override

from hllrcon.commands import RconCommands
from hllrcon.exceptions import HLLConnectionClosedError, HLLConnectionLostError
from hllrcon.protocol.protocol import RconProtocol

if TYPE_CHECKING:
    from collections.abc import Callable


class RconConnection(RconCommands):
    """A managed connection to an RCON server.

    `RconConnection` instances are single-use. Once disconnected they cannot be
    reused. For a client that automatically reconnects on failure, use
    :class:`hllrcon.rcon.Rcon` instead.
    """

    def __init__(self, protocol: RconProtocol) -> None:
        self._protocol = protocol
        self._disconnect_event: asyncio.Event = asyncio.Event()
        self._disconnect_event.set()
        self.on_disconnect: Callable[[], None] = lambda: None

    def is_connected(self) -> bool:
        """Return ``True`` if the underlying protocol is connected."""
        return self._protocol.is_connected()

    def disconnect(self) -> None:
        """Disconnect from the RCON server."""
        self._protocol.disconnect()

    def _on_disconnect(self, _: Exception | None) -> None:
        """Internal callback forwarded to ``protocol.on_connection_lost``."""
        self._disconnect_event.set()
        try:
            self.on_disconnect()
        except Exception:
            # Swallow user callback errors to avoid breaking protocol cleanup.
            pass

    async def wait_until_disconnected(self) -> None:
        """Block until the connection closes."""
        await self._disconnect_event.wait()

    @classmethod
    async def connect(
        cls,
        host: str,
        port: int,
        password: str,
        logger: logging.Logger | None = None,
        timeout: float | None = 10.0,
        heartbeat_interval: float = 0.0,
    ) -> "RconConnection":
        """Connect to the RCON server.

        Parameters
        ----------
        host :
            Hostname or IP address.
        port :
            RCON port.
        password :
            Server password.
        logger :
            Optional logger.
        timeout :
            Per-request timeout.
        heartbeat_interval :
            If > 0, sends lightweight heartbeat commands during idle periods.

        """
        protocol = await RconProtocol.connect(
            host=host,
            port=port,
            password=password,
            logger=logger,
            timeout=timeout,
            heartbeat_interval=heartbeat_interval,
        )
        self = cls(protocol)
        self._disconnect_event.clear()
        protocol.on_connection_lost = self._on_disconnect
        return self

    @override
    async def execute(
        self,
        command: str,
        version: int,
        body: str | dict[str, Any] = "",
    ) -> str:
        """Execute a command and return the response body as a string.

        Raises
        ------
        HLLConnectionLostError
            If the connection has already been lost.
        HLLCommandError
            If the server returns a non-OK status.

        """
        if self._disconnect_event.is_set() and not self._protocol.is_connected():
            raise HLLConnectionLostError("Connection has been lost")

        response = await self._protocol.execute(command, version, body)
        response.raise_for_status()
        return response.content_body
