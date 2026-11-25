"""Shared fixtures and the requirements-traceability plugin."""

from __future__ import annotations

import tomllib
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import pytest

from flightsim import (
    FlightClient,
    FlightState,
    LoopbackTransport,
    Result,
    SimEndpoint,
    SimTcpServer,
    TcpTransport,
)

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_FILE = ROOT / "requirements" / "system_requirements.toml"
REPORT_FILE = ROOT / "reports" / "traceability.md"


def load_requirements() -> dict[str, str]:
    data = tomllib.loads(REQUIREMENTS_FILE.read_text())
    return {r["id"]: r["text"] for r in data["requirement"]}


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def endpoint() -> SimEndpoint:
    return SimEndpoint()


@pytest.fixture(params=["loopback", "tcp"])
def vehicle(request: pytest.FixtureRequest, endpoint: SimEndpoint) -> Iterator[FlightClient]:
    """A connected client. Every test using it runs over both transports."""
    if request.param == "loopback":
        client = FlightClient(LoopbackTransport(endpoint))
        yield client
        client.close()
        return
    server = SimTcpServer(endpoint).start()
    client = FlightClient(TcpTransport(*server.address))
    try:
        yield client
    finally:
        client.close()
        server.stop()


@pytest.fixture
def airborne(vehicle: FlightClient) -> FlightClient:
    """Vehicle hovering at 10 m."""
    assert vehicle.arm() is Result.OK
    assert vehicle.takeoff(10) is Result.OK
    vehicle.wait_until(lambda t: t.altitude_m >= 10, timeout_s=10, description="reach 10 m")
    assert vehicle.telemetry().state is FlightState.FLYING
    return vehicle


# --------------------------------------------------------------------------
# Traceability plugin
# --------------------------------------------------------------------------
_outcomes: dict[str, str] = {}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "req(*ids): requirement IDs verified by this test")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    known = load_requirements()
    for item in items:
        for marker in item.iter_markers("req"):
            for req_id in marker.args:
                if req_id not in known:
                    raise pytest.UsageError(
                        f"{item.nodeid} references unknown requirement {req_id}"
                    )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" or report.outcome != "passed":
        prev = _outcomes.get(report.nodeid)
        if prev != "failed":
            _outcomes[report.nodeid] = report.outcome


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    items = getattr(session, "items", [])
    if not items:
        return
    reqs = load_requirements()
    by_req: dict[str, list[str]] = defaultdict(list)
    for item in items:
        for marker in item.iter_markers("req"):
            for req_id in marker.args:
                by_req[req_id].append(item.nodeid)

    lines = [
        "# Requirements Traceability Matrix",
        "",
        "| Requirement | Description | Tests | Status |",
        "|---|---|---|---|",
    ]
    for req_id, text in reqs.items():
        tests = by_req.get(req_id, [])
        results = [_outcomes.get(t, "not run") for t in tests]
        if not tests:
            status = "NOT COVERED"
        elif "failed" in results:
            status = "FAIL"
        elif all(r == "passed" for r in results):
            status = "PASS"
        else:
            status = "PARTIAL"
        lines.append(f"| {req_id} | {text} | {len(tests)} | {status} |")
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n")
