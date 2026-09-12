"""Deterministic eval over a fixed corpus of incident scenarios.

    python -m evals.run                # baseline classifier
    python -m evals.run --agent        # the LangGraph triage agent
    python -m evals.run --gate         # exit 1 on regression, for CI
    python -m evals.run --out x.md     # write the markdown table

The gate thresholds are what the *product* must clear. The baseline is not expected
to clear them; that gap is the argument for the agent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sesn import baseline, triage
from sesn.models import IncidentType, Severity, Telemetry, TriageResult

CORPUS = Path(__file__).resolve().parent / "corpus.json"

# Two different numbers, doing two different jobs.
#
# The GATE is a ratchet, pinned to what the classifier measurably does today. CI
# fails if a change makes triage worse. It is not an aspiration and it must be
# raised whenever the numbers improve, or it stops meaning anything.
#
# The TARGET is where triage has to get before this system would be defensible in
# front of a marine board. The baseline does not meet it and is not expected to.
# The run prints the shortfall on every invocation so the gap cannot quietly
# become the new normal.
GATE_TYPE_ACCURACY = 0.90
GATE_UNDER_TRIAGE = 0.10

TARGET_TYPE_ACCURACY = 0.95
TARGET_UNDER_TRIAGE = 0.05

SEVERITY_BY_NAME = {"Low": 1, "Moderate": 2, "High": 3, "Critical": 4}


def load() -> list[dict]:
    scenarios = json.loads(CORPUS.read_text())
    ids = [s["id"] for s in scenarios]
    assert len(set(ids)) == len(ids), "duplicate scenario id in corpus"
    covered = {s["expected"]["type"] for s in scenarios}
    missing = {t.value for t in IncidentType} - covered
    assert not missing, f"no scenario covers {sorted(missing)}"
    return scenarios


def run(scenarios: list[dict], use_agent: bool) -> list[dict]:
    rows = []
    for s in scenarios:
        tel = Telemetry(**s["telemetry"]) if s.get("telemetry") else None
        if use_agent:
            result, _ = triage.run(s["text"], tel)
        else:
            result = baseline.classify(s["text"], tel)
        rows.append({
            "id": s["id"],
            "expected_type": s["expected"]["type"],
            "expected_sev": SEVERITY_BY_NAME[s["expected"]["severity"]],
            "got_type": result.type.value,
            "got_sev": int(result.severity),
            "result": result,
        })
    return rows


def report(rows: list[dict], name: str) -> tuple[str, float, float]:
    n = len(rows)
    type_ok = sum(r["expected_type"] == r["got_type"] for r in rows)
    sev_exact = sum(r["expected_sev"] == r["got_sev"] for r in rows)
    sev_near = sum(abs(r["expected_sev"] - r["got_sev"]) <= 1 for r in rows)
    # The metric that matters in a marine board inquiry. Calling a critical incident
    # routine is not symmetric with calling a routine incident critical: one wastes
    # an aircraft, the other loses a crew.
    under = sum(r["got_sev"] < r["expected_sev"] for r in rows)

    out = [f"### Eval: {name}", "", f"`{n}` scenarios.", "",
           "| Metric | Score |", "| --- | --- |",
           f"| Incident type accuracy | {type_ok / n:.1%} |",
           f"| Severity exact | {sev_exact / n:.1%} |",
           f"| Severity within one band | {sev_near / n:.1%} |",
           f"| **Under-triage rate** (predicted less severe than truth) | **{under / n:.1%}** |",
           "", "| Incident type | n | Recall | Precision |", "| --- | --- | --- | --- |"]

    for t in IncidentType:
        actual = [r for r in rows if r["expected_type"] == t.value]
        predicted = [r for r in rows if r["got_type"] == t.value]
        if not actual and not predicted:
            continue
        hits = sum(r["expected_type"] == r["got_type"] for r in actual)
        recall = f"{hits / len(actual):.0%}" if actual else "n/a"
        precision = f"{hits / len(predicted):.0%}" if predicted else "n/a"
        out.append(f"| {t.value} | {len(actual)} | {recall} | {precision} |")

    misses = [r for r in rows
              if r["expected_type"] != r["got_type"] or r["got_sev"] < r["expected_sev"]]
    if misses:
        out += ["", "<details><summary>Misses</summary>", "",
                "| Scenario | Expected | Predicted |", "| --- | --- | --- |"]
        names = {v: k for k, v in SEVERITY_BY_NAME.items()}
        for m in misses:
            out.append(f"| `{m['id']}` | {m['expected_type']} / {names[m['expected_sev']]} "
                       f"| {m['got_type']} / {names[m['got_sev']]} |")
        out += ["", "</details>"]

    return "\n".join(out) + "\n", type_ok / n, under / n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", action="store_true", help="use the LangGraph triage agent")
    ap.add_argument("--gate", action="store_true", help="exit 1 if below thresholds")
    ap.add_argument("--out", help="also write the markdown table here")
    args = ap.parse_args()

    scenarios = load()
    rows = run(scenarios, args.agent)
    name = "LangGraph triage agent" if args.agent else "keyword + AIS baseline"
    md, accuracy, under = report(rows, name)

    print(md)
    if args.out:
        Path(args.out).write_text(md)

    if not args.gate:
        return 0

    shortfall = []
    if accuracy < TARGET_TYPE_ACCURACY:
        shortfall.append(f"type accuracy {accuracy:.1%} is below the "
                         f"{TARGET_TYPE_ACCURACY:.0%} target")
    if under > TARGET_UNDER_TRIAGE:
        shortfall.append(f"under-triage {under:.1%} is above the "
                         f"{TARGET_UNDER_TRIAGE:.0%} target")
    for s_ in shortfall:
        print(f"SHORTFALL: {s_}", file=sys.stderr)

    failures = []
    if accuracy < GATE_TYPE_ACCURACY:
        failures.append(f"type accuracy {accuracy:.1%} regressed below the "
                        f"{GATE_TYPE_ACCURACY:.1%} ratchet")
    if under > GATE_UNDER_TRIAGE:
        failures.append(f"under-triage {under:.1%} regressed above the "
                        f"{GATE_UNDER_TRIAGE:.1%} ratchet")
    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    if not failures and (accuracy > GATE_TYPE_ACCURACY or under < GATE_UNDER_TRIAGE):
        print(f"RATCHET: triage improved to {accuracy:.1%} / {under:.1%}. Raise the "
              f"gate in evals/run.py so the gain is locked in.", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
