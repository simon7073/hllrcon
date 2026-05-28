"""Implementation of the RCONv2 protocol for Hell Let Loose.

This module provides `RconProtocol`, a production-grade asyncio protocol handler
that manages the full connection lifecycle including:

* TCP keepalive and optional application-layer heartbeat
* Request/response correlation with monotonic per-process IDs
* Defensive buffer management (anti-DoS payload limits, sticky packet parsing)
* Fast XOR encryption/decryption via `bytearray`
* Graceful error propagation and connection state recovery
"""

from __future__ import annotations

import asyncio
import base64
import enum
import logging
import socket
import struct
import time
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from collections.abc import Callable

from typing_extensions import override

from hllrcon.exceptions import (
    HLLAuthError,
    HLLCommandError,
    HLLConnectionClosedError,
    HLLConnectionError,
    HLLConnectionLostError,
    HLLConnectionRefusedError,
    HLLConnectionTimeoutError,
    HLLMessageError,
    HLLProtocolError,
)
from hllrcon.protocol.constants import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_HEARTBEAT_TIMEOUT,
    DEFAULT_REQUEST_TIMEOUT,
    HEADER_SIZE,
    MAGIC_HEADER_BYTES,
    MAGIC_HEADER_VALUE,
    MAX_PAYLOAD_SIZE,
    RESPONSE_HEADER_FORMAT,
)
from hllrcon.protocol.request import RconRequest
from hllrcon.protocol.response import RconResponse

DEFAULT_LOGGER = logging.getLogger(__name__)


class ProtocolState(enum.Enum):
    """Connection lifecycle state machine."""

    DISCONNECTED = enum.auto()
    CONNECTING = enum.auto()
    CONNECTED = enum.auto()
    AUTHENTICATING = enum.auto()
    AUTHENTICATED = enum.auto()
    CLOSING = enum.auto()
    CLOSED = enum.auto()


