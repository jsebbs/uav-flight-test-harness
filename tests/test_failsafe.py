"""Fault injection: GPS loss, critical battery, comms loss."""

from __future__ import annotations

import pytest

from flightsim import Fault, FlightState, Result, StatusFlags


def _is_failsafe(t):
    return t.state is FlightState.FAILSAFE_LAND


@pytest.mark.req("FS-001")
def test_gps_loss_triggers_failsafe_land(airborne):
    airborne.inject_fault(Fault.GPS_LOSS)
    t = airborne.wait_until(_is_failsafe, timeout_s=0.5, description="failsafe on GPS loss")
    assert StatusFlags.GPS_FAULT in t.flags
    assert StatusFlags.FAILSAFE in t.flags
    airborne.wait_until(
        lambda t: t.state is FlightState.DISARMED, timeout_s=12, description="failsafe touchdown"
    )


@pytest.mark.req("FS-002")
def test_critical_battery_triggers_failsafe_land(airborne):
    airborne.inject_fault(Fault.BATTERY_CRITICAL)
    t = airborne.wait_until(_is_failsafe, timeout_s=0.5, description="failsafe on battery")
    assert StatusFlags.LOW_BATTERY in t.flags


@pytest.mark.req("FS-002")
def test_battery_drains_into_failsafe_naturally(endpoint, airborne):
    endpoint.controller.battery_pct = 17.0
    t = airborne.wait_until(_is_failsafe, timeout_s=10, description="drain to 15%")
    assert t.battery_pct <= 15.0


@pytest.mark.req("FS-003")
def test_comms_loss_triggers_failsafe(airborne):
    # SIM_STEP is bench traffic, so stepping without heartbeats is a silent link.
    airborne.step(2.5, heartbeat=False)
    assert airborne.telemetry().state is FlightState.FLYING  # 2.5 s < 3.0 s timeout
    airborne.step(3.1, heartbeat=False)  # the telemetry request above reset the timer
    t = airborne.telemetry()
    assert t.state is FlightState.FAILSAFE_LAND
    assert StatusFlags.COMMS_LOST in t.flags


@pytest.mark.req("FS-003")
def test_heartbeat_keeps_link_alive(airborne):
    airborne.step(30, heartbeat=True)
    t = airborne.telemetry()
    assert t.state is FlightState.FLYING
    assert StatusFlags.COMMS_LOST not in t.flags


@pytest.mark.req("FS-004")
@pytest.mark.parametrize("command", ["set_altitude", "takeoff"])
def test_operator_altitude_commands_rejected_in_failsafe(airborne, command):
    airborne.inject_fault(Fault.GPS_LOSS)
    airborne.wait_until(_is_failsafe, timeout_s=0.5)
    assert getattr(airborne, command)(50) is Result.REJECTED_STATE
    airborne.step(2)
    assert airborne.telemetry().altitude_m < 10


@pytest.mark.req("FS-001")
def test_gps_recovery_does_not_cancel_failsafe(airborne):
    airborne.inject_fault(Fault.GPS_LOSS)
    airborne.wait_until(_is_failsafe, timeout_s=0.5)
    airborne.inject_fault(Fault.GPS_LOSS, active=False)
    airborne.step(1)
    assert airborne.telemetry().state is FlightState.FAILSAFE_LAND


@pytest.mark.req("FS-003")
def test_comms_lost_flag_latches_until_rearm(airborne):
    """Regression: the flag used to clear on the very next message, so the
    GCS could never see why the failsafe had fired."""
    airborne.step(3.5, heartbeat=False)
    airborne.heartbeat()  # link restored
    assert StatusFlags.COMMS_LOST in airborne.telemetry().flags
    airborne.wait_until(lambda t: t.state is FlightState.DISARMED, timeout_s=12)
    assert airborne.arm() is Result.OK
    assert StatusFlags.COMMS_LOST not in airborne.telemetry().flags
