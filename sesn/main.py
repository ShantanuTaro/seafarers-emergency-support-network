"""FastAPI: simulator, three portals, approval gate, audit log.

Three separate front ends over one world:

  /vessel   seafarer portal, for a master or crew member aboard one ship
  /ops      operations portal, for the shore watch: queue and approvals
  /control  control panel, for fault injection and simulator control

They are separate because the jobs are separate. A master needs to know that shore
has seen them and who is coming; a watchkeeper needs a queue and an approval gate;
an engineer needs to break things. One screen serving all three is how real ops
consoles end up unusable.

The approval gate lives here and only here. `build_packets` creates every packet
unapproved and nothing but an operator action flips that bit.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import providers, response, triage
from .models import Incident, Telemetry
from .sim import FAULTS, KINDS, Ship, Simulator, haversine_nm

TICK_SECONDS = 5.0
ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
AUDIT_PATH = ROOT / "audit.jsonl"

sim = Simulator()
incidents: dict[str, Incident] = {}
# Direct operator <-> bridge traffic, per vessel. Not a packet and not gated: a
# message here is composed and sent by a named human, which is what the gate exists
# to guarantee for the generated ones. Logged either way.
messages: dict[str, list[dict]] = {}
clients: dict[WebSocket, dict] = {}  # ws -> {"bounds": [...], "cap": int}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def audit(event: str, **fields) -> None:
    """Append-only. Assume every line becomes evidence in a marine board inquiry:
    never rewritten, never deleted, and an approval always carries a name."""
    with AUDIT_PATH.open("a") as fh:
        fh.write(json.dumps({"ts": _now(), "event": event, **fields}) + "\n")


def _ship_detail(s: Ship) -> dict:
    return {
        "mmsi": s.mmsi, "name": s.name, "operator": s.operator, "kind": s.kind,
        "flag": s.flag, "pob": s.pob, "lat": round(s.lat, 4), "lon": round(s.lon, 4),
        "course": round(s.course), "speed": round(s.speed_kn, 1),
        "navStatus": s.nav_status, "corridor": s.corridor, "cargo": s.cargo,
        "destination": s.destination, "distressed": s.distressed,
        "dark": s.ais_dark, "fault": s.injected_fault,
        "sarCapable": s.can_assist,
    }


async def _tick_loop() -> None:
    while True:
        sim.tick(TICK_SECONDS)
        stats = sim.stats()
        distressed = [_ship_detail(s) for s in sim.distressed()]
        dead = []
        for ws, cfg in list(clients.items()):
            rows, total = sim.frame(cfg.get("bounds"), cfg.get("cap", 2500))
            try:
                await ws.send_json({
                    "type": "frame", "ts": _now(), "rows": rows,
                    "inView": total, "stats": stats, "distressed": distressed,
                    "incidents": len(incidents),
                })
            except (WebSocketDisconnect, RuntimeError):
                dead.append(ws)
        for ws in dead:
            clients.pop(ws, None)
        await asyncio.sleep(TICK_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_tick_loop())
    audit("system.start", fleet=len(sim.ships))
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Seafarers Emergency Support Network (simulation)", lifespan=lifespan)


@app.middleware("http")
async def no_stale_assets(request, call_next):
    """The portals are static files with no build step and no content hashing, so a
    browser holding yesterday's common.js against today's ops.html gets a map with
    no ships on it and no error anyone will see. Revalidate everything: this is a
    single-process demo on localhost, not a CDN."""
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


class InjectRequest(BaseModel):
    mmsi: str
    fault: str
    source: str = "control-panel"
    comment: str = ""  # optional, from the bridge: what the crew adds to the button they pressed


class ReportRequest(BaseModel):
    mmsi: str
    text: str


class ApprovalRequest(BaseModel):
    operator: str


class MessageRequest(BaseModel):
    text: str
    author: str = ""
    frm: str = "vessel"  # "vessel" from the bridge, "shore" from the ops console


def _open_incident(mmsi: str, text: str, telemetry: Telemetry,
                   fault_label: str | None, source: str,
                   comment: str | None = None) -> Incident:
    ship = sim.ships[mmsi]
    result, trace = triage.run(text, telemetry)
    incident = Incident(
        id=uuid.uuid4().hex[:8], mmsi=mmsi, vessel_name=ship.name,
        opened_at=_now(), report_text=text, telemetry=telemetry,
        triage=result, injected_fault=fault_label, crew_comment=comment)
    fleet = list(sim.ships.values())
    responders = response.nearest(fleet, ship, limit=8)
    # `nearest` weights dedicated SAR assets ahead of merchant traffic, so in a busy
    # lane the whole ranked list can be tugs and coastguard and the duty-to-assist
    # draft ends up addressed to the same tug that was already tasked. Carry one
    # nearest merchant alongside, so the two drafts reach two different bridges.
    responders += response.nearest([v for v in fleet if not v.can_assist], ship, limit=1)
    region, mrcc = response.sar_region(ship.lat, ship.lon)
    incident.responders = responders
    incident.recommendation = response.recommend(result, responders, mrcc, region)
    incident.packets = response.build_packets(incident, ship, responders)
    incidents[incident.id] = incident
    audit("incident.opened", incident=incident.id, mmsi=mmsi, source=source,
          injected_fault=fault_label, report_text=text,
          telemetry=telemetry.model_dump(by_alias=True),
          triage=result.model_dump(mode="json"), trace=trace,
          recommendation=[a.text for a in incident.recommendation],
          packets_drafted=len(incident.packets))
    return incident


def _already_open(mmsi: str, fault_label: str | None, text: str) -> Incident | None:
    """A second tap on "Send to shore" is the same distress, not a new one. While the
    hull is still in distress, an identical fault or report returns the open incident
    instead of drafting a second set of messages to the same rescue centre."""
    if not sim.ships[mmsi].distressed:
        return None
    return next((i for i in reversed(incidents.values()) if i.mmsi == mmsi
                 and i.injected_fault == fault_label and i.report_text == text), None)


async def _announce(incident: Incident) -> None:
    payload = {"type": "incident", "incident": incident.model_dump(mode="json")}
    for ws in list(clients):
        with contextlib.suppress(Exception):
            await ws.send_json(payload)


# ---- incident lifecycle ---------------------------------------------------

@app.post("/api/inject")
async def inject(req: InjectRequest):
    """Control panel: stage a fault. Mutates telemetry, not just a label."""
    if req.mmsi not in sim.ships:
        raise HTTPException(404, "unknown vessel")
    if req.fault not in FAULTS:
        raise HTTPException(400, f"unknown fault: {req.fault}")
    fault = FAULTS[req.fault]
    # The crew's comment is read by triage alongside the report the button stands for,
    # so the classification, its unknowns and the drafts work from what the bridge said.
    comment = req.comment.strip()[:2000]
    text = f"{fault.text}\n\nCrew comment: {comment}".strip() if comment else fault.text
    if dup := _already_open(req.mmsi, fault.label, text):
        audit("incident.duplicate_ignored", incident=dup.id, mmsi=req.mmsi, source=req.source)
        return dup
    ship, fault, beacon = sim.inject(req.mmsi, req.fault)
    # A beacon with no accompanying report is the hard case: triage sees only the
    # beacon's own telemetry, which is exactly what a shore watch gets.
    telemetry = beacon.telemetry() if (beacon and not text) else ship.telemetry()
    incident = _open_incident(req.mmsi, text, telemetry, fault.label, req.source,
                              comment or None)
    await _announce(incident)
    return incident


@app.post("/api/report")
async def manual_report(req: ReportRequest):
    """Seafarer portal and ops manual intake: free text as actually received."""
    if req.mmsi not in sim.ships:
        raise HTTPException(404, "unknown vessel")
    if not req.text.strip():
        raise HTTPException(400, "a report cannot be empty")
    if dup := _already_open(req.mmsi, None, req.text.strip()):
        audit("incident.duplicate_ignored", incident=dup.id, mmsi=req.mmsi, source="vessel-report")
        return dup
    ship = sim.ships[req.mmsi]
    ship.distressed = True
    incident = _open_incident(req.mmsi, req.text.strip(), ship.telemetry(), None, "vessel-report")
    await _announce(incident)
    return incident


@app.post("/api/incidents/{incident_id}/packets/{index}/{decision}")
async def decide(incident_id: str, index: int, decision: str, req: ApprovalRequest):
    """The approval gate. The only thing that can mark a packet approved, and it
    requires a named approver."""
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")
    incident = incidents.get(incident_id)
    if not incident:
        raise HTTPException(404, "unknown incident")
    if not 0 <= index < len(incident.packets):
        raise HTTPException(404, "unknown packet")
    if not req.operator.strip():
        raise HTTPException(400, "an approver identity is required")
    packet = incident.packets[index]
    if packet.approved or packet.rejected:
        raise HTTPException(409, "packet has already been decided")
    packet.approved = decision == "approve"
    packet.rejected = decision == "reject"
    packet.decided_by = req.operator.strip()
    packet.decided_at = _now()
    audit(f"packet.{decision}d", incident=incident_id, index=index,
          recipient_class=packet.recipient_class, recipient=packet.recipient_name,
          operator=req.operator.strip(), subject=packet.subject)
    await _announce(incident)
    return packet


@app.post("/api/vessel/{mmsi}/message")
async def send_message(mmsi: str, req: MessageRequest):
    """A line of text between the shore watch and the bridge, both directions.

    Shore-side messages carry the operator's name for the same reason approvals do:
    the log has to say who said it. Nothing here is a GMDSS distress relay and the
    portals say so.
    """
    if mmsi not in sim.ships:
        raise HTTPException(404, "unknown vessel")
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "a message cannot be empty")
    if req.frm not in ("vessel", "shore"):
        raise HTTPException(400, "frm must be vessel or shore")
    author = req.author.strip()
    if req.frm == "shore" and not author:
        raise HTTPException(400, "a shore message requires the operator's name")
    msg = {"ts": _now(), "frm": req.frm,
           "author": author or sim.ships[mmsi].name, "text": text}
    thread = messages.setdefault(mmsi, [])
    thread.append(msg)
    del thread[:-200]  # a bridge terminal is not an archive
    audit("message.sent", mmsi=mmsi, frm=req.frm, author=msg["author"], text=text)
    payload = {"type": "message", "mmsi": mmsi, "message": msg}
    for ws in list(clients):
        with contextlib.suppress(Exception):
            await ws.send_json(payload)
    return msg


@app.get("/api/vessel/{mmsi}/messages")
async def read_messages(mmsi: str):
    if mmsi not in sim.ships:
        raise HTTPException(404, "unknown vessel")
    return messages.get(mmsi, [])


@app.post("/api/clear/{mmsi}")
async def clear(mmsi: str):
    if mmsi not in sim.ships:
        raise HTTPException(404, "unknown vessel")
    sim.clear(mmsi)
    audit("vessel.cleared", mmsi=mmsi)
    return {"ok": True}


# ---- reads ----------------------------------------------------------------

@app.get("/api/faults")
async def fault_catalogue():
    return [{"key": k, "label": f.label, "silent": not f.text,
             "beacon": f.beacon_prefix} for k, f in FAULTS.items()]


@app.get("/api/kinds")
async def kinds():
    return KINDS


@app.get("/api/stats")
async def stats():
    return {**sim.stats(), "incidents": len(incidents),
            "pendingPackets": sum(1 for i in incidents.values()
                                  for p in i.packets if not (p.approved or p.rejected)),
            "llmProviders": [{"name": p.name, "model": p.model_name,
                              "keyed": bool(p.key), "available": p.available}
                             for p in providers.CHAIN]}


@app.get("/api/search")
async def search(q: str = "", kind: str = "", flag: str = "", region: str = "",
                 area: str = "", limit: int = 20, sample: int = 0):
    """Name or MMSI, optionally narrowed by type, flag, SAR region and area (lane,
    anchorage or fishing ground). A linear scan over 60k hulls is a few milliseconds
    and an index would be a lie about how often this is called. The region test runs
    last because it is the only one that costs anything."""
    ql = q.strip().lower()
    if len(ql) < 2 and not (kind or flag or region or area):
        # A blank gate is a dead end for a demo. Unseeded on purpose: the sim's own RNG
        # must not be advanced by someone browsing, or a scenario stops replaying exactly.
        crewed = [s for s in sim.ships.values() if s.pob] if sample else []
        return [_ship_detail(s) for s in random.sample(crewed, min(sample, 200, len(crewed)))]
    hits = [s for s in sim.ships.values()
            if (not ql or ql in s.name.lower() or s.mmsi.startswith(ql))
            and (not kind or s.kind == kind) and (not flag or s.flag == flag)
            and (not area or s.corridor == area)
            and (not region or response.sar_region(s.lat, s.lon)[0] == region)]
    hits.sort(key=lambda s: (not s.distressed, s.name))
    return [_ship_detail(s) for s in hits[:max(1, min(limit, 200))]]


@app.get("/api/directory")
async def directory():
    """The choices behind the bridge sign-in filters, drawn from the fleet itself so a
    filter never offers an option that matches nothing."""
    ships = [s for s in sim.ships.values() if s.pob]
    return {
        "kinds": KINDS,
        "flags": sorted({s.flag for s in ships}),
        "regions": sorted({response.sar_region(s.lat, s.lon)[0] for s in ships}),
        "areas": sorted({s.corridor for s in ships if s.corridor}),
    }


@app.get("/api/vessel/{mmsi}")
async def vessel(mmsi: str):
    s = sim.ships.get(mmsi)
    if not s:
        raise HTTPException(404, "unknown vessel")
    return _ship_detail(s)


@app.get("/api/vessel/{mmsi}/situation")
async def situation(mmsi: str):
    """The seafarer view, and the thing current systems do worst: once a ship has
    declared distress, the crew usually cannot see whether anyone ashore has picked
    it up, what was concluded, or who is coming. This returns exactly that."""
    s = sim.ships.get(mmsi)
    if not s:
        raise HTTPException(404, "unknown vessel")
    mine = [i for i in incidents.values() if i.mmsi == mmsi]
    mine.sort(key=lambda i: i.opened_at, reverse=True)
    nearby = response.nearest(list(sim.ships.values()), s, limit=6)
    latest = mine[0] if mine else None
    return {
        "vessel": _ship_detail(s),
        # Position and speed ride along so the bridge map can draw the line to a
        # responder and keep its ETA current between polls.
        "nearby": [{**r.model_dump(), "lat": round(sim.ships[r.mmsi].lat, 4),
                    "lon": round(sim.ships[r.mmsi].lon, 4),
                    "speed": round(sim.ships[r.mmsi].speed_kn, 1)} for r in nearby],
        "shoreStatus": _shore_status(latest),
        "messages": messages.get(mmsi, []),
        # Every incident this hull has raised, newest first, each carrying its own
        # shore status and per-recipient state. One array rather than a "latest" plus a
        # thinner "history": the bridge opens any of them and expects the same detail,
        # and a crew reading a three-hour-old incident deserves the same answer as one
        # reading the live one.
        "incidents": [{**i.model_dump(mode="json"),
                       "actions": _actions(i, s),
                       "shoreStatus": _shore_status(i)} for i in mine],
    }


def _actions(incident: Incident | None, casualty: Ship | None) -> list[dict]:
    """Per-recipient state of every drafted message, for the bridge.

    The crew asked shore for help; what they need back is who was asked, whether it
    was actually released, and when that ship will arrive. The ETA is recomputed
    from live positions on every read rather than quoted from the draft, because a
    responder's ETA at the moment of drafting is already wrong.
    """
    if not incident or not casualty:
        return []
    out = []
    for p in incident.packets:
        row = {
            "recipient_class": p.recipient_class,
            "recipient_name": p.recipient_name,
            "state": "released" if p.approved else "declined" if p.rejected else "pending",
            "decided_by": p.decided_by, "decided_at": p.decided_at,
            "distance_nm": None, "eta_hours": None, "kind": None,
        }
        responder = sim.ships.get(p.recipient_mmsi or "")
        if responder:
            nm = haversine_nm(casualty.lat, casualty.lon, responder.lat, responder.lon)
            row["kind"] = responder.kind
            row["distance_nm"] = round(nm, 1)
            row["eta_hours"] = (round(nm / responder.speed_kn, 1)
                                if responder.speed_kn > 0.5 else None)
        out.append(row)
    return out


def _shore_status(incident: Incident | None) -> dict:
    """Plain-language answer to the only question that matters on the bridge:
    has anyone ashore actually done anything yet?"""
    if not incident:
        return {"state": "no_incident",
                "text": "No active incident. Telemetry is being monitored ashore."}
    approved = [p for p in incident.packets if p.approved]
    pending = [p for p in incident.packets if not (p.approved or p.rejected)]
    if approved:
        # With the approver's name. A crew told that something was released, but not by
        # whom, is still being asked to trust a black box on the worst day of their lives.
        who = sorted({p.decided_by for p in approved if p.decided_by})
        return {"state": "notified",
                "text": f"{len(approved)} of {len(incident.packets)} notifications "
                        f"approved and released by "
                        + (", ".join(who) if who else "a shore operator") + ".",
                "released": [p.recipient_name for p in approved]}
    if pending:
        return {"state": "awaiting_approval",
                "text": "Shore has received your alert and an operator is reviewing it "
                        "now. Nothing has been sent onward yet."}
    return {"state": "rejected",
            "text": "Shore reviewed the drafted notifications and released none of "
                    "them. Contact the operations room directly."}


@app.get("/api/incidents")
async def list_incidents():
    return [i.model_dump(mode="json") for i in
            sorted(incidents.values(), key=lambda i: i.opened_at, reverse=True)]


@app.get("/api/audit")
async def audit_tail(limit: int = 200):
    if not AUDIT_PATH.exists():
        return []
    return [json.loads(x) for x in AUDIT_PATH.read_text().strip().splitlines()[-limit:]]


# ---- simulator control (control panel only) -------------------------------

@app.post("/api/sim/{action}")
async def sim_control(action: str):
    if action not in ("pause", "resume"):
        raise HTTPException(400, "action must be pause or resume")
    sim.paused = action == "pause"
    audit(f"sim.{action}d")
    return sim.stats()


# ---- websocket ------------------------------------------------------------

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    clients[websocket] = {"bounds": None, "cap": 2500}
    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            if "bounds" in msg:
                clients[websocket]["bounds"] = msg["bounds"]
            if "cap" in msg:
                clients[websocket]["cap"] = max(100, min(6000, int(msg["cap"])))
    except (WebSocketDisconnect, json.JSONDecodeError):
        pass
    finally:
        clients.pop(websocket, None)


# ---- portals --------------------------------------------------------------

@app.get("/")
async def home():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/ops")
async def ops():
    return FileResponse(WEB_DIR / "ops.html")


@app.get("/control")
async def control():
    return FileResponse(WEB_DIR / "control.html")


@app.get("/vessel")
async def vessel_portal():
    return FileResponse(WEB_DIR / "vessel.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
