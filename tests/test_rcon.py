"""Tests for `hllrcon.rcon`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any
from unittest import mock

import pytest
from hllrcon.connection import RconConnection
from hllrcon.exceptions import HLLConnectionClosedError, HLLError
from hllrcon.rcon import Rcon

pytestmark = pytest.mark.asyncio


@pytest.fixture
def connection() -> mock.Mock:
    mock_connection = mock.Mock(spec=RconConnection)
    mock_connection.is_connected.return_value = True
    return mock_connection


@pytest.fixture
def connection2() -> mock.Mock:
    mock_connection = mock.Mock(spec=RconConnection)
    mock_connection.is_connected.return_value = True
    return mock_connection


@pytest.fixture
def rcon(monkeypatch: pytest.MonkeyPatch, connection: mock.Mock) -> Rcon:
    async def get_connection(*_args: Any, **_kwargs: Any) -> RconConnection:
        return connection  # type: ignore[return-value]

    monkeypatch.setattr("hllrcon.rcon.RconConnection.connect", get_connection)
    return Rcon(host="localhost", port=1234, password="password")


async def test_logger(rcon: Rcon) -> None:
    assert rcon.logger.name == "hllrcon.rcon"
    rcon.logger = logging.getLogger("test")
    assert rcon.logger.name == "test"
    rcon.logger = None
    assert rcon.logger.name == "hllrcon.rcon"


async def test_get_connection_new(rcon: Rcon, connection: mock.Mock) -> None:
    assert await rcon._get_connection() == connection


async def test_get_connection_reuse(
    rcon: Rcon,
    connection2: mock.Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate an already-active connection.
    rcon._connection = connection2
    assert await rcon._get_connection() == connection2


async def test_get_connection_disconnected(
    rcon: Rcon,
    connection: mock.Mock,
    connection2: mock.Mock,
) -> None:
    rcon._connection = connection2
    connection2.is_connected.return_value = False
    assert await rcon._get_connection() == connection


async def test_get_connection_wait(
    rcon: Rcon,
    connection2: mock.Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Test that concurrent callers share the same in-flight connection attempt.
    async def delayed_connect(*_args: Any, **_kwargs: Any) -> RconConnection:
        await asyncio.sleep(0.05)
        return connection2  # type: ignore[return-value]

    monkeypatch.setattr("hllrcon.rcon.RconConnection.connect", delayed_connect)

    assert await rcon._get_connection() == connection2
    assert rcon._connection == connection2


async def test_get_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
    rcon: Rcon,
    connection: mock.Mock,
) -> None:
    async def get_connection(*_args: Any, **_kwargs: Any) -> RconConnection:
        msg = "Connection failed"
        raise HLLError(msg)

    monkeypatch.setattr("hllrcon.rcon.RconConnection.connect", get_connection)

    with pytest.raises(HLLError, match="Connection failed"):
        await rcon._get_connection()

    # After failure, next call should retry.
    monkeypatch.setattr(
        "hllrcon.rcon.RconConnection.connect",
        mock.AsyncMock(return_value=connection),
    )
    assert await rcon._get_connection() == connection


async def test_is_connected(rcon: Rcon, connection: mock.Mock) -> None:
    assert rcon.is_connected() is False, "Should be disconnected initially"

    await rcon.wait_until_connected()
    assert rcon.is_connected() is True, "Should be connected after getting connection"

    connection.is_connected.return_value = False
    assert rcon.is_connected() is False, "Should be disconnected after connection loss"


async def test_enter_exit(rcon: Rcon, connection: mock.Mock) -> None:
    assert rcon._connection is None, "Initial connection should be None"

    async with rcon.connect():
        assert rcon._connection is not None, "Connection should be established"

    connection.disconnect.assert_called_once()
    assert rcon._connection is None, "Connection should be reset after exit"

    connection.disconnect.reset_mock()

    with contextlib.suppress(RuntimeError):
        async with rcon.connect():
            assert rcon._connection is not None, "Connection should be established again"
            raise RuntimeError

    connection.disconnect.assert_called_once()
    assert rcon._connection is None, "Connection should be reset after error"


async def test_execute(rcon: Rcon, connection: mock.Mock) -> None:
    command = "command"
    version = 2
    body = "body"
    response = "response"

    connection.execute.return_value = response
    result = await rcon.execute(command, version, body)
    assert result == response


async def test_reconnect_after_failures_parameter() -> None:
    rcon = Rcon(host="localhost", port=1234, password="password")
    assert rcon.reconnect_after_failures == 3

    rcon = Rcon(
        host="localhost",
        port=1234,
        password="password",
        reconnect_after_failures=5,
    )
    assert rcon.reconnect_after_failures == 5

    rcon = Rcon(
        host="localhost",
        port=1234,
        password="password",
        reconnect_after_failures=0,
    )
    assert rcon.reconnect_after_failures == 0

    rcon = Rcon(
        host="localhost",
        port=1234,
        password="password",
        reconnect_after_failures=-1,
    )
    assert rcon.reconnect_after_failures == 0


async def test_failure_count_increment_on_timeout(
    rcon: Rcon,
    connection: mock.Mock,
) -> None:
    connection.execute.side_effect = TimeoutError("Connection timeout")

    with pytest.raises(TimeoutError, match="Connection timeout"):
        await rcon.execute("test_command", 1, "")
    assert rcon._failure_count == 1

    with pytest.raises(TimeoutError, match="Connection timeout"):
        await rcon.execute("test_command", 1, "")
    assert rcon._failure_count == 2


async def test_failure_count_increment_on_os_error(
    rcon: Rcon,
    connection: mock.Mock,
) -> None:
    connection.execute.side_effect = OSError("Network error")

    with pytest.raises(OSError, match="Network error"):
        await rcon.execute("test_command", 1, "")
    assert rcon._failure_count == 1


async def test_failure_count_reset_on_disconnect(rcon: Rcon) -> None:
    rcon._failure_count = 5
    rcon.disconnect()
    assert rcon._failure_count == 0


async def test_reconnect_after_failures_disabled(
    monkeypatch: pytest.MonkeyPatch,
    connection: mock.Mock,
) -> None:
    async def get_connection(*_args: Any, **_kwargs: Any) -> RconConnection:
        return connection  # type: ignore[return-value]

    monkeypatch.setattr("hllrcon.rcon.RconConnection.connect", get_connection)
    rcon = Rcon(
        host="localhost",
        port=1234,
        password="password",
        reconnect_after_failures=0,
    )

    connection.execute.side_effect = TimeoutError("Connection timeout")

    for i in range(5):
        with pytest.raises(TimeoutError, match="Connection timeout"):
            await rcon.execute("test_command", 1, "")
        assert rcon._failure_count == i + 1
        assert rcon._connection is not None


async def test_reconnect_after_failures_triggers_disconnect(
    monkeypatch: pytest.MonkeyPatch,
    connection: mock.Mock,
) -> None:
    async def get_connection(*_args: Any, **_kwargs: Any) -> RconConnection:
        return connection  # type: ignore[return-value]

    monkeypatch.setattr("hllrcon.rcon.RconConnection.connect", get_connection)
    rcon = Rcon(
        host="localhost",
        port=1234,
        password="password",
        reconnect_after_failures=2,
    )

    await rcon.wait_until_connected()
    connection.execute.side_effect = TimeoutError("Connection timeout")

    with pytest.raises(TimeoutError, match="Connection timeout"):
        await rcon.execute("test_command", 1, "")
    assert rcon._failure_count == 1
    assert rcon._connection is not None

    with pytest.raises(TimeoutError, match="Connection timeout"):
        await rcon.execute("test_command", 1, "")
    assert rcon._failure_count == 0
    assert rcon._connection is None


async def test_failure_count_reset_on_success(
    rcon: Rcon,
    connection: mock.Mock,
) -> None:
    rcon._failure_count = 5
    connection.execute.return_value = "success"

    result = await rcon.execute("test_command", 1, "")
    assert result == "success"
    assert rcon._failure_count == 0


async def test_failure_count_different_exceptions(
    rcon: Rcon,
    connection: mock.Mock,
) -> None:
    connection.execute.side_effect = ValueError("Some other error")
    with pytest.raises(ValueError, match="Some other error"):
        await rcon.execute("test_command", 1, "")
    assert rcon._failure_count == 0

    connection.execute.side_effect = TimeoutError("Timeout")
    with pytest.raises(TimeoutError, match="Timeout"):
        await rcon.execute("test_command", 1, "")
    assert rcon._failure_count == 1

    connection.execute.side_effect = OSError("OS Error")
    with pytest.raises(OSError, match="OS Error"):
        await rcon.execute("test_command", 1, "")
    assert rcon._failure_count == 2


async def test_reconnect_threshold_exact_match(
    monkeypatch: pytest.MonkeyPatch,
    connection: mock.Mock,
) -> None:
    async def get_connection(*_args: Any, **_kwargs: Any) -> RconConnection:
        return connection  # type: ignore[return-value]

    monkeypatch.setattr("hllrcon.rcon.RconConnection.connect", get_connection)
    rcon = Rcon(
        host="localhost",
        port=1234,
        password="password",
        reconnect_after_failures=3,
    )

    await rcon.wait_until_connected()
    connection.execute.side_effect = TimeoutError("Connection timeout")

    for i in range(2):
        with pytest.raises(TimeoutError, match="Connection timeout"):
            await rcon.execute("test_command", 1, "")
        assert rcon._failure_count == i + 1
        assert rcon._connection is not None

    with pytest.raises(TimeoutError, match="Connection timeout"):
        await rcon.execute("test_command", 1, "")
    assert rcon._failure_count == 0
    assert rcon._connection is None
