"""Typed contracts. Every boundary in the system speaks these: the simulator,
the triage graph, the websocket, and the eval suite. Nothing passes dicts around."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class IncidentType(str, Enum):
    """`UNKNOWN` is a first-class answer, not a failure. A bare SART hit with no
    voice contact genuinely does not name an incident type, and a triage that
    guesses there is worse than one that abstains and says what it needs."""

    UNKNOWN = "Unknown"
    PIRACY = "Piracy"
    ATTACK = "Attack"
    FIRE = "Fire"
    FLOODING = "Flooding"
    COLLISION = "Collision"
    GROUNDING = "Grounding"
    MACHINERY_FAILURE = "MachineryFailure"
    MEDICAL_EVACUATION = "MedicalEvacuation"
    MAN_OVERBOARD = "ManOverboard"
    CREW_ABANDONMENT = "CrewAbandonment"


class Severity(int, Enum):
    LOW = 1
    MODERATE = 2
    HIGH = 3
    CRITICAL = 4


# ITU-R M.1371 navigational status. Only the ones the simulator actually produces.
class NavStatus(int, Enum):
    UNDER_WAY = 0
    AT_ANCHOR = 1
    NOT_UNDER_COMMAND = 2
    MOORED = 5
    AGROUND = 6
    UNDEFINED = 15


class Telemetry(BaseModel):
    """The structured half of a triage input. What the feed says, independent of
    what anyone reported by voice."""

    mmsi: str
    lat: float
    lon: float
    speed_kn: float = Field(alias="speedKn")
    nav_status: int = Field(alias="navStatus")

    # Accept either spelling, always emit the camelCase one. The portals read a
    # single wire vocabulary; an incident whose telemetry serialised as snake_case
    # rendered as "undefined kn" in the ops console for exactly this reason.
    model_config = {"populate_by_name": True, "serialize_by_alias": True}



class TriageResult(BaseModel):
    """What the triage agent must return. `unknowns` is part of the contract, not a
    nicety. The operator has to see what the classification does *not* rest on."""

    type: IncidentType
    severity: Severity
    confidence: float
    unknowns: list[str] = []
    rationale: str = ""
    provider: str = "baseline"
    latency_ms: int = 0


class Responder(BaseModel):
    """A candidate hull. Carried on the incident so the console can show *why* a
    particular ship was drafted to, and what else was in range and passed over."""

    mmsi: str
    name: str
    kind: str
    distance_nm: float
    eta_hours: float | None = None
    sar_capable: bool = False
    # Armed is not the same as SAR-capable and the difference decides a piracy case.
    # A tug is `sar_capable` and sorts to the top of the responder list; tasking one
    # into an active boarding is not a rescue, it is a second casualty.
    armed: bool = False


class Action(BaseModel):
    """One recommended step, in order. `basis` is part of the contract: an operator
    is entitled to know which half of a recommendation was a model's judgement and
    which was standing policy, and so is a marine board reading the log later."""

    text: str
    urgency: Literal["now", "next", "caution"] = "next"
    basis: Literal["classification", "policy", "geometry"] = "policy"


class Packet(BaseModel):
    """A drafted outbound message. `approved` starts false and only an operator
    action changes it. Nothing in this system sends on its own."""

    recipient_class: Literal["mrcc", "merchant", "naval", "manager", "next_of_kin"]
    recipient_name: str
    # Set only for packets addressed to a hull in the simulation. It is what lets
    # the bridge be told a live ETA for the ship that was actually asked to come,
    # rather than the distance that happened to be true when the draft was written.
    recipient_mmsi: str | None = None
    subject: str
    body: str
    # How this draft came to exist, in order, each line tagged with its basis. The
    # operator has to see which step was the model and which was procedure or distance.
    reasoning: list[Action] = []
    approved: bool = False
    rejected: bool = False
    # Who decided, and when. The bridge is told the name: a crew that can see their
    # alert was released, but not by whom, is still being asked to trust a black box.
    decided_by: str | None = None
    decided_at: str | None = None


class Incident(BaseModel):
    id: str
    mmsi: str
    vessel_name: str
    opened_at: str
    report_text: str
    telemetry: Telemetry
    triage: TriageResult | None = None
    packets: list[Packet] = []
    # Everything that was in range, not only the three that got a draft. The console
    # shows the shortlist so an operator can see what was passed over and overrule it.
    responders: list[Responder] = []
    recommendation: list[Action] = []
    injected_fault: str | None = None
