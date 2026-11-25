"""Telemetry contract and requirements-coverage gate."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from conftest import load_requirements
from flightsim import FlightState, StatusFlags, Telemetry


@pytest.mark.req("TLM-001")
def test_initial_telemetry(vehicle):
    t = vehicle.telemetry()
    assert t == Telemetry(
        state=FlightState.DISARMED,
        altitude_m=0.0,
        battery_pct=100.0,
        gps_fix=True,
        flags=StatusFlags.NONE,
        sim_time_s=0.0,
    )


@pytest.mark.req("TLM-001")
def test_sim_time_advances_with_steps(vehicle):
    vehicle.step(2.5)
    assert vehicle.telemetry().sim_time_s == pytest.approx(2.5)


@pytest.mark.req("TLM-001")
@given(
    state=st.sampled_from(FlightState),
    alt_cm=st.integers(0, 12000),
    batt_tenths=st.integers(0, 1000),
    fix=st.booleans(),
    flags=st.integers(0, 15),
    t_ms=st.integers(0, 2**32 - 1),
)
def test_telemetry_pack_round_trip(state, alt_cm, batt_tenths, fix, flags, t_ms):
    t = Telemetry(state, alt_cm / 100, batt_tenths / 10, fix, StatusFlags(flags), t_ms / 1000)
    assert Telemetry.unpack(t.pack()) == t


def test_every_requirement_is_covered(request):
    covered = {
        req_id
        for item in request.session.items
        for marker in item.iter_markers("req")
        for req_id in marker.args
    }
    missing = set(load_requirements()) - covered
    assert not missing, f"requirements with no verifying test: {sorted(missing)}"
