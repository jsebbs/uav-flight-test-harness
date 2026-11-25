"""Binary framing protocol shared by the simulator and the test harness.

Frame layout (all multi-byte fields big-endian)::

    +------+-----+-----+--------+-----------------+---------+
    | SYNC | LEN | SEQ | MSG_ID | PAYLOAD (LEN B) | CRC16   |
    | 0xA5 | u8  | u8  | u8     |                 | u16     |
    +------+-----+-----+--------+-----------------+---------+

The CRC is CRC-16/CCITT-FALSE computed over LEN, SEQ, MSG_ID and PAYLOAD.
The decoder is a streaming state machine: it accepts arbitrary byte chunks,
re-synchronises after garbage or corrupted frames, and never raises on bad
input. That last property is checked with property-based fuzz tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SYNC = 0xA5
HEADER_LEN = 4  # sync + len + seq + msg_id
CRC_LEN = 2
MAX_PAYLOAD = 64


def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no xorout)."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


@dataclass(frozen=True)
class Frame:
    seq: int
    msg_id: int
    payload: bytes = b""


class FrameError(ValueError):
    """Raised when asked to encode a frame that violates the protocol."""


def encode(frame: Frame) -> bytes:
    if not 0 <= frame.seq <= 0xFF:
        raise FrameError(f"seq out of range: {frame.seq}")
    if not 0 <= frame.msg_id <= 0xFF:
        raise FrameError(f"msg_id out of range: {frame.msg_id}")
    if len(frame.payload) > MAX_PAYLOAD:
        raise FrameError(f"payload too long: {len(frame.payload)} > {MAX_PAYLOAD}")
    body = bytes([len(frame.payload), frame.seq, frame.msg_id]) + frame.payload
    return bytes([SYNC]) + body + crc16_ccitt(body).to_bytes(2, "big")


@dataclass
class DecoderStats:
    frames_ok: int = 0
    crc_errors: int = 0
    length_errors: int = 0
    bytes_discarded: int = 0


@dataclass
class FrameDecoder:
    """Incremental decoder. Feed it any chunking of a byte stream."""

    stats: DecoderStats = field(default_factory=DecoderStats)
    _buf: bytearray = field(default_factory=bytearray)

    def feed(self, data: bytes) -> list[Frame]:
        self._buf.extend(data)
        frames: list[Frame] = []
        while True:
            start = self._buf.find(SYNC)
            if start < 0:
                self.stats.bytes_discarded += len(self._buf)
                self._buf.clear()
                return frames
            if start:
                self.stats.bytes_discarded += start
                del self._buf[:start]
            if len(self._buf) < HEADER_LEN:
                return frames
            length = self._buf[1]
            if length > MAX_PAYLOAD:
                self.stats.length_errors += 1
                self._drop_sync_byte()
                continue
            total = HEADER_LEN + length + CRC_LEN
            if len(self._buf) < total:
                return frames
            body = bytes(self._buf[1 : HEADER_LEN + length])
            rx_crc = int.from_bytes(self._buf[HEADER_LEN + length : total], "big")
            if crc16_ccitt(body) != rx_crc:
                self.stats.crc_errors += 1
                self._drop_sync_byte()
                continue
            frames.append(Frame(seq=body[1], msg_id=body[2], payload=body[3:]))
            self.stats.frames_ok += 1
            del self._buf[:total]

    def _drop_sync_byte(self) -> None:
        # Skip only the sync byte so a real frame hiding inside a corrupted
        # one can still be found on the next pass.
        self.stats.bytes_discarded += 1
        del self._buf[:1]
