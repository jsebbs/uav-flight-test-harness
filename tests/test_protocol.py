"""Protocol unit tests, including property-based fuzzing of the decoder."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from flightsim.protocol import (
    MAX_PAYLOAD,
    SYNC,
    Frame,
    FrameDecoder,
    FrameError,
    crc16_ccitt,
    encode,
)

frames = st.builds(
    Frame,
    seq=st.integers(0, 255),
    msg_id=st.integers(0, 255),
    payload=st.binary(max_size=MAX_PAYLOAD),
)


@pytest.mark.req("PROTO-001")
def test_crc_matches_standard_check_value():
    # Published check value for CRC-16/CCITT-FALSE over ASCII "123456789"
    assert crc16_ccitt(b"123456789") == 0x29B1


@pytest.mark.req("PROTO-001")
@given(frames)
def test_encode_decode_round_trip(frame):
    assert FrameDecoder().feed(encode(frame)) == [frame]


@pytest.mark.req("PROTO-001")
@given(frames, st.data())
def test_any_single_bit_flip_is_rejected(frame, data):
    raw = bytearray(encode(frame))
    bit = data.draw(st.integers(8, len(raw) * 8 - 1))  # leave SYNC intact
    raw[bit // 8] ^= 1 << (bit % 8)
    decoder = FrameDecoder()
    assert decoder.feed(bytes(raw)) == []


@pytest.mark.req("PROTO-002")
def test_resyncs_after_leading_garbage():
    frame = Frame(seq=7, msg_id=0x10)
    decoder = FrameDecoder()
    assert decoder.feed(b"\x00\xff\x13\x37" + encode(frame)) == [frame]
    assert decoder.stats.bytes_discarded == 4


@pytest.mark.req("PROTO-002")
def test_recovers_valid_frame_after_corrupted_frame():
    bad = bytearray(encode(Frame(1, 0x10, b"abc")))
    bad[-1] ^= 0xFF
    good = Frame(2, 0x11)
    decoder = FrameDecoder()
    assert decoder.feed(bytes(bad) + encode(good)) == [good]
    assert decoder.stats.crc_errors == 1


@pytest.mark.req("PROTO-002")
def test_oversized_length_field_is_skipped():
    good = Frame(3, 0x12, b"\x03\xe8")
    decoder = FrameDecoder()
    assert decoder.feed(bytes([SYNC, MAX_PAYLOAD + 1, 0, 0]) + encode(good)) == [good]
    assert decoder.stats.length_errors == 1


@pytest.mark.req("PROTO-003")
@settings(max_examples=300)
@given(st.binary(max_size=512))
def test_decoder_never_raises_on_arbitrary_bytes(blob):
    FrameDecoder().feed(blob)


@pytest.mark.req("PROTO-003")
@given(st.lists(frames, min_size=1, max_size=8), st.data())
def test_frames_survive_arbitrary_chunking(frame_list, data):
    stream = b"".join(encode(f) for f in frame_list)
    cuts = sorted(data.draw(st.lists(st.integers(0, len(stream)), max_size=10)))
    decoder = FrameDecoder()
    out, prev = [], 0
    for cut in [*cuts, len(stream)]:
        out += decoder.feed(stream[prev:cut])
        prev = cut
    assert out == frame_list


@pytest.mark.parametrize(
    "frame",
    [Frame(256, 0), Frame(0, -1), Frame(0, 0, bytes(MAX_PAYLOAD + 1))],
    ids=["seq-overflow", "negative-msg-id", "payload-too-long"],
)
def test_encoder_rejects_invalid_frames(frame):
    with pytest.raises(FrameError):
        encode(frame)
