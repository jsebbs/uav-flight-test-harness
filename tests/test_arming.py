"""Arming, preflight checks and auto-disarm."""

from __future__ import annotations

import pytest

from flightsim import Fault, FlightState, Result


@pytest.mark.req("ARM-001")
def test_arms_when_preflight_passes(vehicle):
    assert vehicle.arm() is Result.OK
    assert vehicle.telemetry().state is FlightState.ARMED


@pytest.mark.req("ARM-001")
def test_rejects_arm_without_gps(vehicle):
    vehicle.inject_fault(Fault.GPS_LOSS)
    assert vehicle.arm() is Result.REJECTED_PREFLIGHT
    vehicle.inject_fault(Fault.GPS_LOSS, active=False)
    assert vehicle.arm() is Result.OK


@pytest.mark.req("ARM-001")
@pytest.mark.parametrize(
    ("battery", "expected"),
    [(29.9, Result.REJECTED_PREFLIGHT), (30.0, Result.OK), (30.1, Result.OK)],
    ids=["below", "at-limit", "above"],
)
def test_battery_arming_boundary(endpoint, vehicle, battery, expected):
    endpoint.controller.battery_pct = battery  # bench setup: force battery level
    assert vehicle.arm() is expected


@pytest.mark.req("ARM-001")
def test_rejects_double_arm(vehicle):
    assert vehicle.arm() is Result.OK
    assert vehicle.arm() is Result.REJECTED_STATE


@pytest.mark.req("ARM-002")
def test_rejects_disarm_in_flight(airborne):
    assert airborne.disarm() is Result.REJECTED_STATE
    assert airborne.telemetry().state is FlightState.FLYING


@pytest.mark.req("ARM-002")
def test_disarm_on_ground(vehicle):
    vehicle.arm()
    assert vehicle.disarm() is Result.OK
    assert vehicle.telemetry().state is FlightState.DISARMED


@pytest.mark.req("ARM-003")
def test_auto_disarms_after_idle_timeout(vehicle):
    vehicle.arm()
    vehicle.step(9.5)
    assert vehicle.telemetry().state is FlightState.ARMED
    vehicle.step(0.6)
    assert vehicle.telemetry().state is FlightState.DISARMED
