"""Tests for `hllrcon.connection`."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest import mock

import pytest
import pytest_asyncio
from hllrcon.connection import RconConnection
from hllrcon.exceptions import HLLConnectionLostError
from hllrcon.protocol.protocol import RconProtocol
from hllrcon.protocol.response import RconResponse, RconResponseStatus


@pytest.fixture
def protocol() -> mock.Mock:
    """Mock RconProtocol with connection loss simulation."""
    mock_protocol = mock.Mock(spec=RconProtocol)

    def connection_lost(exc: Exception | None) -> None:
        mock_protocol.is_connected.return_value = False
        if mock_protocol.on_connection_lost:
            mock_protocol.on_connection_lost(exc)

    mock_protocol.is_connected.return_value = True
    mock_protocol.connection_lost = connection_lost
    return mock_protocol


@pytest_asyncio.fixture
async def connection(
    monkeypatch: pytest.MonkeyPatch,
    protocol: mock.Mock,
) -> RconConnection:
    monkeypatch.setattr(
        RconProtocol,
        "connect",
        mock.AsyncMock(return_value=protocol),
    )
    return await RconConnection.connect("localhost", 1234, "password")


@pytest.mark.asyncio
async def test_is_connected(connection: RconConnection, protocol: mock.Mock) -> None:
    assert connection.is_connected() is True
    protocol.connection_lost(None)
    assert connection.is_connected() is False


@pytest.mark.asyncio
async def test_disconnect(connection: RconConnection, protocol: mock.Mock) -> None:
    with pytest.raises(asyncio.TimeoutError):
        async with asyncio.timeout(0.1):
            await connection.wait_until_disconnected()

    connection.disconnect()
    protocol.disconnect.assert_called_once()
    protocol.connection_lost(None)

    async with asyncio.timeout(0.1):
        await connection.wait_until_disconnected()


@pytest.mark.asyncio
async def test_execute(connection: RconConnection, protocol: mock.Mock) -> None:
    protocol.execute.return_value = RconResponse(
        request_id=1,
        command="test_command",
        version=1,
        status_code=RconResponseStatus.OK,
        status_message="OK",
        content_body="response",
    )
    result = await connection.execute("test_command", 1, "test_body")
    assert result == "response"

    protocol.connection_lost(None)
    with pytest.raises(HLLConnectionLostError):
        await connection.execute("test_command", 1, "test_body")
