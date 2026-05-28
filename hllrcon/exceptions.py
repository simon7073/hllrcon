"""HLL RCON exception hierarchy.

All exceptions raised by the library derive from `HLLError`. The hierarchy is
intentionally flat enough to be usable, but detailed enough to allow fine-grained
error handling in production code.
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "HLLError",
    "HLLAuthError",
    "HLLCommandError",
    "HLLConnectionClosedError",
    "HLLConnectionError",
    "HLLConnectionLostError",
    "HLLConnectionRefusedError",
    "HLLConnectionTimeoutError",
    "HLLMessageError",
    "HLLProtocolError",
    "HLLRconWarning",
)


class HLLError(Exception):
    """Base exception for all HLL-related errors."""


class HLLCommandError(HLLError):
    """Raised when the game server returns an error for a request."""

    def __init__(
        self,
        status_code: int,
        *args: object,
        command: str | None = None,
        response_body: str | None = None,
    ) -> None:
        """Initialize a new `HLLCommandError` instance.

        Parameters
        ----------
        status_code : int
            The status code returned by the server.
        *args : object
            Additional arguments to pass to the base exception.
        command : str | None, optional
            The command that caused the error, for diagnostic context.
        response_body : str | None, optional
            The raw response body, for diagnostic context.

        """
        self.status_code = status_code
        self.command = command
        self.response_body = response_body
        super().__init__(*args)

    def __str__(self) -> str:
        """Return a string representation of the error."""
        exc_str = super().__str__()
        header = f"({self.status_code})"
        parts = [header, exc_str]
        if self.command:
            parts.append(f"[command={self.command}]")
        return " ".join(p for p in parts if p).rstrip()


class HLLMessageError(HLLError):
    """Raised when the game server returns an unexpected value."""


class HLLProtocolError(HLLError):
    """Raised when a low-level protocol invariant is violated.

    Examples include malformed packets, missing magic headers, or payload length
    mismatches.
    """


class HLLConnectionError(HLLError):
    """Generic error for connection errors."""

    def __init__(
        self,
        *args: object,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self.host = host
        self.port = port
        super().__init__(*args)


class HLLConnectionRefusedError(HLLConnectionError):
    """Raised when the connection is refused."""


class HLLConnectionTimeoutError(HLLConnectionError):
    """Raised when a connection or request times out."""


class HLLAuthError(HLLConnectionError):
    """Raised for failed authentication."""


class HLLConnectionClosedError(HLLConnectionError):
    """Raised when the connection is closed gracefully."""


class HLLConnectionLostError(HLLConnectionClosedError):
    """Raised when the connection to the server is unexpectedly lost."""


class HLLRconWarning(UserWarning):
    """Base warning for all warnings emitted by the hllrcon library."""
