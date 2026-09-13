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


def test_vessel_identities_are_consistent():
    """A fleet where six hulls answer to "HYM Anchor", or an MMSI says Hong Kong while
    the flag says Liberia, reads as fake to anyone who has stood a watch."""
    from sesn.sim import FLAG_MIDS
    ships = list(Simulator(size=20_000).ships.values())
    assert len({s.name for s in ships}) == len(ships), "two hulls share a name"
    wrong = [s.mmsi for s in ships if s.mmsi[:3] not in FLAG_MIDS[s.flag]]
    assert not wrong, f"MMSI MID contradicts flag state: {wrong[:3]}"


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


def test_shore_messages_carry_a_name():
    """A bridge message is not a gated packet, so the only thing making it
    accountable is the name on it, and the endpoint has to insist on one. The
    vessel side does not: a crew member is already identified by their hull."""
    from fastapi.testclient import TestClient

    from sesn.main import app
    from sesn.main import sim as live

    client = TestClient(app)
    mmsi = next(iter(live.ships))
    post = lambda m, **body: client.post(f"/api/vessel/{m}/message", json=body)

    assert post(mmsi, text="Tug tasked", frm="shore").status_code == 400, "unnamed shore message accepted"
    assert post(mmsi, text="   ", frm="vessel").status_code == 400, "empty message accepted"
    assert post("000000000", text="hello").status_code == 404
    ok = post(mmsi, text="Tug tasked, ETA 3 h.", author="Watchkeeper", frm="shore")
    assert ok.status_code == 200, ok.text

    thread = client.get(f"/api/vessel/{mmsi}/situation").json()["messages"]
    assert thread[-1] == {**thread[-1], "frm": "shore", "author": "Watchkeeper"}, thread


def test_vessel_search_filters_narrow_and_never_widen():
    """The bridge sign-in narrows 60,000 hulls by type, flag, region and area. A filter
    the endpoint silently ignores returns a plausible list of the wrong ships."""
    from fastapi.testclient import TestClient

    from sesn.main import app

    client = TestClient(app)
    find = lambda **p: client.get("/api/search", params={"limit": 200, **p}).json()
    d = client.get("/api/directory").json()
    assert d["kinds"] and d["flags"] and d["regions"] and d["areas"], d

    got = find(kind="tanker", flag="Liberia")
    assert got and all(v["kind"] == "tanker" and v["flag"] == "Liberia" for v in got)
    got = find(area="Malacca Strait")
    assert got and all(v["corridor"] == "Malacca Strait" for v in got)
    got = find(region="Gulf of Aden / Bab el-Mandeb")
    assert got and all(response.sar_region(v["lat"], v["lon"])[0] == "Gulf of Aden / Bab el-Mandeb"
                       for v in got)
    assert find(q="x") == [], "a single letter and no filter scanned the whole fleet"


def test_every_hull_declares_what_it_is_carrying():
    """Cargo decides whether a fire is a fire or a hazmat incident, and it is the
    first thing a responding master asks. An empty field is a wrong answer."""
    sim = Simulator(size=1500)
    missing = [s.mmsi for s in sim.ships.values() if not s.cargo]
    assert not missing, f"{len(missing)} hulls carry nothing at all, e.g. {missing[:3]}"


def test_env_file_never_overrides_a_real_environment_variable():
    """A key exported on the command line has to win over one sitting in .env, or
    `GROQ_API_KEY=... uvicorn ...` silently runs against the wrong account."""
    import os
    import tempfile
    from pathlib import Path

    from sesn import providers

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".env"
        path.write_text("# a comment\nSESN_TEST_A=from-file\nSESN_TEST_B='quoted value'\n")
        os.environ["SESN_TEST_A"] = "from-shell"
        os.environ.pop("SESN_TEST_B", None)
        providers.load_env_file(path)
        assert os.environ["SESN_TEST_A"] == "from-shell", "the file overrode the shell"
        assert os.environ["SESN_TEST_B"] == "quoted value", "quotes were not stripped"
        for k in ("SESN_TEST_A", "SESN_TEST_B"):
            os.environ.pop(k, None)


def test_bulk_release_can_never_reach_a_held_recipient():
    """The ops console lets an operator release the operational drafts in one action.
    Anything not explicitly held there goes out in that batch, so a recipient class
    added to the backend and forgotten in the console would be bulk-released to next
    of kin by default. This is the check that makes the console fail loudly instead."""
    import re
    from pathlib import Path

    from sesn.models import Packet

    js = (Path(__file__).resolve().parent / "web" / "ops.html").read_text()
    ranked = set(re.findall(r"(\w+): \d", re.search(r"const RANK = \{(.+?)\}", js, re.S).group(1)))
    held = set(re.findall(r'"(\w+)"', re.search(r"const HELD = new Set\(\[(.+?)\]", js, re.S).group(1)))

    classes = set(Packet.model_fields["recipient_class"].annotation.__args__)
    assert classes <= ranked, f"ops console does not order {classes - ranked}"
    assert {"manager", "next_of_kin"} <= held, "a held recipient left the held set"
    assert not (held - classes), f"held set names a recipient the backend never sends: {held - classes}"


