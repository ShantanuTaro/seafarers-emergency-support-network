"""Triage agent, built on LangGraph.

    detect ──► classify (llm | baseline) ──► guard ──► END

`detect` reads the telemetry for hard distress signals before any model sees the
case. `guard` runs after classification and can only ever raise severity, never
lower it. That asymmetry is deliberate: over-triage wastes an aircraft,
under-triage loses a crew.

The model is given a typed payload and its output is parsed back through the
pydantic contract. A response that does not validate is discarded and the
deterministic baseline answers instead. A malformed model reply must never
become a blank incident in front of an operator.
"""

from __future__ import annotations

import json
import time
from operator import add
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import baseline, providers
from .models import IncidentType, Severity, Telemetry, TriageResult

SYSTEM_PROMPT = """You are a maritime incident triage analyst supporting a shore \
operations centre. You classify a single reported incident and nothing else.

Return a JSON object with exactly these keys:
  type        one of: {types}
  severity    integer 1 (Low) 2 (Moderate) 3 (High) 4 (Critical)
  confidence  float 0.0-1.0
  unknowns    array of short strings: facts the operator still must establish
  rationale   one sentence, under 200 characters

Rules:
- If the report names a cause and an effect, classify the CAUSE. A drone strike that
  starts a fire is an Attack. A grounding that floods the engine room is a Grounding.
  The cause determines which authority is responsible for responding.
- If the evidence does not identify an incident type, answer "Unknown". Do not guess.
  A distress beacon with no voice contact confirms distress but names no incident.
- `unknowns` must not be empty unless you are certain of the full picture.
- Never lower severity because a report sounds calm. Crews under-report."""


class State(TypedDict, total=False):
    text: str
    telemetry: dict[str, Any] | None
    signals: list[str]
    result: TriageResult | None
    # Reducer, not replacement: every node appends its own hop, so the finished
    # state carries the whole path. Structured tracing is a requirement, not a log line.
    trace: Annotated[list[dict[str, Any]], add]


def _telemetry(state: State) -> Telemetry | None:
    t = state.get("telemetry")
    return Telemetry(**t) if t else None


def detect(state: State) -> State:
    """Hard signals straight from the feed, before any model opinion. These are
    facts, not inferences, and `guard` later enforces them over the classifier."""
    t = _telemetry(state)
    signals: list[str] = []
    if t:
        if t.mmsi.startswith("970"):
            signals.append("AIS-SART activation (MMSI prefix 970)")
        if t.mmsi.startswith("972"):
            signals.append("Man-overboard beacon (MMSI prefix 972)")
        if t.mmsi.startswith("974"):
            signals.append("AIS-EPIRB activation (MMSI prefix 974)")
        if t.nav_status == 6:
            signals.append("Navigational status 6: aground")
        if t.nav_status == 2:
            signals.append("Navigational status 2: not under command")
        if t.speed_kn < 0.5:
            signals.append("Speed over ground below 0.5 kn: vessel stopped")
    return {"signals": signals, "trace": [{"node": "detect", "signals": signals}]}


def _route(state: State) -> str:
    return "classify_llm" if providers.any_available() else "classify_baseline"


def classify_llm(state: State) -> State:
    payload = {
        "report_text": state.get("text") or "(no voice or written report received)",
        "telemetry": state.get("telemetry"),
        "detected_signals": state.get("signals", []),
    }
    system = SYSTEM_PROMPT.format(types=", ".join(t.value for t in IncidentType))
    try:
        raw, provider, latency = providers.complete_json(
            system, json.dumps(payload, indent=2)
        )
        result = TriageResult(
            type=IncidentType(raw["type"]),
            severity=Severity(int(raw["severity"])),
            confidence=float(raw.get("confidence", 0.5)),
            unknowns=[str(u) for u in raw.get("unknowns", [])],
            rationale=str(raw.get("rationale", ""))[:300],
            provider=provider,
            latency_ms=latency,
        )
        return {"result": result,
                "trace": [{"node": "classify_llm", "provider": provider,
                           "latency_ms": latency, "ok": True}]}
    except (providers.AllProvidersDown, KeyError, ValueError, TypeError) as exc:
        # Fall through to the baseline. A model that answers badly is the same as a
        # model that does not answer.
        return {"result": None,
                "trace": [{"node": "classify_llm", "ok": False,
                           "error": f"{type(exc).__name__}: {exc}"}]}


def classify_baseline(state: State) -> State:
    started = time.monotonic()
    result = baseline.classify(state.get("text") or "", _telemetry(state))
    result.latency_ms = int((time.monotonic() - started) * 1000)
    return {"result": result,
            "trace": [{"node": "classify_baseline", "provider": "baseline", "ok": True}]}


def _after_llm(state: State) -> str:
    return "guard" if state.get("result") else "classify_baseline"


def guard(state: State) -> State:
    """Post-classification safety floor. Can raise severity and add unknowns.
    Never lowers either. Every override is recorded in the trace, because these
    logs are written on the assumption they become evidence."""
    result = state["result"]
    assert result is not None, "guard reached with no classification"
    t = _telemetry(state)
    overrides: list[str] = []

    if t:
        floor = Severity.LOW
        if t.mmsi.startswith(("970", "972", "974")):
            floor = Severity.CRITICAL
        elif t.nav_status == 6:
            floor = Severity.HIGH
        if result.severity < floor:
            overrides.append(
                f"severity raised {result.severity.name} -> {floor.name} "
                f"by telemetry floor")
            result.severity = floor

    if not (state.get("text") or "").strip() and not result.unknowns:
        result.unknowns = ["No voice or written report received from the vessel",
                           "Persons on board and their condition",
                           "Whether assistance is already on scene"]
        overrides.append("added unknowns: classification rests on telemetry alone")

    if result.confidence <= 0.6 and not result.unknowns:
        result.unknowns = ["Nature of the incident is not established from the "
                           "available evidence"]
        overrides.append("added unknowns: low confidence with none declared")

    return {"result": result,
            "trace": [{"node": "guard", "overrides": overrides}]}


def _build():
    g = StateGraph(State)
    g.add_node("detect", detect)
    g.add_node("classify_llm", classify_llm)
    g.add_node("classify_baseline", classify_baseline)
    g.add_node("guard", guard)
    g.add_edge(START, "detect")
    g.add_conditional_edges("detect", _route,
                            {"classify_llm": "classify_llm",
                             "classify_baseline": "classify_baseline"})
    g.add_conditional_edges("classify_llm", _after_llm,
                            {"guard": "guard", "classify_baseline": "classify_baseline"})
    g.add_edge("classify_baseline", "guard")
    g.add_edge("guard", END)
    return g.compile()


GRAPH = _build()


def run(text: str, telemetry: Telemetry | None) -> tuple[TriageResult, list[dict]]:
    out = GRAPH.invoke({
        "text": text,
        "telemetry": telemetry.model_dump(by_alias=True) if telemetry else None,
        "trace": [],
    })
    return out["result"], out.get("trace", [])
