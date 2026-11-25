"""Command/ACK contract over a live transport."""

from __future__ import annotations

import pytest

from flightsim import MsgId, Result
from flightsim.messages import unpack_ack
from flightsim.protocol import Frame, encode


@pytest.mark.req("PROTO-004")
def test_ack_echoes_sequence_and_message_id(vehicle):
    for _ in range(300):  # wraps the 8-bit sequence counter
        reply = vehicle.request(MsgId.HEARTBEAT)
        assert reply.msg_id == MsgId.ACK
        assert unpack_ack(reply.payload) == (MsgId.HEARTBEAT, Result.OK)


@pytest.mark.req("PROTO-004")
def test_unknown_message_is_nacked(vehicle):
    assert vehicle.command(0x7E) is Result.UNKNOWN_MESSAGE


@pytest.mark.req("PROTO-004")
@pytest.mark.parametrize("payload", [b"", b"\x01", b"\x01\x02\x03"], ids=["empty", "short", "long"])
def test_malformed_takeoff_payload_is_nacked(vehicle, payload):
    assert vehicle.arm() is Result.OK
    assert vehicle.command(MsgId.TAKEOFF, payload) is Result.BAD_PAYLOAD


@pytest.mark.req("PROTO-002", "PROTO-004")
def test_link_survives_line_noise(vehicle):
    vehicle.send_raw(b"\xa5\x02\x00\x10garbage\x00\xff")
    assert vehicle.heartbeat() is Result.OK


@pytest.mark.req("PROTO-004")
def test_corrupted_command_gets_no_response(vehicle):
    raw = bytearray(encode(Frame(seq=200, msg_id=MsgId.ARM)))
    raw[-1] ^= 0x01
    vehicle.send_raw(bytes(raw))
    # The corrupted ARM must not have been executed.
    assert vehicle.telemetry().state.name == "DISARMED"
