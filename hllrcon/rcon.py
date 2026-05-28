"""Auto-reconnecting RCON client."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from typing_extensions import override

from hllrcon.client import RconClient
from hllrcon.connection import RconConnection
from hllrcon.exceptions import HLLConnectionClosedError, HLLConnectionError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class Rcon(RconClient):
    """An auto-reconnecting interface for an RCON server.

    This client maintains a single active connection and transparently
    re-establishes it when transient failures occur (up to
    ``reconnect_after_failures`` consecutive errors). It is safe to use from
    multiple coroutines concurrently.
    """

    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        logger: logging.Logger | None = None,
        reconnect_after_failures: int = 3,
        heartbeat_interval: float = 0.0,
    ) -> None:
        """Initialize a new `Rcon` instance.

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
        reconnect_after_failures :
            Number of consecutive failures before the connection is torn down
            and rebuilt on the next command. ``0`` disables auto-reconnect.
        heartbeat_interval :
            If > 0, passes this through to the underlying protocol.

        """
        super().__init__()
        self.host = host
        self.port = port
        self.password = password
        self.reconnect_after_failures = max(0, reconnect_after_failures)
        self.heartbeat_interval = max(0.0, float(heartbeat_interval))

        self._logger = logger
        self._connection: RconConnection | None = None
        self._failure_count = 0
        self._lock = asyncio.Lock()
        self._connecting: asyncio.Future[RconConnection] | None = None

    @property
    def logger(self) -> logging.Logger:
        return self._logger or logging.getLogger(__name__)

    @logger.setter
    def logger(self, value: logging.Logger | None) -> None:
        self._logger = value

    async def _get_connection(self) -> RconConnection:
        """Return the active connection, creating one if necessary."""
        while True:
            async with self._lock:
                if self._connection is not None and self._connection.is_connected():
                    return self._connection

                if self._connecting is None:
                    # We are the one responsible for establishing the connection.
                    self._connecting = asyncio.get_running_loop().create_future()
                    break

                # Another coroutine is already connecting — wait on its future.
                future = self._connecting

            # Await outside the lock so multiple waiters can share the same
            # connection attempt without serialising on the mutex.
            try:
                return await future
            except Exception:
                # The other attempt failed; loop around and retry.
                continue

        # We own self._connecting — perform the actual connection attempt.
        try:
            connection = await RconConnection.connect(
                host=self.host,
                port=self.port,
                password=self.password,
                logger=self._logger,
                heartbeat_interval=self.heartbeat_interval,
            )
        except Exception as exc:
            async with self._lock:
                if self._connecting is not None:
                    self._connecting.set_exception(exc)
                    self._connecting = None
            raise
        else:
            async with self._lock:
                self._connection = connection
                if self._connecting is not None:
                    self._connecting.set_result(connection)
                    self._connecting = None
                self._failure_count = 0
            return connection

    @override
    def is_connected(self) -> bool:
        conn = self._connection
        return conn is not None and conn.is_connected()

    @override
    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[None]:
        await self._get_connection()
        try:
            yield
        finally:
            self.disconnect()

    @override
    async def wait_until_connected(self) -> None:
        await self._get_connection()

    @override
    def disconnect(self) -> None:
        """Disconnect and reset all internal state.

        Idempotent.
        """
        if self._connection is not None:
            self._connection.disconnect()
        self._connection = None
        self._failure_count = 0
        if self._connecting is not None and not self._connecting.done():
            msg = "Client disconnected"
            self._connecting.set_exception(HLLConnectionClosedError(msg))
        self._connecting = None

    @override
    async def execute(
        self,
        command: str,
        version: int,
        body: str | dict[str, Any] = "",
    ) -> str:
        """Execute a command, automatically reconnecting on transient failure.

        Parameters
        ----------
        command :
            Command name.
        version :
            API version.
        body :
            Payload.

        Returns
        -------
        str
            Response body.

        """
        connection = await self._get_connection()

        try:
            result = await connection.execute(command, version, body)
        except (TimeoutError, OSError) as exc:
            self._failure_count += 1
            self.logger.debug(
                "Command %s failed (%s), failure_count=%s/%s",
                command,
                exc,
                self._failure_count,
                self.reconnect_after_failures,
            )
            if (
                self.reconnect_after_failures > 0
                and self._failure_count >= self.reconnect_after_failures
            ):
                self.disconnect()
            raise
        except HLLConnectionError:
            # Any explicit connection error also counts as a failure.
            self._failure_count += 1
            if (
                self.reconnect_after_failures > 0
                and self._failure_count >= self.reconnect_after_failures
            ):
                self.disconnect()
            raise
        else:
            # Reset failure counter on *any* successful round-trip, even if the
            # server returned a command-level error (that is handled by the caller).
            self._failure_count = 0
            return result
