# UAV Flight Test Harness

[![CI](https://github.com/jsebbs/uav-flight-test-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/jsebbs/uav-flight-test-harness/actions/workflows/ci.yml)

A requirements-driven test automation framework for a simulated UAV flight
controller, written in Python with pytest. The simulator is the device under
test; the harness drives it over a binary protocol exactly the way a ground
station or hardware-in-the-loop (HIL) bench would.

**91 tests · 15 system requirements · 95% branch coverage · 2 transports · CI on Python 3.11–3.13**

## What it demonstrates

| Area | How |
|---|---|
| **Requirements traceability** | Every test is tagged `@pytest.mark.req("FS-003")`. A pytest plugin builds a traceability matrix on every run, rejects unknown IDs, and fails the build if any requirement has no verifying test. |
| **Fault injection** | Bench-only messages inject GPS loss and critical battery; comms loss is simulated by silencing the heartbeat. Tests verify failsafe entry, status flags, and that operators can't override a failsafe. |
| **Property-based fuzzing** | Hypothesis drives the protocol decoder with arbitrary bytes, random chunking and single-bit corruption, checking that it never crashes, never accepts a corrupted frame, and always resynchronises. |
| **Boundary-value testing** | Parametrized tests sit on both sides of every limit (arm at 29.9 / 30.0 / 30.1 % battery, geofence at 0 / 0.01 / 120 / 120.01 m). |
| **Transport-agnostic suite** | One fixture runs every system test over an in-process loopback *and* a real TCP socket, so tests verify vehicle behaviour, not the wiring. |
| **Deterministic simulated time** | The bench controls the clock (`SIM_STEP`), so a 30-second flight runs in milliseconds with zero flakiness. `wait_until()` fails with the last telemetry snapshot for fast triage. |
| **CI** | GitHub Actions matrix: ruff lint + format check, pytest with JUnit XML and coverage gate (≥ 90%), traceability matrix published to the job summary, reports uploaded as artifacts. |

## Architecture

```
tests/ ──► FlightClient (harness API) ──► Transport ──► SimEndpoint ──► FlightController (DUT)
             arm(), takeoff(),            Loopback      frame decode      state machine,
             inject_fault(),              or TCP        + dispatch        physics, failsafes
             wait_until(...)
```

| Module | Role |
|---|---|
| `protocol.py` | Framing (`SYNC · LEN · SEQ · MSG_ID · PAYLOAD · CRC16`) and a streaming decoder that resyncs on garbage |
| `messages.py` | Message IDs, result codes, telemetry packing |
| `controller.py` | Flight controller state machine: `DISARMED → ARMED → FLYING → LANDING / FAILSAFE_LAND` |
| `endpoint.py` | Routes frames to the controller and builds ACK/NACK replies; separates vehicle traffic from bench control |
| `transport.py` | Loopback and TCP transports plus a threaded TCP sim server |
| `client.py` | The harness API test cases are written against |

## Requirements

Defined in [`requirements/system_requirements.toml`](requirements/system_requirements.toml):

| ID | Requirement |
|---|---|
| PROTO-001–004 | CRC integrity, resync, robustness to arbitrary input, ACK/NACK contract |
| ARM-001–003 | Preflight checks (GPS + battery ≥ 30%), no disarm in flight, 10 s auto-disarm |
| FLT-001–003 | 2.0 m/s climb, ±0.1 m altitude hold, (0, 120] m geofence, 1.0 m/s descent + touchdown disarm |
| FS-001–004 | Failsafe land on GPS loss, battery ≤ 15%, comms silence > 3 s; operator lockout during failsafe |
| TLM-001 | Telemetry contract |

After a run, `reports/traceability.md` maps each requirement to its tests and their PASS/FAIL status.

## Example test

```python
@pytest.mark.req("FS-001")
def test_gps_loss_triggers_failsafe_land(airborne):
    airborne.inject_fault(Fault.GPS_LOSS)
    t = airborne.wait_until(_is_failsafe, timeout_s=0.5, description="failsafe on GPS loss")
    assert StatusFlags.GPS_FAULT in t.flags
    airborne.wait_until(lambda t: t.state is FlightState.DISARMED, timeout_s=12)
```

## Bug found by the harness

While writing `FS-003`, the comms-loss test failed: the vehicle correctly entered
failsafe, but `COMMS_LOST` was never visible in telemetry. Requesting telemetry
counts as link traffic, and the controller cleared the flag on *any* incoming
message, so it was wiped before it could be reported. The fix latches the flag
until the next arm, and `test_comms_lost_flag_latches_until_rearm` guards
against regression.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

pytest                                   # full suite (≈20 s)
pytest -k failsafe                       # one area
pytest -m "req" --cov                    # with coverage
ruff check . && ruff format --check .    # lint
```

## License

MIT