def test_a_security_incident_is_never_tasked_to_an_unarmed_hull():
    """A tug is SAR-capable and sorts to the top of the responder list, so the naval
    draft used to address one for an active boarding, under a letterhead that talks
    about rules of engagement. For piracy and armed attack the tasked asset must be
    armed, or there must be no tasking draft at all and the recommendation must say
    so. Sending an unarmed tug into a boarding does not rescue anyone, it produces a
    second casualty."""
    from sesn.models import Incident
    from sesn.sim import ARMED

    sim = Simulator(size=4000)
    for fault in ("piracy", "attack"):
        ship = next(s for s in sim.ships.values() if s.route and not s.can_assist)
        sim.inject(ship.mmsi, fault)
        result, _ = triage.run(FAULTS[fault].text, ship.telemetry())
        inc = Incident(id="t", mmsi=ship.mmsi, vessel_name=ship.name, opened_at="now",
                       report_text=FAULTS[fault].text, telemetry=ship.telemetry(),
                       triage=result)
        responders = response.nearest(list(sim.ships.values()), ship, limit=8)
        packets = response.build_packets(inc, ship, responders)

        tasked = [p for p in packets if p.recipient_class == "naval"]
        for p in tasked:
            hull = next(r for r in responders if r.mmsi == p.recipient_mmsi)
            assert hull.kind in ARMED, f"{fault}: tasked {hull.kind} {hull.name} to a boarding"

        region, mrcc = response.sar_region(ship.lat, ship.lon)
        rec = response.recommend(result, responders, mrcc, region)
        if not tasked:
            assert any(a.urgency == "caution" and "no naval or coastguard" in a.text.lower()
                       for a in rec), f"{fault}: no armed asset and nothing said so"


def test_every_classification_has_a_recommended_response():
    """A classification with no doctrine entry silently falls back to the Unknown
    row, which tells an operator to establish voice contact on a confirmed fire."""
    from sesn.models import IncidentType

    missing = [t.value for t in IncidentType if t.value not in response.DOCTRINE]
    assert not missing, f"no response doctrine for {missing}"
    for name, (want, lines, caution) in response.DOCTRINE.items():
        assert want in response._FALLBACK or want == "none", f"{name}: unknown asset class {want}"
        assert lines and caution, f"{name}: doctrine row is empty"


def test_the_recommendation_and_the_drafts_never_name_different_ships():
    """The console shows "Task X" directly above a draft addressed to Y if these are
    computed twice by two different rules, which is how it read before `assign`
    existed: a man overboard recommended the container ship half a mile away while
    the draft on the same screen went to a coastguard cutter an hour out. An operator
    handed two answers has been handed none."""
    import re

    from sesn.models import Incident, IncidentType

    sim = Simulator(size=4000)
    checked = 0
    for fault in FAULTS:
        ship = next(s for s in sim.ships.values() if s.route and not s.distressed)
        sim.inject(ship.mmsi, fault)
        result, _ = triage.run(FAULTS[fault].text, ship.telemetry())
        inc = Incident(id="t", mmsi=ship.mmsi, vessel_name=ship.name, opened_at="now",
                       report_text=FAULTS[fault].text, telemetry=ship.telemetry(),
                       triage=result)
        responders = response.nearest(list(sim.ships.values()), ship, limit=8)
        packets = response.build_packets(inc, ship, responders)
        region, mrcc = response.sar_region(ship.lat, ship.lon)
        rec = response.recommend(result, responders, mrcc, region)

        task = next((a for a in rec if a.text.startswith("Task ")), None)
        if task is None:
            # No asset of the wanted class was in range. The duty-to-assist ask may
            # still stand on its own -- its body carries the hazard and the master
            # decides -- but nothing may be tasked as a response asset.
            assert not [p for p in packets if p.recipient_class == "naval"], (
                f"{fault}: tasked a response asset that the recommendation never named")
            continue
        named = re.match(r"Task (.+?) \(", task.text).group(1)
        assert any(p.recipient_name.startswith(named) for p in packets if p.recipient_mmsi), (
            f"{fault}: recommendation says task {named!r}, "
            f"drafts went to {[p.recipient_name for p in packets if p.recipient_mmsi]}")
        checked += 1
    # Not every fault reaches a tasking: the silent beacons classify Unknown, and some
    # positions have no asset of the wanted class in range. The floor is here so the
    # loop cannot quietly end up asserting nothing at all.
    assert checked >= 6, f"only {checked} faults exercised a tasking path"


