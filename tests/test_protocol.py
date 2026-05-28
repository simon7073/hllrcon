"""Tests for `hllrcon.protocol.protocol`."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from typing import Any
from unittest.mock import Mock

import pytest
import pytest_asyncio
from hllrcon.exceptions import (
    HLLAuthError,
    HLLConnectionClosedError,
    HLLConnectionLostError,
    HLLConnectionRefusedError,
    HLLConnectionTimeoutError,
    HLLMessageError,
    HLLProtocolError,
)
from hllrcon.protocol.constants import MAGIC_HEADER_BYTES
from hllrcon.protocol.protocol import ProtocolState, RconProtocol
from hllrcon.protocol.request import RconRequest
from hllrcon.protocol.response import RconResponse, RconResponseStatus
from pytest_mock import MockerFixture

magic = MAGIC_HEADER_BYTES


@pytest.fixture
def transport(mocker: MockerFixture) -> Mock:
    t = mocker.Mock(spec=asyncio.Transport)
    t.is_closing.return_value = False
    return t


@pytest_asyncio.fixture
async def protocol(transport: Mock, mocker: MockerFixture) -> RconProtocol:
    """Create a protocol instance wired to *transport* with request IDs reset."""
    p = RconProtocol(asyncio.get_running_loop(), timeout=1.0)
    p.connection_made(transport)
    # Reset the per-process request id counter so tests are deterministic.
    mocker.patch.object(RconRequest, "_next_id", 0)
    return p


def test_is_connected(protocol: RconProtocol, transport: Mock) -> None:
    assert protocol.is_connected() is True

    transport.is_closing.return_value = True
    assert protocol.is_connected() is False

    protocol._transport = None
    assert protocol.is_connected() is False


@pytest.mark.asyncio
async def test_connect_timeout(mocker: MockerFixture) -> None:
    loop = asyncio.get_running_loop()
    mocker.patch.object(
        loop,
        "create_connection",
        side_effect=TimeoutError,
    )
    with pytest.raises(HLLConnectionTimeoutError, match=r"timed out"):
        await RconProtocol.connect("localhost", 1234, "pw")


@pytest.mark.asyncio
async def test_connect_refused(mocker: MockerFixture) -> None:
    loop = asyncio.get_running_loop()
    mocker.patch.object(
        loop,
        "create_connection",
        side_effect=ConnectionRefusedError,
    )
    with pytest.raises(HLLConnectionRefusedError, match=r"refused"):
        await RconProtocol.connect("localhost", 1234, "pw")


@pytest.mark.asyncio
async def test_connect_authentication_failure(mocker: MockerFixture) -> None:
    """If auth fails the protocol must be cleaned up and HLLAuthError raised."""
    proto = RconProtocol(asyncio.get_running_loop(), timeout=1.0)
    mocker.patch.object(proto, "authenticate", side_effect=HLLAuthError("bad pw"))

    loop = asyncio.get_running_loop()
    mocker.patch.object(loop, "create_connection", return_value=(None, proto))

    with pytest.raises(HLLAuthError):
        await RconProtocol.connect("localhost", 1234, "bad")
    assert proto._transport is None or not proto.is_connected()


def test_disconnect_idempotent(protocol: RconProtocol, transport: Mock) -> None:
    protocol.disconnect()
    transport.close.assert_called_once()
    # Second call must not raise.
    protocol.disconnect()


def test_connection_made_bad_transport(protocol: RconProtocol) -> None:
    with pytest.raises(TypeError, match=r"asyncio\.Transport"):
        protocol.connection_made(Mock(spec=asyncio.BaseTransport))


def test_data_received_appends_to_buffer(protocol: RconProtocol) -> None:
    protocol.data_received(b"foo")
    protocol.data_received(b"bar")
    assert bytes(protocol._buffer) == b"foobar"


def test_read_from_buffer_too_small(protocol: RconProtocol) -> None:
    data = magic + b"\x01\x02\x03\x04\x05\x06\x07"
    protocol._buffer = bytearray(data)
    protocol._read_from_buffer()
    assert bytes(protocol._buffer) == data


def test_read_from_buffer_incomplete_packet(protocol: RconProtocol) -> None:
    data = magic + b"\x01\x00\x00\x00\x05\x00\x00\x00Hell"
    protocol._buffer = bytearray(data)
    protocol._read_from_buffer()
    assert bytes(protocol._buffer) == data


def test_read_from_buffer_exactly_one_packet(
    mocker: MockerFixture,
    protocol: RconProtocol,
) -> None:
    mock_unpack = mocker.patch(
        "hllrcon.protocol.protocol.RconResponse.unpack",
        autospec=True,
    )
    data = magic + b"\x01\x00\x00\x00\x05\x00\x00\x00Hello"

    waiter: asyncio.Future[RconResponse] = asyncio.Future()
    protocol._waiters[1] = waiter

    protocol._buffer = bytearray(data)
    protocol._read_from_buffer()
    assert len(protocol._buffer) == 0
    assert waiter.result()
    mock_unpack.assert_called_once_with(1, b"Hello")


def test_read_from_buffer_missing_waiter(
    mocker: MockerFixture,
    protocol: RconProtocol,
) -> None:
    mock_unpack = mocker.patch(
        "hllrcon.protocol.protocol.RconResponse.unpack",
        autospec=True,
    )
    data = magic + b"\x01\x00\x00\x00\x05\x00\x00\x00Hello"
    protocol._buffer = bytearray(data)
    protocol._read_from_buffer()
    assert len(protocol._buffer) == 0
    mock_unpack.assert_called_once_with(1, b"Hello")


def test_read_from_buffer_multiple_packets(
    mocker: MockerFixture,
    protocol: RconProtocol,
) -> None:
    mock_unpack = mocker.patch(
        "hllrcon.protocol.protocol.RconResponse.unpack",
        autospec=True,
    )
    data = (
        magic
        + b"\x01\x00\x00\x00\x05\x00\x00\x00Hello"
        + magic
        + b"\x02\x00\x00\x00\x05\x00\x00\x00World"
        + magic
        + b"\x00\x00"
    )

    waiter1: asyncio.Future[RconResponse] = asyncio.Future()
    waiter2: asyncio.Future[RconResponse] = asyncio.Future()
    protocol._waiters[1] = waiter1
    protocol._waiters[2] = waiter2

    protocol._buffer = bytearray(data)
    protocol._read_from_buffer()
    assert bytes(protocol._buffer) == magic + b"\x00\x00"
    assert waiter1.result()
    assert waiter2.result()
    assert mock_unpack.call_count == 2
    mock_unpack.assert_any_call(1, b"Hello")
    mock_unpack.assert_called_with(2, b"World")


def test_read_from_buffer_magic_missing(
    mocker: MockerFixture,
    protocol: RconProtocol,
) -> None:
    mock_logger = mocker.patch.object(protocol.logger, "warning")
    data = b"\x00\x00\x00\x00\x01\x00\x00\x00\x05\x00\x00\x00Hello"
    protocol._buffer = bytearray(data)
    protocol._read_from_buffer()
    assert len(protocol._buffer) == 0
    mock_logger.assert_called_once()


def test_read_from_buffer_magic_offset(
    mocker: MockerFixture,
    protocol: RconProtocol,
) -> None:
    mock_unpack = mocker.patch(
        "hllrcon.protocol.protocol.RconResponse.unpack",
        autospec=True,
    )
    data = b"\x00\x05\x00\x00\x01\x00\x00" + magic + b"\x01\x00\x00\x00\x05\x00\x00\x00Hello"
    waiter: asyncio.Future[RconResponse] = asyncio.Future()
    protocol._buffer = bytearray(data)
    protocol._waiters[1] = waiter
    protocol._read_from_buffer()
    assert len(protocol._buffer) == 0
    assert waiter.result()
    mock_unpack.assert_called_once_with(1, b"Hello")


def test_read_from_buffer_invalid_payload_size(protocol: RconProtocol) -> None:
    """A packet claiming > MAX_PAYLOAD_SIZE should be dropped."""
    from hllrcon.protocol.constants import MAX_PAYLOAD_SIZE

    pkt_len = MAX_PAYLOAD_SIZE + 1
    data = magic + b"\x01\x00\x00\x00" + pkt_len.to_bytes(4, "little")
    protocol._buffer = bytearray(data)
    protocol._read_from_buffer()
    assert len(protocol._buffer) == 0


def test_connection_lost_graceful(protocol: RconProtocol) -> None:
    waiters: dict[int, asyncio.Future[RconResponse]] = {
        1: asyncio.Future(),
        2: asyncio.Future(),
    }
    protocol._waiters = waiters.copy()
    protocol.connection_lost(None)

    assert not protocol.is_connected()
    assert not protocol._waiters
    assert isinstance(waiters[1].exception(), HLLConnectionClosedError)
    assert isinstance(waiters[2].exception(), HLLConnectionClosedError)


def test_connection_lost_with_exception(protocol: RconProtocol) -> None:
    waiters: dict[int, asyncio.Future[RconResponse]] = {
        1: asyncio.Future(),
        2: asyncio.Future(),
    }
    protocol._waiters = waiters.copy()

    response = RconResponse(
        request_id=1,
        command="cmd",
        version=1,
        status_code=RconResponseStatus.OK,
        status_message="OK",
        content_body="foo",
    )
    waiters[1].set_result(response)

    protocol.connection_lost(OSError("Connection error"))

    assert not protocol.is_connected()
    assert not protocol._waiters
    assert waiters[1].result() == response
    assert isinstance(waiters[2].exception(), HLLConnectionLostError)


def test_connection_lost_callback(protocol: RconProtocol, mocker: MockerFixture) -> None:
    cb = mocker.Mock()
    protocol.on_connection_lost = cb
    protocol.connection_lost(None)
    cb.assert_called_once_with(None)


def test_connection_lost_callback_failure(protocol: RconProtocol, mocker: MockerFixture) -> None:
    cb = mocker.Mock(side_effect=RuntimeError("boom"))
    protocol.on_connection_lost = cb
    protocol.connection_lost(None)
    cb.assert_called_once_with(None)


# --------------------------------------------------------------------------- #
# XOR cipher tests
# --------------------------------------------------------------------------- #


def test_xor_single_byte_key(protocol: RconProtocol) -> None:
    protocol.xorkey = b"\x01"
    msg = b"\x00\x01\x02"
    expected = bytes([b ^ 0x01 for b in msg])
    assert protocol._xor(msg) == expected


def test_xor_multi_byte_key(protocol: RconProtocol) -> None:
    protocol.xorkey = b"\x01\x02\x03"
    msg = b"\x10\x20\x30\x40\x50\x60"
    expected = bytes(
        [
            0x10 ^ 0x01,
            0x20 ^ 0x02,
            0x30 ^ 0x03,
            0x40 ^ 0x01,
            0x50 ^ 0x02,
            0x60 ^ 0x03,
        ],
    )
    assert protocol._xor(msg) == expected


def test_xor_offset(protocol: RconProtocol) -> None:
    protocol.xorkey = b"\x01\x02\x03"
    msg = b"\x10\x20\x30"
    expected = bytes([0x10 ^ 0x02, 0x20 ^ 0x03, 0x30 ^ 0x01])
    assert protocol._xor(msg, offset=1) == expected


def test_xor_roundtrip(protocol: RconProtocol) -> None:
    protocol.xorkey = b"\x0a\x0b\x0c"
    msg = b"SecretMessage"
    encrypted = protocol._xor(msg)
    decrypted = protocol._xor(encrypted)
    assert decrypted == msg


# --------------------------------------------------------------------------- #
# execute() tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_execute_no_connection(protocol: RconProtocol) -> None:
    protocol.connection_lost(None)
    with pytest.raises(HLLConnectionClosedError, match=r"Connection is closed"):
        await protocol.execute("command", 1, "body")


def _make_response(request_id: int, message: str) -> bytes:
    body = {
        "name": "command",
        "version": 1,
        "statusCode": 200,
        "statusMessage": "OK",
        "contentBody": message,
    }
    body_encoded = json.dumps(body).encode("utf-8")
    return (
        magic
        + request_id.to_bytes(4, "little")
        + len(body_encoded).to_bytes(4, "little")
        + body_encoded
    )


@pytest.mark.asyncio
async def test_execute_success(protocol: RconProtocol, transport: Mock) -> None:
    loop = asyncio.get_running_loop()
    loop.call_later(0.1, protocol.data_received, _make_response(0, "response"))
    response = await protocol.execute("command", 1, "body")
    assert response.content_body == "response"
    transport.write.assert_called_once()


@pytest.mark.asyncio
async def test_execute_timeout(protocol: RconProtocol, transport: Mock) -> None:
    protocol.timeout = 0.1
    with pytest.raises(TimeoutError):
        await protocol.execute("command", 1, "body")
    assert not protocol._waiters
    transport.write.assert_called_once()


@pytest.mark.asyncio
async def test_execute_concurrently(protocol: RconProtocol, transport: Mock) -> None:
    protocol.timeout = 5.0

    async def delayed_response() -> None:
        await asyncio.sleep(0.1)
        protocol.data_received(
            _make_response(1, "response2") + _make_response(0, "response1"),
        )

    asyncio.create_task(delayed_response())
    responses = await asyncio.gather(
        protocol.execute("command1", 1, "body1"),
        protocol.execute("command2", 2, "body2"),
    )
    assert responses[0].content_body == "response1"
    assert responses[1].content_body == "response2"
    assert transport.write.call_count == 2


# --------------------------------------------------------------------------- #
# Authentication tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_authenticate_success(mocker: MockerFixture, protocol: RconProtocol) -> None:
    xorkey_b64 = base64.b64encode(b"keybytes").decode()
    xorkey_response = mocker.Mock()
    xorkey_response.content_body = xorkey_b64
    xorkey_response.raise_for_status = mocker.Mock()

    auth_token_response = mocker.Mock()
    auth_token_response.content_body = "token123"
    auth_token_response.raise_for_status = mocker.Mock()

    execute = mocker.patch.object(
        protocol,
        "execute",
        side_effect=[xorkey_response, auth_token_response],
    )

    await protocol.authenticate("password")

    execute.assert_has_calls(
        [
            mocker.call("ServerConnect", 2, ""),
            mocker.call("Login", 2, "password"),
        ],
    )
    assert protocol.xorkey == b"keybytes"
    assert protocol.auth_token == "token123"
    assert protocol.state == ProtocolState.AUTHENTICATED


@pytest.mark.asyncio
async def test_authenticate_serverconnect_not_string(
    mocker: MockerFixture,
    protocol: RconProtocol,
) -> None:
    xorkey_response = mocker.Mock()
    xorkey_response.content_body = 12345
    xorkey_response.raise_for_status = mocker.Mock()

    execute = mocker.patch.object(protocol, "execute", side_effect=[xorkey_response])

    with pytest.raises(HLLMessageError, match="not a string"):
        await protocol.authenticate("password")
    assert protocol.xorkey is None


@pytest.mark.asyncio
async def test_authenticate_serverconnect_raises(
    mocker: MockerFixture,
    protocol: RconProtocol,
) -> None:
    xorkey_response = mocker.Mock()
    xorkey_response.content_body = "ignored"
    xorkey_response.raise_for_status = mocker.Mock(side_effect=Exception("fail"))

    execute = mocker.patch.object(protocol, "execute", side_effect=[xorkey_response])

    with pytest.raises(HLLAuthError):
        await protocol.authenticate("password")


@pytest.mark.asyncio
async def test_authenticate_login_raises(
    mocker: MockerFixture,
    protocol: RconProtocol,
) -> None:
    xorkey_b64 = base64.b64encode(b"keybytes").decode()
    xorkey_response = mocker.Mock()
    xorkey_response.content_body = xorkey_b64
    xorkey_response.raise_for_status = mocker.Mock()

    auth_token_response = mocker.Mock()
    auth_token_response.content_body = "token123"
    auth_token_response.raise_for_status = mocker.Mock(side_effect=Exception("loginfail"))

    mocker.patch.object(
        protocol,
        "execute",
        side_effect=[xorkey_response, auth_token_response],
    )

    with pytest.raises(HLLAuthError):
        await protocol.authenticate("password")

    assert protocol.xorkey is None
    assert protocol.auth_token is None


@pytest.mark.asyncio
async def test_authenticate_xorkey_base64_error(
    mocker: MockerFixture,
    protocol: RconProtocol,
) -> None:
    xorkey_response = mocker.Mock()
    xorkey_response.content_body = "!!!notbase64!!!"
    xorkey_response.raise_for_status = mocker.Mock()

    mocker.patch.object(protocol, "execute", side_effect=[xorkey_response])

    with pytest.raises((binascii.Error, HLLMessageError)):
        await protocol.authenticate("password")
    assert protocol.xorkey is None
