"""Synchronous wrapper around the asynchronous :class:`hllrcon.rcon.Rcon`.

The synchronous client runs an asyncio event loop in a dedicated daemon thread.
All operations are marshalled to that thread via
:func:`asyncio.run_coroutine_threadsafe`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from typing_extensions import override

from hllrcon.rcon import Rcon
from hllrcon.sync.commands import SyncRconCommands

if TYPE_CHECKING:
    from collections.abc import Generator
    from concurrent.futures import Future


class SyncRcon(SyncRconCommands):
    """A synchronous interface for connecting to an RCON server.

    Internally this wraps :class:`Rcon` running in a background thread with its
    own event loop. All methods block the calling thread until the result is
    available.
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
        """Initialize a new `SyncRcon` instance.

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
            Passed through to the underlying :class:`Rcon`.
        heartbeat_interval :
            Passed through to the underlying :class:`Rcon`.

        """
        self._logger = logger
        self._rcon = Rcon(
            host,
            port,
            password,
            logger=logger,
            reconnect_after_failures=reconnect_after_failures,
            heartbeat_interval=heartbeat_interval,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()

    # --------------------------------------------------------------------- #
    # Properties
    # --------------------------------------------------------------------- #

    @property
    def host(self) -> str:
        return self._rcon.host

    @host.setter
    def host(self, value: str) -> None:
        self._rcon.host = value

    @property
    def port(self) -> int:
        return self._rcon.port

    @port.setter
    def port(self, value: int) -> None:
        self._rcon.port = value

    @property
    def password(self) -> str:
        return self._rcon.password

    @password.setter
    def password(self, value: str) -> None:
        self._rcon.password = value

    @property
    def logger(self) -> logging.Logger:
        return self._logger or logging.getLogger(__name__)

    @logger.setter
    def logger(self, value: logging.Logger | None) -> None:
        self._logger = value
        self._rcon.logger = value

    @property
    def reconnect_after_failures(self) -> int:
        return self._rcon.reconnect_after_failures

    @reconnect_after_failures.setter
    def reconnect_after_failures(self, value: int) -> None:
        self._rcon.reconnect_after_failures = value

    # --------------------------------------------------------------------- #
    # Connection management
    # --------------------------------------------------------------------- #

    def is_connected(self) -> bool:
        """Return ``True`` if the loop is running and the client is connected."""
        return (
            self._loop is not None
            and self._loop.is_running()
            and self._rcon.is_connected()
        )

    @contextmanager
    def connect(self) -> Generator[None]:
        """Establish a connection and yield, tearing it down on exit."""
        self.wait_until_connected()
        try:
            yield
        finally:
            self.disconnect()

    def wait_until_connected(self) -> None:
        """Ensure the background event loop and connection are ready."""
        if self._loop is not None and self._loop.is_running():
            self._run_coroutine(self._rcon.wait_until_connected()).result()
            return

        self._shutdown_event.clear()
        ready_event = threading.Event()

        def target() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            loop.call_soon(ready_event.set)
            try:
                loop.run_forever()
            finally:
                # Drain any remaining tasks before closing.
                with contextlib.suppress(Exception):
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True),
                        )
                loop.close()
                self._loop = None

        self._thread = threading.Thread(
            target=target,
            name=f"SyncRconThread-{id(self)}",
            daemon=True,
        )
        self._thread.start()

        if not ready_event.wait(timeout=5.0):
            self.disconnect()
            msg = "Background event loop failed to start within 5 seconds"
            raise RuntimeError(msg)

        self._run_coroutine(self._rcon.wait_until_connected()).result()

    def disconnect(self) -> None:
        """Disconnect and stop the background thread."""
        if self._loop is not None and self._loop.is_running():
            with contextlib.suppress(Exception):
                self._run_coroutine(self._rcon.disconnect())
            # Schedule loop.stop from inside the loop so it exits run_forever().
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        self._loop = None
        self._thread = None
        self._shutdown_event.set()

    def execute_concurrently(
        self,
        command: str,
        version: int,
        body: str | dict[str, Any] = "",
    ) -> Future[str]:
        """Schedule a command for execution and return a :class:`Future`.

        This is the only way to execute commands concurrently from multiple
        threads — each call returns immediately with a future that completes
        when the response arrives.

        """
        self.wait_until_connected()
        return self._run_coroutine(
            self._rcon.execute(command, version, body),
            block=False,
        )

    @override
    def execute(
        self,
        command: str,
        version: int,
        body: str | dict[str, Any] = "",
    ) -> str:
        """Execute a command and block until the response arrives."""
        return self.execute_concurrently(command, version, body).result()

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _run_coroutine(
        self,
        coro: Any,
        *,
        block: bool = True,
    ) -> Future[str]:
        """Marshal *coro* to the background loop.

        Parameters
        ----------
        coro :
            The awaitable to run.
        block :
            If ``True`` this method returns the raw
            :class:`concurrent.futures.Future` and the caller must call
            ``.result()``.

        """
        if self._loop is None or not self._loop.is_running():
            msg = "Background event loop is not running"
            raise RuntimeError(msg)

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        if block:
            return future
        return future
