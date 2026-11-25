"""Takeoff, altitude hold, geofence and landing."""

from __future__ import annotations

import pytest

from flightsim import FlightState, Result

CLIMB_RATE = 2.0
DESCENT_RATE = 1.0


@pytest.mark.req("FLT-001")
def test_climb_rate_and_altitude_hold(vehicle):
    vehicle.arm()
    assert vehicle.takeoff(20) is Result.OK
    vehicle.step(5)
    assert vehicle.telemetry().altitude_m == pytest.approx(5 * CLIMB_RATE, abs=0.1)
    vehicle.step(10)
    for _ in range(3):  # holds altitude, no overshoot or drift
        vehicle.step(1)
        assert vehicle.telemetry().altitude_m == pytest.approx(20, abs=0.1)


@pytest.mark.req("FLT-001")
def test_set_altitude_in_flight(airborne):
    assert airborne.set_altitude(30) is Result.OK
    t = airborne.wait_until(lambda t: t.altitude_m >= 30, timeout_s=11, description="reach 30 m")
    assert t.altitude_m == pytest.approx(30, abs=0.1)
    assert airborne.set_altitude(5) is Result.OK
    airborne.wait_until(lambda t: t.altitude_m <= 5, timeout_s=26, description="descend to 5 m")


@pytest.mark.req("FLT-002")
@pytest.mark.parametrize(
    ("altitude", "expected"),
    [
        (0, Result.REJECTED_GEOFENCE),
        (0.01, Result.OK),
        (120, Result.OK),
        (120.01, Result.REJECTED_GEOFENCE),
        (500, Result.REJECTED_GEOFENCE),
    ],
)
def test_takeoff_geofence_boundaries(vehicle, altitude, expected):
    vehicle.arm()
    assert vehicle.takeoff(altitude) is expected


@pytest.mark.req("FLT-002")
def test_set_altitude_geofence_keeps_previous_target(airborne):
    assert airborne.set_altitude(121) is Result.REJECTED_GEOFENCE
    airborne.step(3)
    assert airborne.telemetry().altitude_m == pytest.approx(10, abs=0.1)


@pytest.mark.req("FLT-001")
def test_takeoff_requires_armed(vehicle):
    assert vehicle.takeoff(10) is Result.REJECTED_STATE


@pytest.mark.req("FLT-003")
def test_land_descent_rate_and_touchdown_disarm(airborne):
    assert airborne.land() is Result.OK
    airborne.step(4)
    t = airborne.telemetry()
    assert t.state is FlightState.LANDING
    assert t.altitude_m == pytest.approx(10 - 4 * DESCENT_RATE, abs=0.1)
    t = airborne.wait_until(
        lambda t: t.state is FlightState.DISARMED, timeout_s=8, description="touchdown"
    )
    assert t.altitude_m == 0


@pytest.mark.req("FLT-003")
def test_land_is_idempotent(airborne):
    assert airborne.land() is Result.OK
    assert airborne.land() is Result.OK


@pytest.mark.req("FLT-003")
def test_full_mission_profile(vehicle):
    """End-to-end: arm → climb → reposition → land, checking every phase."""
    assert vehicle.arm() is Result.OK
    assert vehicle.takeoff(15) is Result.OK
    vehicle.wait_until(lambda t: t.altitude_m >= 15, timeout_s=10, description="climb")
    assert vehicle.set_altitude(25) is Result.OK
    vehicle.wait_until(lambda t: t.altitude_m >= 25, timeout_s=6, description="reposition")
    assert vehicle.land() is Result.OK
    final = vehicle.wait_until(
        lambda t: t.state is FlightState.DISARMED, timeout_s=30, description="land"
    )
    assert final.altitude_m == 0
    assert final.battery_pct > 50
