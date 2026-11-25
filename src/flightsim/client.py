"""Test-harness client: the API that test cases are written against."""

from __future__ import annotations

from collections.abc import Callable

from .messages import (
    Fault,
    MsgId,
    Result,
    Telemetry,
    pack_fault,
    pack_u16,
    unpack_ack,
)
from .protocol import Frame, FrameDecoder, encode
from .transport import Transport


class ProtocolError(RuntimeError):
    pass


class WaitTimeout(AssertionError):
    """Raised when a condition is not met within the simulated time budget."""

    def __init__(self, description: str, timeout_s: float, last: Telemetry) -> None:
        super().__init__(f"'{description}' not met within {timeout_s:.1f}s sim time; last={last}")
        self.last = last


class FlightClient:
    def __init__(self, transport: Transport, response_timeout_s: float = 2.0) -> None:
        self._t = transport
        self._decoder = FrameDecoder()
        self._seq = 0
        self._timeout = response_timeout_s
        self._pending: list[Frame] = []

    # -------------------------------------------------------------- low-level
    def request(self, msg_id: int, payload: bytes = b"") -> Frame:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFF
        self._t.write(encode(Frame(seq, msg_id, payload)))
        return self._await(seq)

    def send_raw(self, data: bytes) -> None:
        """Write raw bytes (for negative / robustness tests)."""
        self._t.write(data)

    def _await(self, seq: int) -> Frame:
        for _ in range(64):
            for i, frame in enumerate(self._pending):
                if frame.seq == seq:
                    return self._pending.pop(i)
            chunk = self._t.read(self._timeout)
            if not chunk:
                break
            self._pending.extend(self._decoder.feed(chunk))
        raise ProtocolError(f"no response for seq={seq}")

    def command(self, msg_id: int, payload: bytes = b"") -> Result:
        reply = self.request(msg_id, payload)
        if reply.msg_id != MsgId.ACK:
            raise ProtocolError(f"expected ACK, got msg_id=0x{reply.msg_id:02X}")
        acked, result = unpack_ack(reply.payload)
        if acked != msg_id:
            raise ProtocolError(f"ACK for 0x{acked:02X}, expected 0x{msg_id:02X}")
        return result

    # ------------------------------------------------------------ vehicle API
    def heartbeat(self) -> Result:
        return self.command(MsgId.HEARTBEAT)

    def arm(self) -> Result:
        return self.command(MsgId.ARM)

    def disarm(self) -> Result:
        return self.command(MsgId.DISARM)

    def takeoff(self, altitude_m: float) -> Result:
        return self.command(MsgId.TAKEOFF, pack_u16(round(altitude_m * 100)))

    def set_altitude(self, altitude_m: float) -> Result:
        return self.command(MsgId.SET_ALTITUDE, pack_u16(round(altitude_m * 100)))

    def land(self) -> Result:
        return self.command(MsgId.LAND)

    def telemetry(self) -> Telemetry:
        reply = self.request(MsgId.GET_TELEMETRY)
        if reply.msg_id != MsgId.TELEMETRY:
            raise ProtocolError(f"expected TELEMETRY, got msg_id=0x{reply.msg_id:02X}")
        return Telemetry.unpack(reply.payload)

    # -------------------------------------------------------- sim / bench API
    def inject_fault(self, fault: Fault, active: bool = True) -> Result:
        return self.command(MsgId.SIM_INJECT_FAULT, pack_fault(fault, active))

    def step(self, seconds: float, heartbeat: bool = True, chunk_s: float = 0.5) -> None:
        """Advance simulated time. With heartbeat=True the ground station keeps
        the link alive between chunks, like a real GCS would."""
        remaining = seconds
        while remaining > 1e-9:
            dt = min(chunk_s, remaining)
            if heartbeat:
                self.heartbeat()
            result = self.command(MsgId.SIM_STEP, pack_u16(round(dt * 1000)))
            if result is not Result.OK:
                raise ProtocolError(f"SIM_STEP rejected: {result.name}")
            remaining -= dt

    def wait_until(
        self,
        predicate: Callable[[Telemetry], bool],
        timeout_s: float,
        description: str = "condition",
        poll_s: float = 0.1,
        heartbeat: bool = True,
    ) -> Telemetry:
        """Step sim time until predicate(telemetry) holds; fail with context if not."""
        elapsed = 0.0
        telem = self.telemetry()
        while not predicate(telem):
            if elapsed >= timeout_s:
                raise WaitTimeout(description, timeout_s, telem)
            self.step(poll_s, heartbeat=heartbeat, chunk_s=poll_s)
            elapsed += poll_s
            telem = self.telemetry()
        return telem

    def close(self) -> None:
        self._t.close()
