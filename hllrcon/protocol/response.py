"""RCONv2 response decoding."""

from __future__ import annotations

import json
from enum import IntEnum
from typing import Any, Self

from hllrcon.exceptions import HLLCommandError, HLLMessageError, HLLProtocolError


class RconResponseStatus(IntEnum):
    """Enumeration of RCON response status codes."""

    OK = 200
    """The request was successful."""

    BAD_REQUEST = 400
    """The request was invalid."""

    UNAUTHORIZED = 401
    """Insufficient or invalid authorization."""

    INTERNAL_ERROR = 500
    """An internal server error occurred."""


class RconResponse:
    """Represents a single RCON response."""

    __slots__ = (
        "request_id",
        "name",
        "version",
        "status_code",
        "status_message",
        "content_body",
    )

    def __init__(
        self,
        request_id: int,
        command: str,
        version: int,
        status_code: RconResponseStatus,
        status_message: str,
        content_body: str,
    ) -> None:
        """Initialize a new RCON response.

        Parameters
        ----------
        request_id : int
            The ID of the request this response corresponds to.
        command : str
            The command that was executed.
        version : int
            The version of the command.
        status_code : RconResponseStatus
            The status code of the response.
        status_message : str
            A message describing the status of the response.
        content_body : str
            The body of the response, potentially JSON-deserializable.

        """
        self.request_id = request_id
        self.name = command
        self.version = version
        self.status_code = status_code
        self.status_message = status_message
        self.content_body = content_body

    @property
    def content_dict(self) -> dict[str, Any]:
        """JSON-deserialize the content body of the response.

        Raises
        ------
        json.JSONDecodeError
            The content body could not be deserialized.
        TypeError
            The deserialized content is not a dictionary.

        Returns
        -------
        dict[str, Any]
            The deserialized content body as a dictionary.

        """
        parsed_content = json.loads(self.content_body)
        if not isinstance(parsed_content, dict):
            msg = f"Expected JSON content to be a dict, got {type(parsed_content)}"
            raise TypeError(msg)
        return parsed_content

    def __str__(self) -> str:
        content: str | dict[str, Any]
        try:
            content = self.content_dict
        except (json.JSONDecodeError, TypeError):
            content = self.content_body
        return f"{self.status_code} {self.name} {content}"

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} id={self.request_id} "
            f"cmd={self.name!r} status={self.status_code}>"
        )

    @classmethod
    def unpack(cls, request_id: int, body_encoded: bytes) -> Self:
        """Unpack a RCON response from its bytes representation.

        Parameters
        ----------
        request_id : int
            The ID of the request this response corresponds to.
        body_encoded : bytes
            The encoded body of the response, expected to be a UTF-8 JSON string.

        Returns
        -------
        RconResponse
            The unpacked RCON response object.

        Raises
        ------
        HLLProtocolError
            If the payload is not valid JSON or is missing required fields.
        HLLMessageError
            If a required field is of an unexpected type.

        """
        try:
            body = json.loads(body_encoded)
        except json.JSONDecodeError as exc:
            msg = f"Failed to decode response JSON: {exc}"
            raise HLLProtocolError(msg) from exc

        if not isinstance(body, dict):
            msg = f"Response body must be a JSON object, got {type(body).__name__}"
            raise HLLMessageError(msg)

        def _get(key: str, expected_type: type) -> Any:
            value = body.get(key)
            if value is None:
                msg = f"Missing required field '{key}' in response"
                raise HLLProtocolError(msg)
            if not isinstance(value, expected_type):
                msg = (
                    f"Field '{key}' expected {expected_type.__name__}, "
                    f"got {type(value).__name__}"
                )
                raise HLLMessageError(msg)
            return value

        try:
            status_code = RconResponseStatus(int(_get("statusCode", (int, float))))
        except ValueError as exc:
            msg = f"Invalid statusCode in response: {exc}"
            raise HLLProtocolError(msg) from exc

        return cls(
            request_id=request_id,
            command=str(_get("name", str)),
            version=int(_get("version", (int, float))),
            status_code=status_code,
            status_message=str(_get("statusMessage", str)),
            content_body=body.get("contentBody", ""),
        )

    def raise_for_status(self) -> None:
        """Raise an exception if the response status is not OK.

        Raises
        ------
        HLLCommandError
            The response status code is not `RconResponseStatus.OK`.

        """
        if self.status_code != RconResponseStatus.OK:
            raise HLLCommandError(
                self.status_code,
                self.status_message,
                command=self.name,
                response_body=self.content_body,
            )
