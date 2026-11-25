"""Simulated flight controller: the device under test.

The controller is driven by simulated time (``tick``), so every test is
deterministic and a 60-second flight runs in milliseconds. Behaviour is
specified in ``requirements/system_requirements.toml``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .messages import Fault, FlightState, Result, StatusFlags, Telemetry


@dataclass(frozen=True)
class FlightParams:
    climb_rate_mps: float = 2.0
    descent_rate_mps: float = 1.0
    max_altitude_m: float = 120.0
    min_arm_battery_pct: float = 30.0
    low_battery_pct: float = 25.0
    critical_battery_pct: float = 15.0
    idle_drain_pct_per_s: float = 0.05
    flight_drain_pct_per_s: float = 0.4
    comms_timeout_s: float = 3.0
    auto_disarm_s: float = 10.0
    critical_battery_injected_pct: float = 10.0


class FlightController:
    def __init__(self, params: FlightParams | None = None) -> None:
        self.p = params or FlightParams()
        self.state = FlightState.DISARMED
        self.altitude_m = 0.0
        self.target_alt_m = 0.0
        self.battery_pct = 100.0
        self.gps_fix = True
        self.sim_time_s = 0.0
        self._last_comms_s = 0.0
        self._armed_idle_s = 0.0
        self._comms_lost = False

    # ------------------------------------------------------------------ cmds
    def note_comms(self) -> None:
        """Called for every vehicle message received (not sim-control traffic)."""
        self._last_comms_s = self.sim_time_s
        # COMMS_LOST is latched: it stays set until the next arm, so the
        # ground station can see why a failsafe happened after the link returns.

    def arm(self) -> Result:
        if self.state is not FlightState.DISARMED:
            return Result.REJECTED_STATE
        if not self.gps_fix or self.battery_pct < self.p.min_arm_battery_pct:
            return Result.REJECTED_PREFLIGHT
        self.state = FlightState.ARMED
        self._armed_idle_s = 0.0
        self._comms_lost = False
        return Result.OK

    def disarm(self) -> Result:
        if self.state is not FlightState.ARMED:
            return Result.REJECTED_STATE
        self.state = FlightState.DISARMED
        return Result.OK

    def takeoff(self, altitude_m: float) -> Result:
        if self.state is not FlightState.ARMED:
            return Result.REJECTED_STATE
        if not self._altitude_allowed(altitude_m):
            return Result.REJECTED_GEOFENCE
        self.state = FlightState.FLYING
        self.target_alt_m = altitude_m
        return Result.OK

    def set_altitude(self, altitude_m: float) -> Result:
        if self.state is not FlightState.FLYING:
            return Result.REJECTED_STATE
        if not self._altitude_allowed(altitude_m):
            return Result.REJECTED_GEOFENCE
        self.target_alt_m = altitude_m
        return Result.OK

    def land(self) -> Result:
        if self.state is FlightState.FAILSAFE_LAND or self.state is FlightState.LANDING:
            return Result.OK  # idempotent
        if self.state is not FlightState.FLYING:
            return Result.REJECTED_STATE
        self.state = FlightState.LANDING
        self.target_alt_m = 0.0
        return Result.OK

    def inject_fault(self, fault: Fault, active: bool) -> Result:
        if fault is Fault.GPS_LOSS:
            self.gps_fix = not active
        elif fault is Fault.BATTERY_CRITICAL and active:
            self.battery_pct = min(self.battery_pct, self.p.critical_battery_injected_pct)
        return Result.OK

    # ------------------------------------------------------------------ sim
    def tick(self, dt: float) -> None:
        if dt <= 0:
            return
        self.sim_time_s += dt
        airborne = self.state in (
            FlightState.FLYING,
            FlightState.LANDING,
            FlightState.FAILSAFE_LAND,
        )

        drain = (
            self.p.flight_drain_pct_per_s
            if airborne
            else (self.p.idle_drain_pct_per_s if self.state is FlightState.ARMED else 0.0)
        )
        self.battery_pct = max(0.0, self.battery_pct - drain * dt)

        if self.state is FlightState.FLYING:
            if self.sim_time_s - self._last_comms_s > self.p.comms_timeout_s:
                self._comms_lost = True
                self._enter_failsafe()
            elif not self.gps_fix or self.battery_pct <= self.p.critical_battery_pct:
                self._enter_failsafe()

        if airborne:
            self._move_toward_target(dt)

        if self.state in (FlightState.LANDING, FlightState.FAILSAFE_LAND) and self.altitude_m <= 0:
            self.altitude_m = 0.0
            self.state = FlightState.DISARMED

        if self.state is FlightState.ARMED:
            self._armed_idle_s += dt
            if self._armed_idle_s >= self.p.auto_disarm_s:
                self.state = FlightState.DISARMED

    def telemetry(self) -> Telemetry:
        flags = StatusFlags.NONE
        if self.state is FlightState.FAILSAFE_LAND:
            flags |= StatusFlags.FAILSAFE
        if not self.gps_fix:
            flags |= StatusFlags.GPS_FAULT
        if self._comms_lost:
            flags |= StatusFlags.COMMS_LOST
        if self.battery_pct <= self.p.low_battery_pct:
            flags |= StatusFlags.LOW_BATTERY
        return Telemetry(
            state=self.state,
            altitude_m=round(self.altitude_m, 2),
            battery_pct=round(self.battery_pct, 1),
            gps_fix=self.gps_fix,
            flags=flags,
            sim_time_s=round(self.sim_time_s, 3),
        )

    # -------------------------------------------------------------- helpers
    def _altitude_allowed(self, altitude_m: float) -> bool:
        return 0 < altitude_m <= self.p.max_altitude_m

    def _enter_failsafe(self) -> None:
        self.state = FlightState.FAILSAFE_LAND
        self.target_alt_m = 0.0

    def _move_toward_target(self, dt: float) -> None:
        delta = self.target_alt_m - self.altitude_m
        if delta > 0:
            self.altitude_m = min(self.target_alt_m, self.altitude_m + self.p.climb_rate_mps * dt)
        elif delta < 0:
            self.altitude_m = max(self.target_alt_m, self.altitude_m - self.p.descent_rate_mps * dt)
