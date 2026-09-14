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


# What shore still does not know once the words have been read. A classification
# that declares nothing unconfirmed is claiming the report was complete, and no
# first report ever is. Each question carries the terms that would have answered it,
# so a master who already said "all crew accounted for" is not asked again.
GENERAL_UNKNOWNS: list[tuple[str, tuple[str, ...]]] = [
    ("Whether all persons on board are accounted for",
     ("accounted for", "all crew", "all hands", "muster")),
    ("Whether the vessel retains propulsion and steering",
     ("propulsion", "main engine", "under way", "steering", "not under command")),
    ("Whether assistance has already been accepted from another vessel",
     ("assist", "tug", "standing by", "escort", "salvage")),
]

TYPE_UNKNOWNS: dict[T, tuple[str, tuple[str, ...]]] = {
    T.FIRE: ("Whether the fire is contained",
             ("contained", "extinguish", "boundary cooling", "co2", "sealed")),
    T.FLOODING: ("Rate of ingress and current angle of list",
                 ("list", "degrees", "pumps", "ingress")),
    T.PIRACY: ("Whether the boarders are armed and whether they are aboard",
               ("armed", "boarded", "citadel", "weapons")),
    T.ATTACK: ("Whether further attack is expected",
               ("further", "second", "ceased", "cleared the area")),
    T.COLLISION: ("Condition of the other vessel and persons in the water",
                  ("other vessel", "going down", "recovering", "rescue boat")),
    T.GROUNDING: ("Hull integrity and pollution risk",
                  ("hull", "pollution", "breach", "soundings", "tanks")),
    T.MACHINERY_FAILURE: ("Whether the vessel is setting toward a hazard",
                          ("drift", "setting toward", "anchor", "traffic separation")),
    T.MEDICAL_EVACUATION: ("Whether telemedical advice has been obtained",
                           ("doctor", "telemedical", "medico", "medical advice")),
    T.MAN_OVERBOARD: ("Time in the water and sea temperature",
                      ("water temperature", "sea temperature", "minutes")),
    T.CREW_ABANDONMENT: ("Number and position of survival craft",
                         ("liferaft", "life raft", "free-fall boat", "rafts")),
}


def _unknowns(best: T, low: str) -> list[str]:
    candidates = [TYPE_UNKNOWNS[best]] if best in TYPE_UNKNOWNS else []
    return [question for question, answered in candidates + GENERAL_UNKNOWNS
            if not any(a in low for a in answered)]


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

    # A hostile act outranks any count of effect terms, not just ties: a drone strike
    # report says "fire" and "burns" more often than "drone", and scoring it a Fire
    # sends an unarmed SAR hull into a weapons area.
    order = {t: i for i, (t, _) in enumerate(RULES)}
    ranked = sorted(((k in (T.ATTACK, T.PIRACY), v, -order[k], k)
                     for k, v in scores.items() if v > 0), reverse=True)

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

    _, score, _, best = ranked[0]
    severity = BASE_SEVERITY[best]
    if any(e in low for e in ESCALATORS):
        severity = S.CRITICAL
    elif any(d in low for d in DEESCALATORS):
        # One band, not two. Dropping two turned "no injuries" in an active flooding
        # report into a Low, and under-triage is the failure mode that kills people.
        # The eval caught it, which is the point of the eval.
        severity = S(max(1, severity - 1))

    matched = sorted({term for kind, terms in RULES if kind is best
                      for term in terms if _mentions(low, term)})
    return TriageResult(
        type=best, severity=severity,
        confidence=min(0.95, 0.45 + 0.15 * score),
        unknowns=_unknowns(best, low),
        rationale=f"Report matched " + ", ".join(repr(m) for m in matched[:4])
                  + f" against the {best.value} terms"
                  + (f"; telemetry reports navigational status "
                     f"{telemetry.nav_status} at {telemetry.speed_kn:.1f} kn."
                     if telemetry else "."),
    )