class RconProtocol(asyncio.Protocol):
    """Production-grade implementation of the HLL RCONv2 protocol.

    This class extends :class:`asyncio.Protocol` to handle communication with a
    Hell Let Loose server using the RCONv2 protocol.

    Example usage:

        conn = await RconProtocol.connect(host=..., port=..., password=...)
        response = await conn.execute(
            command="KickPlayer",
            version=2,
            content_body={"PlayerId": "76561199023367826", "Reason": "Rules"},
        )
        conn.disconnect()

    You likely do not want to use this class directly. Instead, use
    :class:`hllrcon.connection.RconConnection` or :class:`hllrcon.rcon.Rcon`
    which provide higher-level interfaces.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        timeout: float | None = DEFAULT_REQUEST_TIMEOUT,
        logger: logging.Logger | None = None,
        on_connection_lost: Callable[[Exception | None], Any] | None = None,
        heartbeat_interval: float = 0.0,
        heartbeat_timeout: float = DEFAULT_HEARTBEAT_TIMEOUT,
    ) -> None:
        """Initialize a `RconProtocol` instance.

        Do not call this directly — use :meth:`connect` instead.

        Parameters
        ----------
        loop :
            The event loop used for async operations.
        timeout :
            Default timeout for individual requests (``None`` = no timeout).
        logger :
            Optional logger instance.
        on_connection_lost :
            Optional callback invoked when the connection drops. Receives the
            exception that caused the loss, or ``None`` for graceful close.
        heartbeat_interval :
            If > 0, an application-layer heartbeat will be sent every *N*
            seconds of inactivity. ``0`` disables this feature.
        heartbeat_timeout :
            Max time to wait for a heartbeat response before forcing disconnect.

        """
        self.loop = loop
        self.timeout = timeout
        self.logger = logger or DEFAULT_LOGGER
        self.on_connection_lost = on_connection_lost

        self._heartbeat_interval = max(0.0, float(heartbeat_interval))
        self._heartbeat_timeout = max(1.0, float(heartbeat_timeout))
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._last_activity = time.monotonic()

        self._transport: asyncio.Transport | None = None
        self._buffer: bytearray = bytearray()
        self._waiters: dict[int, asyncio.Future[RconResponse]] = {}
        self._state = ProtocolState.DISCONNECTED

        self.xorkey: bytes | None = None
        self.auth_token: str | None = None

    # --------------------------------------------------------------------- #
    # Connection factory
    # --------------------------------------------------------------------- #

    @classmethod
    async def connect(
        cls: type[Self],
        host: str,
        port: int,
        password: str,
        timeout: float | None = DEFAULT_REQUEST_TIMEOUT,
        loop: asyncio.AbstractEventLoop | None = None,
        logger: logging.Logger | None = None,
        on_connection_lost: Callable[[Exception | None], Any] | None = None,
        heartbeat_interval: float = 0.0,
        heartbeat_timeout: float = DEFAULT_HEARTBEAT_TIMEOUT,
    ) -> Self:
        """Establish a connection to the HLL server and authenticate.

        Parameters
        ----------
        host :
            Hostname or IP address.
        port :
            RCON port.
        password :
            Server RCON password.
        timeout :
            Per-request timeout in seconds.
        loop :
            Event loop (defaults to the running loop).
        logger :
            Optional logger.
        on_connection_lost :
            Callback for connection loss.
        heartbeat_interval :
            Application heartbeat interval (``0`` = disabled).
        heartbeat_timeout :
            Heartbeat response timeout.

        Raises
        ------
        HLLConnectionTimeoutError
            TCP connection timed out.
        HLLConnectionRefusedError
            Server actively refused the connection.
        HLLConnectionError
            Other connection-level failure.
        HLLAuthError
            Password was rejected.

        """
        loop = loop or asyncio.get_running_loop()

        def protocol_factory() -> Self:
            return cls(
                loop=loop,
                timeout=timeout,
                logger=logger,
                on_connection_lost=on_connection_lost,
                heartbeat_interval=heartbeat_interval,
                heartbeat_timeout=heartbeat_timeout,
            )

        instance: Self
        try:
            _, instance = await asyncio.wait_for(
                loop.create_connection(protocol_factory, host=host, port=port),
                timeout=DEFAULT_CONNECT_TIMEOUT,
            )
        except TimeoutError as exc:
            msg = f"Connection to {host}:{port} timed out"
            raise HLLConnectionTimeoutError(msg, host=host, port=port) from exc
        except ConnectionRefusedError as exc:
            msg = f"The server refused connection over port {port}"
            raise HLLConnectionRefusedError(msg, host=host, port=port) from exc
        except OSError as exc:
            msg = f"Failed to connect to {host}:{port}: {exc}"
            raise HLLConnectionError(msg, host=host, port=port) from exc

        instance.logger.info("Connected to %s:%s", host, port)

        try:
            await instance.authenticate(password)
        except HLLAuthError:
            instance.disconnect()
            raise

        return instance

    # --------------------------------------------------------------------- #
    # Lifecycle helpers
    # --------------------------------------------------------------------- #

    def disconnect(self) -> None:
        """Close the connection gracefully.

        Idempotent — calling this multiple times is safe.
        """
        if self._state in (ProtocolState.CLOSING, ProtocolState.CLOSED):
            return

        self._state = ProtocolState.CLOSING
        self.logger.debug("disconnect() called")

        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None

        transport = self._transport
        self._transport = None
        if transport is not None:
            transport.close()

        # Fail any outstanding waiters so coroutines don't hang forever.
        waiters = list(self._waiters.values())
        self._waiters.clear()
        exc = HLLConnectionClosedError("Connection closed by client")
        for waiter in waiters:
            if not waiter.done():
                waiter.set_exception(exc)

        self._state = ProtocolState.CLOSED
        self.logger.info("Connection closed")

    def is_connected(self) -> bool:
        """Return ``True`` if the transport exists and is not closing."""
        return self._transport is not None and not self._transport.is_closing()

    @property
    def state(self) -> ProtocolState:
        """Current protocol state."""
        return self._state

    # --------------------------------------------------------------------- #
    # asyncio.Protocol callbacks
    # --------------------------------------------------------------------- #

    @override
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        if not isinstance(transport, asyncio.Transport):
            msg = "Transport must be an instance of asyncio.Transport"
            raise TypeError(msg)

        self._transport = transport
        self._state = ProtocolState.CONNECTED
        self._buffer.clear()
        self._waiters.clear()
        self.xorkey = None
        self.auth_token = None

        # Attempt to enable TCP keepalive on the underlying socket.
        sock = transport.get_extra_info("socket")
        if sock is not None:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                if hasattr(socket, "TCP_KEEPIDLE"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                if hasattr(socket, "TCP_KEEPINTVL"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
                if hasattr(socket, "TCP_KEEPCNT"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                self.logger.debug("TCP keepalive enabled")
            except OSError as exc:
                self.logger.debug("Could not configure TCP keepalive: %s", exc)

        self.logger.info("Connection made!")

    @override
    def data_received(self, data: bytes) -> None:
        self._buffer.extend(data)
        self._read_from_buffer()

    @override
    def connection_lost(self, exc: Exception | None) -> None:
        self._transport = None
        self._state = ProtocolState.CLOSED

        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None

        # Capture and clear waiters so we don't leak futures.
        waiters = list(self._waiters.values())
        self._waiters.clear()

        if exc:
            self.logger.warning("Connection lost: %s", exc)
            err = HLLConnectionLostError(str(exc))
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_exception(err)
        else:
            self.logger.info("Connection lost (graceful)")
            err = HLLConnectionClosedError("Connection closed by server")
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_exception(err)

        if self.on_connection_lost is not None:
            try:
                self.on_connection_lost(exc)
            except Exception:
                self.logger.exception("on_connection_lost hook raised an exception")

    # --------------------------------------------------------------------- #
    # Buffer / packet parsing
    # --------------------------------------------------------------------- #

    def _read_from_buffer(self) -> None:
        while True:
            if len(self._buffer) < HEADER_SIZE:
                return

            # Fast-path: magic expected at index 0.
            if self._buffer[:4] != MAGIC_HEADER_BYTES:
                magic_idx = self._buffer.find(MAGIC_HEADER_BYTES)
                if magic_idx == -1:
                    self.logger.warning(
                        "Magic header not found in %s bytes, discarding buffer",
                        len(self._buffer),
                    )
                    self._buffer.clear()
                    return
                if magic_idx > 0:
                    self.logger.warning(
                        "Magic header not at start of buffer, skipping %s bytes",
                        magic_idx,
                    )
                    del self._buffer[:magic_idx]
                    continue  # Re-evaluate with aligned buffer.

            magic, pkt_id, pkt_len = struct.unpack(
                RESPONSE_HEADER_FORMAT,
                self._buffer[:HEADER_SIZE],
            )
            if magic != MAGIC_HEADER_VALUE:
                # Should not happen after find(), but defensively drop 1 byte.
                del self._buffer[:1]
                continue

            if pkt_len < 0 or pkt_len > MAX_PAYLOAD_SIZE:
                self.logger.error(
                    "Invalid payload length %s (max %s), dropping header",
                    pkt_len,
                    MAX_PAYLOAD_SIZE,
                )
                del self._buffer[:HEADER_SIZE]
                continue

            pkt_size = HEADER_SIZE + pkt_len
            if len(self._buffer) < pkt_size:
                return  # Incomplete packet — wait for more data.

            # Extract body, advance buffer, decrypt.
            body_bytes = bytes(self._buffer[HEADER_SIZE:pkt_size])
            del self._buffer[:pkt_size]
            decoded_body = self._xor(body_bytes)

            self.logger.debug(
                "Received packet id=%s len=%s (decoded %s bytes)",
                pkt_id,
                pkt_len,
                len(decoded_body),
            )

            try:
                pkt = RconResponse.unpack(pkt_id, decoded_body)
            except HLLProtocolError as exc:
                self.logger.exception("Failed to unpack response id=%s", pkt_id)
                waiter = self._waiters.pop(pkt_id, None)
                if waiter is not None and not waiter.done():
                    waiter.set_exception(exc)
                continue

            waiter = self._waiters.pop(pkt_id, None)
            if waiter is None:
                self.logger.warning(
                    "No waiter for packet id=%s (active waiters: %s)",
                    pkt_id,
                    list(self._waiters.keys()),
                )
            elif not waiter.done():
                waiter.set_result(pkt)

            # Loop around in case multiple packets arrived in one TCP segment.

    # --------------------------------------------------------------------- #
    # XOR cipher
    # --------------------------------------------------------------------- #

    def _xor(self, message: bytes, offset: int = 0) -> bytes:
        """Encrypt or decrypt *message* using the server-provided XOR key.

        Parameters
        ----------
        message :
            Raw bytes to transform.
        offset :
            Rotation offset into the key (used for stream continuity).

        Returns
        -------
        bytes
            Transformed bytes.

        """
        if not self.xorkey:
            return message

        key = self.xorkey
        key_len = len(key)
        out = bytearray(message)
        for i, b in enumerate(out):
            out[i] = b ^ key[(i + offset) % key_len]
        return bytes(out)

    # --------------------------------------------------------------------- #
    # Command execution
    # --------------------------------------------------------------------- #

    async def execute(
        self,
        command: str,
        version: int,
        content_body: dict[str, Any] | str = "",
    ) -> RconResponse:
        """Execute a RCON command and await the response.

        Parameters
        ----------
        command :
            Command name.
        version :
            Command API version.
        content_body :
            JSON-serializable payload or raw string.

        Raises
        ------
        HLLConnectionClosedError
            The connection is not open.
        HLLConnectionLostError
            The connection dropped while waiting.
        TimeoutError
            The request exceeded ``self.timeout``.

        """
        if not self._transport:
            msg = "Connection is closed"
            raise HLLConnectionClosedError(msg)

        request = RconRequest(
            command=command,
            version=version,
            auth_token=self.auth_token,
            content_body=content_body,
        )

        header, body = request.pack()
        message = header + self._xor(body)
        self.logger.debug("Sending id=%s cmd=%s", request.request_id, command)

        waiter: asyncio.Future[RconResponse] = self.loop.create_future()
        try:
            self._waiters[request.request_id] = waiter
            self._transport.write(message)
            self._last_activity = time.monotonic()
            response = await asyncio.wait_for(waiter, timeout=self.timeout)
        except Exception:
            # Ensure waiter is cleaned up on *any* failure path.
            self._waiters.pop(request.request_id, None)
            raise
        else:
            self._last_activity = time.monotonic()
            self.logger.debug(
                "Response id=%s cmd=%s status=%s",
                response.request_id,
                response.name,
                response.status_code,
            )
            return response
        finally:
            self._waiters.pop(request.request_id, None)

    # --------------------------------------------------------------------- #
    # Authentication
    # --------------------------------------------------------------------- #

    async def authenticate(self, password: str) -> None:
        """Authenticate with the HLL server.

        Parameters
        ----------
        password :
            RCON password.

        Raises
        ------
        HLLAuthError
            Password incorrect or handshake failed.
        HLLMessageError
            Server sent an unexpected handshake payload.

        """
        if self._state != ProtocolState.CONNECTED:
            msg = f"Cannot authenticate in state {self._state.name}"
            raise HLLConnectionError(msg)

        self._state = ProtocolState.AUTHENTICATING
        self.logger.debug("Starting authentication handshake...")

        try:
            xorkey_resp = await self.execute("ServerConnect", 2, "")
            xorkey_resp.raise_for_status()
        except Exception as exc:
            self._state = ProtocolState.CONNECTED
            msg = f"ServerConnect handshake failed: {exc}"
            raise HLLAuthError(msg) from exc

        if not isinstance(xorkey_resp.content_body, str):
            self._state = ProtocolState.CONNECTED
            msg = "ServerConnect response content_body is not a string"
            raise HLLMessageError(msg)

        try:
            self.xorkey = base64.b64decode(xorkey_resp.content_body)
        except Exception as exc:
            self._state = ProtocolState.CONNECTED
            msg = f"Invalid xorkey base64: {exc}"
            raise HLLMessageError(msg) from exc

        try:
            auth_resp = await self.execute("Login", 2, password)
            auth_resp.raise_for_status()
        except HLLCommandError as exc:
            self._state = ProtocolState.CONNECTED
            self.xorkey = None
            msg = "Authentication failed: incorrect password"
            raise HLLAuthError(msg) from exc
        except Exception as exc:
            self._state = ProtocolState.CONNECTED
            self.xorkey = None
            msg = f"Login handshake failed: {exc}"
            raise HLLAuthError(msg) from exc

        self.auth_token = auth_resp.content_body
        self._state = ProtocolState.AUTHENTICATED
        self.logger.info("Authenticated successfully")

        if self._heartbeat_interval > 0:
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(),
                name=f"hllrcon-heartbeat-{id(self)}",
            )

    # --------------------------------------------------------------------- #
    # Heartbeat / keepalive
    # --------------------------------------------------------------------- #

    async def _heartbeat_loop(self) -> None:
        """Background task that sends lightweight probes during idle periods."""
        while self.is_connected():
            try:
                await asyncio.sleep(self._heartbeat_interval)
            except asyncio.CancelledError:
                return

            if not self.is_connected():
                return

            idle = time.monotonic() - self._last_activity
            if idle < self._heartbeat_interval:
                continue

            self.logger.debug("Sending application heartbeat")
            try:
                await asyncio.wait_for(
                    self.execute(
                        "GetServerInformation",
                        2,
                        {"Name": "serverconfig", "Value": ""},
                    ),
                    timeout=self._heartbeat_timeout,
                )
            except Exception:
                self.logger.warning(
                    "Heartbeat failed after %.1fs idle — disconnecting",
                    idle,
                )
                self.disconnect()
                return
