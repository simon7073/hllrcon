"""RCONv2 request encoding."""

from __future__ import annotations

import json
import struct
import threading
from typing import Any, ClassVar

from hllrcon.protocol.constants import (
    HEADER_SIZE,
    MAGIC_HEADER_VALUE,
    MAX_PAYLOAD_SIZE,
    REQUEST_HEADER_FORMAT,
)


class RconRequest:
    """Represents a single RCON request."""

    # Per-process counter protected by a lock so that multiple concurrent
    # protocol instances (or threads in the sync wrapper) never reuse IDs.
    _lock: ClassVar[threading.Lock] = threading.Lock()
    _next_id: ClassVar[int] = 0

    def __init__(
        self,
        command: str,
        version: int,
        auth_token: str | None,
        content_body: dict[str, Any] | str = "",
    ) -> None:
        """Initialize a new RCON request.

        Parameters
        ----------
        command : str
            The command to be executed.
        version : int
            The version of the command.
        auth_token : str | None
            The authentication token for the RCON connection.
        content_body : dict[str, Any] | str, optional
            An additional payload to send along with the command. Must be
            JSON-serializable.

        """
        self.name = command
        self.version = version
        self.auth_token = auth_token
        self.content_body = content_body
        with self._lock:
            request_id = RconRequest._next_id
            RconRequest._next_id = (RconRequest._next_id + 1) & 0xFFFFFFFF
        self.request_id: int = request_id

    def pack(self) -> tuple[bytes, bytes]:
        """Pack the request into header and body bytes.

        Returns
        -------
        tuple[bytes, bytes]
            A tuple containing the header and body of the request.

        Raises
        ------
        ValueError
            If the encoded body exceeds `MAX_PAYLOAD_SIZE`.

        """
        body = {
            "authToken": self.auth_token or "",
            "version": self.version,
            "name": self.name,
            "contentBody": (
                self.content_body
                if isinstance(self.content_body, str)
                else json.dumps(self.content_body, separators=(",", ":"), ensure_ascii=False)
            ),
        }
        body_encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

        if len(body_encoded) > MAX_PAYLOAD_SIZE:
            msg = f"Request body size {len(body_encoded)} exceeds maximum {MAX_PAYLOAD_SIZE}"
            raise ValueError(msg)

        header = struct.pack(
            REQUEST_HEADER_FORMAT,
            MAGIC_HEADER_VALUE,
            self.request_id,
            len(body_encoded),
        )
        return header, body_encoded
