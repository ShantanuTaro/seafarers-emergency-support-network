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

    model_config = {"populate_by_name": True}



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


class Packet(BaseModel):
    """A drafted outbound message. `approved` starts false and only an operator
    action changes it. Nothing in this system sends on its own."""

    recipient_class: Literal["mrcc", "merchant", "naval", "manager", "next_of_kin"]
    recipient_name: str
    subject: str
    body: str
    approved: bool = False
    rejected: bool = False


class Incident(BaseModel):
    id: str
    mmsi: str
    vessel_name: str
    opened_at: str
    report_text: str
    telemetry: Telemetry
    triage: TriageResult | None = None
    packets: list[Packet] = []
    injected_fault: str | None = None