def test_an_unestablished_classification_drafts_no_tasking():
    """A bare beacon names no incident. Drafting a rules-of-engagement tasking off one
    is exactly the guess the triage contract refuses to make, and it must not reappear
    one layer down in the response builder."""
    from sesn.models import Incident, IncidentType, Severity, TriageResult

    sim = Simulator(size=2000)
    ship = next(s for s in sim.ships.values() if s.route)
    result = TriageResult(type=IncidentType.UNKNOWN, severity=Severity.HIGH,
                          confidence=0.3, unknowns=["nature of distress"],
                          rationale="AIS-SART with no voice contact.")
    inc = Incident(id="t", mmsi=ship.mmsi, vessel_name=ship.name, opened_at="now",
                   report_text="", telemetry=ship.telemetry(), triage=result)
    packets = response.build_packets(inc, ship, response.nearest(list(sim.ships.values()), ship))
    classes = [p.recipient_class for p in packets]
    assert "naval" not in classes and "merchant" not in classes, (
        f"tasked a hull off an unestablished classification: {classes}")
    assert "mrcc" in classes, "an unknown beacon must still reach the rescue centre"


def test_own_ship_marker_plots_lon_lat_in_that_order():
    """The bridge map draws a "you are here" marker for the signed-in hull, from the
    tick when the frame carries it and from the last situation poll when the server
    has culled it out of view.

    GeoJSON is [lon, lat] and every other surface in this system says lat first, so a
    swap here is one transposed pair away and puts a master's own ship in the wrong
    ocean while looking entirely plausible. Runs the real function under node rather
    than trusting a reading of it; skips if node is absent, as check_web.py does.
    """
    import json
    import re
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        print("  ..  node not found, skipping own-ship marker check")
        return

    src = (Path(__file__).resolve().parent / "web" / "vessel.html").read_text()
    start = src.index("function drawMe(frame) {")
    depth, i = 0, src.index("{", start)
    for i in range(i, len(src)):                      # balance to the closing brace
        depth += (src[i] == "{") - (src[i] == "}")
        if depth == 0:
            break
    drawMe = src[start:i + 1]
    assert "setData" in drawMe, "extracted the wrong block"

    harness = """
    let painted = null;
    const SESN = { fc: features => ({ type: "FeatureCollection", features }) };
    const map = { getSource: () => ({ setData: d => { painted = d; } }) };
    let me = null, mineNow = null;
    %s
    const out = [];
    const run = (label, frame) => {
      drawMe(frame);
      out.push([label, painted.features.map(f => f.geometry.coordinates)]);
    };
    me = "111"; mineNow = { lat: 51.5, lon: -0.1 };
    run("from frame", { rows: [["999", 1, 2, 0, 0, 0], ["111", 51.5, -0.1, 0, 0, 0]] });
    run("culled, falls back to poll", { rows: [["999", 1, 2, 0, 0, 0]] });
    mineNow = null;
    run("no position known at all", { rows: [] });
    me = null; mineNow = { lat: 51.5, lon: -0.1 };
    run("signed out", { rows: [["111", 51.5, -0.1, 0, 0, 0]] });
    console.log(JSON.stringify(out));
    """ % drawMe

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "marker.js"
        path.write_text(harness)
        proc = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    got = dict(json.loads(proc.stdout))

    # GeoJSON order, so longitude first. A swap reads as 51.5E off Somalia.
    assert got["from frame"] == [[-0.1, 51.5]], got["from frame"]
    assert got["culled, falls back to poll"] == [[-0.1, 51.5]], got["culled, falls back to poll"]
    assert got["no position known at all"] == [], got["no position known at all"]
    assert got["signed out"] == [], got["signed out"]


def test_every_recipient_class_has_a_plain_language_explainer():
    """Both consoles describe the five recipients from one table in common.js. An
    operator releasing a message to "MRCC SIM-TASMAN" and a master reading who was
    told about their own fire must get the same answer, and a recipient class added
    to the backend with no entry here shows the crew a bare "next_of_kin" instead."""
    import re
    from pathlib import Path

    from sesn.models import Packet

    js = (Path(__file__).resolve().parent / "web" / "common.js").read_text()
    block = re.search(r"const RECIPIENTS = \{(.+?)\n  \};", js, re.S).group(1)
    described = set(re.findall(r"^    (\w+): \{", block, re.M))

    classes = set(Packet.model_fields["recipient_class"].annotation.__args__)
    assert classes == described, f"explainer table and Packet disagree: {classes ^ described}"
    # Every entry must carry both halves. A label with no `plain` silently renders the
    # empty string under the packet header, which reads as a layout bug, not a gap.
    for name in described:
        entry = re.search(r"    %s: \{(.+?)\n    \}," % name, block, re.S).group(1)
        assert "label:" in entry and "plain:" in entry, f"{name} is missing label or plain"
        assert len(entry) > 200, f"{name}: explainer is too short to explain anything"


