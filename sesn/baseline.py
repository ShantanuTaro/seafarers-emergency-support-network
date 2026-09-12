"""Deterministic keyword + AIS-rule classifier.

This is not the product. It is the floor. An LLM triage that cannot beat this on the
eval corpus is not earning its latency, its cost, or its failure modes, and the
README says so. It is also the offline fallback: with no API key configured, the
portal still classifies, so the demo never depends on a free tier being up.

The term lists are written from maritime vocabulary, not reverse-engineered from the
corpus. Tuning them against the graded scenarios would make the floor meaningless.
"""

from __future__ import annotations

from .models import IncidentType as T
from .models import Severity as S
from .models import Telemetry, TriageResult

# Ordered: earlier types win ties. An attack that starts a fire is an attack; a
# grounding that floods the engine room is a grounding. Cause outranks effect,
# because the cause is what determines who is legally responsible for responding.
RULES: list[tuple[T, list[str]]] = [
    (T.ATTACK, ["missile", "drone", "uav", "unmanned", "projectile", "explosion",
                "detonat", "shrapnel"]),
    (T.PIRACY, ["pirate", "piracy", "skiff", "armed", "boarded", "boarding", "hijack",
                "robbery", "citadel", "ladder", "knives", "weapons"]),
    (T.CREW_ABANDONMENT, ["abandon", "liferaft", "life raft", "free-fall boat", "epirb"]),
    (T.MAN_OVERBOARD, ["overboard", "man over", "person in the water", "williamson",
                       "lifebuoy", "went over the side"]),
    (T.FIRE, ["fire", "smoke", "burn", "blaze", "co2", "boundary cooling", "extinguish"]),
    (T.FLOODING, ["ingress", "flood", "taking on water", "hull breach",
                  "breach in the hull", "bilge alarm", "list has increased",
                  "below the waterline"]),
    (T.GROUNDING, ["aground", "grounded", "grounding", "ran aground",
                   "touched the bottom", "reef", "shoal", "refloat"]),
    (T.COLLISION, ["collision", "collided", "struck a", "made contact with",
                   "contact with the quay", "allision"]),
    (T.MACHINERY_FAILURE, ["engine has shut down", "main engine", "blackout",
                           "loss of power", "loss of propulsion", "not under command",
                           "steering gear", "generator", "rudder", "cannot be restarted"]),
    (T.MEDICAL_EVACUATION, ["medevac", "medical", "chest pain", "unconscious",
                            "fracture", "appendicitis", "patient", "bleeding",
                            "casualty", "injured"]),
]

BASE_SEVERITY: dict[T, S] = {
    T.ATTACK: S.CRITICAL,
    T.PIRACY: S.HIGH,
    T.CREW_ABANDONMENT: S.CRITICAL,
    T.MAN_OVERBOARD: S.CRITICAL,
    T.FIRE: S.HIGH,
    T.FLOODING: S.HIGH,
    T.GROUNDING: S.HIGH,
    T.COLLISION: S.HIGH,
    T.MACHINERY_FAILURE: S.MODERATE,
    T.MEDICAL_EVACUATION: S.HIGH,
    T.UNKNOWN: S.HIGH,
}

ESCALATORS = ["immediate", "urgent", "cannot keep up", "sinking", "going down",
              "requesting assistance", "need assistance"]
DEESCALATORS = ["no injuries", "no damage", "extinguished", "resumed",
                "for the record", "for awareness", "no impact"]


NEGATIONS = ("no ", "not ", "without ", "negative ")


def _mentions(low: str, term: str) -> bool:
    """True if the term appears and is not directly negated. Reports are full of
    "no ingress" and "no injuries"; counting those as positive evidence is how a
    keyword classifier turns a collision into a flooding."""
    start = 0
    while (i := low.find(term, start)) != -1:
        prefix = low[max(0, i - 12):i]
        if not any(prefix.rstrip().endswith(n.strip()) for n in NEGATIONS):
            return True
        start = i + len(term)
    return False


def classify(text: str, telemetry: Telemetry | None) -> TriageResult:
    low = (text or "").lower()

    scores = {t: sum(1 for k in terms if _mentions(low, k)) for t, terms in RULES}
    text_matched = any(v > 0 for v in scores.values())

    # Nav status 6 is a fact from the vessel's own transmitter, and it breaks ties
    # between competing text readings (a grounding that floods is still a grounding)
    # but it must never manufacture a text match on its own, or a silent incident
    # gets a confident classification with nothing to quote and no unknowns declared.
    if text_matched and telemetry and telemetry.nav_status == 6:
        scores[T.GROUNDING] += 1

    order = {t: i for i, (t, _) in enumerate(RULES)}
    ranked = sorted(((v, -order[k], k) for k, v in scores.items() if v > 0), reverse=True)

    # 2. Telemetry-only reasoning is its own path and must not be dressed up as a
    #    text match. A silent grounding has no report to quote and real unknowns to
    #    declare; letting a nav-status boost score as a "matched term" produced a
    #    confident classification with an empty unknowns list.
    if not text_matched and telemetry:
        # No text signal. Fall back to what the MMSI itself declares. A dedicated
        # distress transmitter says something is very wrong; only 972 says what.
        if telemetry.mmsi.startswith("972"):
            return TriageResult(
                type=T.MAN_OVERBOARD, severity=S.CRITICAL, confidence=0.85,
                unknowns=["Position of the person relative to the vessel",
                          "Time in the water", "Sea temperature"],
                rationale="MMSI prefix 972 is a dedicated man-overboard beacon.")
        if telemetry.mmsi.startswith(("970", "974")):
            kind = "AIS-SART" if telemetry.mmsi.startswith("970") else "AIS-EPIRB"
            return TriageResult(
                type=T.UNKNOWN, severity=S.CRITICAL, confidence=0.5,
                unknowns=["Nature of the incident", "Persons on board",
                          "Whether the vessel is still afloat"],
                rationale=f"{kind} activation with no voice contact. The beacon "
                          f"confirms distress but does not name the incident.")
        if telemetry.nav_status == 6:
            return TriageResult(
                type=T.GROUNDING, severity=S.HIGH, confidence=0.7,
                unknowns=["Hull integrity", "Persons on board", "Pollution risk"],
                rationale="Navigational status 6 (aground) with no voice report.")

    if not ranked:
        return TriageResult(type=T.UNKNOWN, severity=S.HIGH, confidence=0.2,
                            unknowns=["Nature of the incident"],
                            rationale="No classifying signal in the report or telemetry.")

    score, _, best = ranked[0]
    severity = BASE_SEVERITY[best]
    if any(e in low for e in ESCALATORS):
        severity = S.CRITICAL
    elif any(d in low for d in DEESCALATORS):
        # One band, not two. Dropping two turned "no injuries" in an active flooding
        # report into a Low, and under-triage is the failure mode that kills people.
        # The eval caught it, which is the point of the eval.
        severity = S(max(1, severity - 1))

    matched = [k for k, terms in RULES if k == best for k in terms if k in low]
    return TriageResult(
        type=best, severity=severity,
        confidence=min(0.95, 0.45 + 0.15 * score),
        unknowns=[],
        
    )
