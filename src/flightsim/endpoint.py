"""Protocol endpoint: turns incoming frames into controller calls and replies.

Transport-agnostic — the loopback transport calls it directly and the TCP
server calls it from a socket handler.
"""

from __future__ import annotations

import struct
import threading

from .controller import FlightController
from .messages import (
    SIM_CONTROL_IDS,
    MsgId,
    Result,
    pack_ack,
    unpack_fault,
    unpack_u16,
)
from .protocol import Frame, FrameDecoder, encode

PHYSICS_DT_S = 0.05


class SimEndpoint:
    def __init__(self, controller: FlightController | None = None) -> None:
        self.controller = controller or FlightController()
        self._lock = threading.Lock()

    def new_session(self) -> SimSession:
        return SimSession(self)

    def handle(self, frame: Frame) -> Frame:
        with self._lock:
            return self._dispatch(frame)

    def _dispatch(self, frame: Frame) -> Frame:
        fc = self.controller
        try:
            msg = MsgId(frame.msg_id)
        except ValueError:
            return self._ack(frame, Result.UNKNOWN_MESSAGE)

        if msg not in SIM_CONTROL_IDS:
            fc.note_comms()

        try:
            if msg is MsgId.GET_TELEMETRY:
                return Frame(frame.seq, MsgId.TELEMETRY, fc.telemetry().pack())
            if msg is MsgId.HEARTBEAT:
                return self._ack(frame, Result.OK)
            if msg is MsgId.ARM:
                return self._ack(frame, fc.arm())
            if msg is MsgId.DISARM:
                return self._ack(frame, fc.disarm())
            if msg is MsgId.TAKEOFF:
                return self._ack(frame, fc.takeoff(unpack_u16(frame.payload) / 100))
            if msg is MsgId.SET_ALTITUDE:
                return self._ack(frame, fc.set_altitude(unpack_u16(frame.payload) / 100))
            if msg is MsgId.LAND:
                return self._ack(frame, fc.land())
            if msg is MsgId.SIM_STEP:
                remaining = unpack_u16(frame.payload) / 1000
                while remaining > 1e-9:
                    dt = min(PHYSICS_DT_S, remaining)
                    fc.tick(dt)
                    remaining -= dt
                return self._ack(frame, Result.OK)
            if msg is MsgId.SIM_INJECT_FAULT:
                fault, active = unpack_fault(frame.payload)
                return self._ack(frame, fc.inject_fault(fault, active))
        except (struct.error, ValueError):
            return self._ack(frame, Result.BAD_PAYLOAD)
        return self._ack(frame, Result.UNKNOWN_MESSAGE)

    @staticmethod
    def _ack(frame: Frame, result: Result) -> Frame:
        return Frame(frame.seq, MsgId.ACK, pack_ack(frame.msg_id, result))


class SimSession:
    """Per-connection byte-stream state (each connection has its own decoder)."""

    def __init__(self, endpoint: SimEndpoint) -> None:
        self.endpoint = endpoint
        self.decoder = FrameDecoder()

    def receive(self, data: bytes) -> bytes:
        out = bytearray()
        for frame in self.decoder.feed(data):
            out += encode(self.endpoint.handle(frame))
        return bytes(out)