def test_repaint_holds_scroll_only_while_the_view_is_the_same():
    """Both consoles repaint whole panels when a tick lands, and innerHTML resets the
    scroll of the box the panel sits in: a master reading the bottom of an incident
    was yanked back to the top every four seconds.

    The inverse is just as wrong. Restoring the offset when the operator has moved to
    a *different* packet drops them into the middle of a draft they have not started
    reading, which is a worse failure than the one being fixed: it looks like they
    read it. Runs the real helper under node; skips if node is absent.
    """
    import json
    import re
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        print("  ..  node not found, skipping repaint check")
        return

    src = (Path(__file__).resolve().parent / "web" / "common.js").read_text()
    start = src.index("  function repaint(")
    depth, i = 0, src.index("{", start)
    for i in range(i, len(src)):
        depth += (src[i] == "{") - (src[i] == "}")
        if depth == 0:
            break
    fn = src[start:i + 1]
    assert "dataset.view" in fn, "extracted the wrong block"

    harness = """
    // Smallest DOM that can express the bug: a scrolling box whose offset survives or
    // does not survive an innerHTML write.
    const box = { scrollTop: 0 };
    const el = {
      dataset: {},
      _html: "",
      set innerHTML(v) { this._html = v; box.scrollTop = 0; },   // what a browser does
      get innerHTML() { return this._html; },
      querySelector: () => box,
      closest: () => box,
    };
    %s
    const out = [];
    const step = (label, key, scrollTo) => {
      box.scrollTop = scrollTo;
      repaint(el, "<p>x</p>", ".pane", key);
      out.push([label, box.scrollTop]);
    };
    step("first paint", "step-1", 0);
    step("tick, same view, reader is 420px down", "step-1", 420);
    step("operator moves to another packet", "step-2", 420);
    step("tick again on the new packet", "step-2", 90);
    console.log(JSON.stringify(out));
    """ % fn

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "repaint.js"
        path.write_text(harness)
        proc = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    got = dict(json.loads(proc.stdout))

    assert got["tick, same view, reader is 420px down"] == 420, got
    assert got["operator moves to another packet"] == 0, got
    assert got["tick again on the new packet"] == 90, got


def test_every_page_carries_the_simulation_banner():
    """Hard constraints 2 and 6: every page says it is a simulation and that it sits
    beside GMDSS, never in place of it, in a banner above everything else. A restyle is
    exactly when one page quietly loses its banner, and the page still looks finished."""
    import re
    from pathlib import Path

    pages = sorted((Path(__file__).resolve().parent / "web").glob("*.html"))
    assert len(pages) >= 4, f"expected the landing page and three portals, found {pages}"
    for page in pages:
        banner = re.search(r'<div class="simbar">(.*?)</div>', page.read_text(), re.S)
        assert banner, f"{page.name} has no simulation banner"
        text = " ".join(re.sub(r"<[^>]+>", " ", banner.group(1)).lower().split())
        assert "simulat" in text, f"{page.name}: the banner never says this is a simulation"
        assert "gmdss" in text and "never a replacement" in text, (
            f"{page.name}: the banner drops 'supplementary to GMDSS, never a replacement'")


def test_a_double_tap_raises_one_incident_and_every_draft_says_why():
    """A master who taps "Send to shore" twice has one emergency. Two incidents means two
    notifications to the same rescue centre. And a tasking draft that cannot say which
    of its reasons came from the model is asking the operator to sign a black box."""
    from fastapi.testclient import TestClient

    from sesn.main import app, incidents

    client = TestClient(app)
    mmsi = client.get("/api/search", params={"sample": 1}).json()[0]["mmsi"]
    ids = {client.post("/api/inject", json={"mmsi": mmsi, "fault": "collision"}).json()["id"]
           for _ in range(3)}
    assert len(ids) == 1, f"three taps opened {len(ids)} incidents"
    text = {"mmsi": mmsi, "text": "we have hit a fishing boat"}
    assert client.post("/api/report", json=text).json()["id"] == \
           client.post("/api/report", json=text).json()["id"], "a repeated report duplicated"

    inc = incidents[ids.pop()]
    for pk in inc.packets:
        assert pk.reasoning, f"{pk.recipient_class} draft carries no reasoning"
        if pk.recipient_class in ("mrcc", "naval", "merchant"):
            bases = {a.basis for a in pk.reasoning}
            assert "classification" in bases and bases - {"classification"}, pk.recipient_class

    client.post(f"/api/clear/{mmsi}")
    again = client.post("/api/inject", json={"mmsi": mmsi, "fault": "collision"}).json()["id"]
    assert again != inc.id, "after stand-down a real second emergency was swallowed"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")
