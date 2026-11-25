"""Message IDs, result codes and payload packing for the flight protocol."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum, IntFlag


class MsgId(IntEnum):
    # Vehicle commands
    HEARTBEAT = 0x01
    ARM = 0x10
    DISARM = 0x11
    TAKEOFF = 0x12  # payload: u16 target altitude (cm)
    SET_ALTITUDE = 0x13  # payload: u16 target altitude (cm)
    LAND = 0x14
    GET_TELEMETRY = 0x30
    # Simulation control (test-bench only, not vehicle traffic)
    SIM_STEP = 0x20  # payload: u16 milliseconds to advance
    SIM_INJECT_FAULT = 0x21  # payload: u8 fault, u8 active
    # Responses
    ACK = 0x80  # payload: u8 acked msg_id, u8 result
    TELEMETRY = 0x81


SIM_CONTROL_IDS = frozenset({MsgId.SIM_STEP, MsgId.SIM_INJECT_FAULT})


class Result(IntEnum):
    OK = 0
    REJECTED_STATE = 1
    REJECTED_PREFLIGHT = 2
    REJECTED_GEOFENCE = 3
    BAD_PAYLOAD = 4
    UNKNOWN_MESSAGE = 5


class FlightState(IntEnum):
    DISARMED = 0
    ARMED = 1
    FLYING = 2
    LANDING = 3
    FAILSAFE_LAND = 4


class Fault(IntEnum):
    GPS_LOSS = 1
    BATTERY_CRITICAL = 2


class StatusFlags(IntFlag):
    NONE = 0
    FAILSAFE = 1 << 0
    GPS_FAULT = 1 << 1
    COMMS_LOST = 1 << 2
    LOW_BATTERY = 1 << 3


_ACK = struct.Struct(">BB")
_U16 = struct.Struct(">H")
_FAULT = struct.Struct(">BB")
_TELEM = struct.Struct(">BHHBBI")


@dataclass(frozen=True)
class Telemetry:
    state: FlightState
    altitude_m: float
    battery_pct: float
    gps_fix: bool
    flags: StatusFlags
    sim_time_s: float

    def pack(self) -> bytes:
        return _TELEM.pack(
            int(self.state),
            round(self.altitude_m * 100),
            round(self.battery_pct * 10),
            int(self.gps_fix),
            int(self.flags),
            round(self.sim_time_s * 1000),
        )

    @classmethod
    def unpack(cls, payload: bytes) -> Telemetry:
        state, alt_cm, batt, fix, flags, t_ms = _TELEM.unpack(payload)
        return cls(
            state=FlightState(state),
            altitude_m=alt_cm / 100,
            battery_pct=batt / 10,
            gps_fix=bool(fix),
            flags=StatusFlags(flags),
            sim_time_s=t_ms / 1000,
        )


def pack_ack(msg_id: int, result: Result) -> bytes:
    return _ACK.pack(msg_id, int(result))


def unpack_ack(payload: bytes) -> tuple[int, Result]:
    msg_id, result = _ACK.unpack(payload)
    return msg_id, Result(result)


def pack_u16(value: int) -> bytes:
    return _U16.pack(value)


def unpack_u16(payload: bytes) -> int:
    return _U16.unpack(payload)[0]


def pack_fault(fault: Fault, active: bool) -> bytes:
    return _FAULT.pack(int(fault), int(active))


def unpack_fault(payload: bytes) -> tuple[Fault, bool]:
    fault, active = _FAULT.unpack(payload)
    return Fault(fault), bool(active)
