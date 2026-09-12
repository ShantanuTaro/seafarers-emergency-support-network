"""Runnable checks for the logic that would fail silently.

    .venv/bin/python test_sesn.py

No framework. These are the invariants that, if they broke, would produce a system
that still ran and still looked right, which is the dangerous kind of broken.
"""

from sesn import baseline, response, triage
from sesn.models import IncidentType, Severity, Telemetry
from sesn.sim import FAULTS, Simulator


def test_sar_coverage_is_exhaustive():
    """Every position on earth must resolve to a named authority. "We could not work
    out whose water this is" is not an answer a rescue system may give."""
    gaps = [(la, lo) for la in range(-90, 91, 2) for lo in range(-180, 181, 2)
            if response.sar_region(la, lo)[1] == "MRCC SIM-UNASSIGNED"]
    assert not gaps, f"{len(gaps)} positions have no responsible authority, e.g. {gaps[:3]}"


def test_simulator_is_deterministic():
    a, b = Simulator(size=500), Simulator(size=500)
    assert [s.mmsi for s in a.ships.values()] == [s.mmsi for s in b.ships.values()]
    for _ in range(5):
        a.tick(1.0)
        b.tick(1.0)
    assert a.frame(None)[0] == b.frame(None)[0], "same seed diverged"


def test_faults_move_telemetry_not_just_labels():
    """The whole design rests on this: an injected fault has to change the feed, or
    the detector is being handed the answer instead of deriving it."""
    sim = Simulator(size=400)
    for key, fault in FAULTS.items():
        if fault.speed_kn is None and fault.nav_status is None and not fault.ais_dark:
            continue  # medical evacuation legitimately leaves telemetry untouched
        ship = next(s for s in sim.ships.values() if not s.distressed and s.route)
        before = (ship.speed_kn, ship.nav_status, ship.ais_dark)
        sim.inject(ship.mmsi, key)
        after = (ship.speed_kn, ship.nav_status, ship.ais_dark)
        assert before != after, f"fault {key!r} changed no telemetry"


def test_distressed_never_culled_from_a_frame():
    """An operator must not lose a casualty to a rendering budget."""
    sim = Simulator(size=8000)
    victims = [s for s in list(sim.ships.values())[:12]]
    for s in victims:
        sim.inject(s.mmsi, "fire")
    rows, total = sim.frame(None, cap=200)
    shown = {r[0] for r in rows}
    assert total > 200, "test needs an over-capacity frame to be meaningful"
    for s in victims:
        assert s.mmsi in shown, f"distressed {s.mmsi} was culled"


def test_guard_only_ever_raises_severity():
    """The asymmetry the whole triage design rests on. A beacon MMSI forces
    Critical no matter how calm the classifier was."""
    tel = Telemetry(mmsi="974220518", lat=19.4, lon=-66.8, speedKn=0.0, navStatus=15)
    result, _ = triage.run("", tel)
    assert result.severity == Severity.CRITICAL, result
    assert result.unknowns, "a telemetry-only incident must declare its unknowns"


def test_silent_incident_always_declares_unknowns():
    sim = Simulator(size=200)
    ship = next(s for s in sim.ships.values() if s.route)
    sim.inject(ship.mmsi, "grounding")
    result, _ = triage.run("", ship.telemetry())
    assert result.type is IncidentType.GROUNDING
    assert result.unknowns, "a report-free grounding claimed to know everything"


def test_negation_is_not_positive_evidence():
    """"No ingress" was scoring as flooding, which cost every collision in the
    corpus. The guard belongs in the matcher, not in one call site."""
    r = baseline.classify(
        "We have struck a fishing vessel in fog. Damage to our bow above the "
        "waterline, no ingress on our side.", None)
    assert r.type is IncidentType.COLLISION, r.type


def test_every_packet_starts_unapproved():
    """The liability requirement, asserted rather than trusted."""
    sim = Simulator(size=600)
    ship = next(s for s in sim.ships.values() if s.route)
    sim.inject(ship.mmsi, "flooding")
    from sesn.models import Incident
    result, _ = triage.run(FAULTS["flooding"].text, ship.telemetry())
    inc = Incident(id="t", mmsi=ship.mmsi, vessel_name=ship.name, opened_at="now",
                   report_text=FAULTS["flooding"].text, telemetry=ship.telemetry(),
                   triage=result)
    packets = response.build_packets(inc, ship, response.nearest(list(sim.ships.values()), ship))
    assert packets, "no packets drafted"
    assert not any(p.approved or p.rejected for p in packets), "a packet was born approved"
    assert all("supplementary to GMDSS" in p.body for p in packets), "missing GMDSS footer"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")
