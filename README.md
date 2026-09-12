# Seafarers Emergency Support Network

**Decision support for maritime distress incidents.** When a vessel is in trouble,
SESN classifies what happened, names the rescue authority legally responsible for
that water, finds the nearest hull that can actually reach them, and drafts a
different message for every party who needs one. Then it stops, and waits for a
named human to approve each one.

> ### Supplementary to GMDSS. Never a replacement.
> Distress alerting must be made via GMDSS: DSC, EPIRB, or Inmarsat. This system
> does not transmit distress alerts and is not connected to any real distress
> network. It is decision support only.

Inspired by the Seafarers Emergency Support Network proposed by India at the 2026
BRICS Summit.

---

## The problem this is shaped around

A ship declares distress. What follows is a coordination problem, not a detection
problem, and it is where the time goes:

- **The authority question.** Whose SAR region is this, and which rescue coordination
  centre is legally on the hook? On the high seas this is frequently not obvious.
- **The recipient question.** An MRCC, a merchant ship 12 nm away, a naval asset, the
  company DPA and the next of kin all need to be told, and they need to be told
  *different things*. One broadcast to all five is worse than sending nothing.
- **The silence problem.** Once a crew has sent a distress alert, they usually cannot
  see whether anyone ashore picked it up, what was concluded, or who is coming. They
  sit in the worst hour of their career with no feedback channel.

SESN is built around those three, and around one hard rule: **nothing sends itself.**

---

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn sesn.main:app
```

Open <http://127.0.0.1:8000>. No API key required. With no LLM key configured, triage
falls back to the deterministic baseline classifier, so the whole system runs offline.
To enable the agent path, set any of `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`.

```bash
.venv/bin/python test_sesn.py            # invariant checks
.venv/bin/python -m evals.run            # triage eval table
.venv/bin/python -m evals.run --gate     # regression ratchet, exits 1 if triage got worse
```

---

## Three portals

They are separate because the jobs are separate. One screen serving all three is how
real operations consoles end up unusable.

| Route | Who | What it does |
| --- | --- | --- |
| **`/vessel`** | masters and crew | Declare distress in one action. See what shore actually did. |
| **`/ops`** | shore watch | World traffic picture, incident queue, triage detail, approval gate. |
| **`/control`** | engineers | Inject faults into any of 60,000 hulls, pause the simulator. |

### `/vessel`, the bridge terminal

Deliberately larger type and lower density than the operations console, because it
gets read by someone having the worst day of their career.

One action declares distress with position, course, speed and persons aboard attached
automatically. Then it answers the question current systems answer worst: **what is
shore actually doing?** Received, classified, drafted, approved and released, with the
name of the operator who released it. It also surfaces the triage agent's declared
unknowns to the crew as "what shore still needs to know", because they are the only
people who can answer them.

### `/ops`, the operations console

Dense, dark, map dominant. Incident queue with severity, confidence and pending
approval counts. Full triage detail: classification, the basis for it, declared
unknowns, which classifier ran and how long it took. Manual intake for reports
arriving by radio, sat phone or email. Append only audit log.

### `/control`, the fault injector

Amber accented so it is never mistaken for the operations console. Every incident in
this system is fabricated on purpose, and this is where that happens.

---

## Architecture

```
                    ┌────────────────────────────────────────────┐
   /control ───────►│  simulator                                 │
   fault injection  │  ~60,000 hulls, 34 sea lanes, 1 s tick     │
   /vessel  ───────►│  faults mutate telemetry, not labels       │
   distress declared└──────────────────┬─────────────────────────┘
                                       │ telemetry
                                       ▼
                    ┌────────────────────────────────────────────┐
                    │  detect                                    │
                    │  MMSI 970/972/974, nav status, speed-zero,  │
                    │  AIS blackout                               │
                    └──────────────────┬─────────────────────────┘
                                       ▼
                    ┌────────────────────────────────────────────┐
                    │  triage (LangGraph)                        │
                    │  detect → classify → guard                 │
                    │  Gemini → Mistral → Groq → baseline        │
                    └──────────────────┬─────────────────────────┘
                                       ▼
                    ┌────────────────────────────────────────────┐
                    │  responders                                │
                    │  haversine + SAR region → MRCC             │
                    └──────────────────┬─────────────────────────┘
                                       ▼
                    ┌────────────────────────────────────────────┐
                    │  packets                                   │
                    │  MRCC · merchant · naval · DPA · next of kin│
                    └──────────────────┬─────────────────────────┘
                                       ▼
                    ╔════════════════════════════════════════════╗
                    ║  OPERATOR APPROVAL GATE                    ║
                    ║  named approver, nothing sends itself      ║
                    ╚══════════════════╤═════════════════════════╝
                                       ▼
                            append-only audit log
```

### The triage graph

`detect` reads hard distress signals out of telemetry before any model sees the case.
`guard` runs after classification and **can only raise severity, never lower it.**
Over-triage wastes an aircraft. Under-triage loses a crew. Those are not symmetric and
the code does not treat them as though they are.

A model reply that fails pydantic validation is discarded and the baseline answers
instead, so a malformed response can never surface as a blank incident in front of an
operator. There is no state in which triage returns nothing.

`Unknown` is a first class answer. An AIS-EPIRB with no voice contact confirms distress
and names no incident type. Guessing there would be worse than abstaining and saying
what is missing.

### Design decisions worth knowing

- **Faults move telemetry, not labels.** A grounding sets nav status 6 and stops the
  ship, with no voice report at all. The detector has to earn its classification from
  the feed exactly as it would against real AIS. `test_sesn.py` asserts this for every
  fault in the catalogue.
- **Ships are a slots dataclass, not pydantic.** At 60,000 instances that is the
  difference between a simulator and a memory problem. Pydantic stays at the API
  boundary where validation actually buys something.
- **The websocket sends compact arrays, culled to your viewport.** Names, flags and
  persons aboard are fetched per vessel on click. Sending them for every hull on
  screen would be most of the payload and none of the picture.
- **Distressed contacts are never culled by the render cap.** An operator must not
  lose a casualty to a rendering budget. There is a test for it.
- **SAR region coverage is exhaustive.** Every position on earth resolves to a named
  authority, because "we could not work out whose water this is" is not an answer a
  rescue coordination system is allowed to give. There is a test for that too.

---

## Eval results

The eval suite is the most important artifact in this repo. Thirty graded scenarios
covering all ten incident types plus `Unknown`, scored per type, gating CI.

### Keyword + AIS baseline: the floor the agent must beat

| Metric | Score | Target |
| --- | --- | --- |
| Incident type accuracy | 90.0% | 95% |
| Severity exact | 63.3% | |
| Severity within one band | 96.7% | |
| **Under-triage rate** | **10.0%** | **5%** |

| Incident type | n | Recall | Precision |
| --- | --- | --- | --- |
| Unknown | 4 | 100% | 67% |
| Piracy | 3 | 67% | 100% |
| Attack | 3 | 67% | 100% |
| Fire | 3 | 100% | 75% |
| Flooding | 2 | 100% | 100% |
| Collision | 2 | 100% | 100% |
| Grounding | 3 | 100% | 100% |
| MachineryFailure | 3 | 100% | 100% |
| MedicalEvacuation | 3 | 100% | 100% |
| ManOverboard | 3 | 67% | 100% |
| CrewAbandonment | 1 | 100% | 100% |

**The agent column is empty on purpose.** It gets filled when an API key is configured
and the LangGraph path has been measured against the same corpus. Publishing a number
for it before then would be the exact thing this suite exists to prevent.

CI enforces a **ratchet** pinned to the numbers above, not the target. A change that
makes triage worse fails the build; the shortfall against the target is printed on
every run so it cannot quietly become the new normal.

### What the suite has already caught

Three real defects, all of which would have shipped silently:

1. A de-escalation rule reading "no injuries" in an active flooding report and
   dropping it two severity bands.
2. A keyword matcher scoring "**no** ingress" as evidence *of* flooding, which was
   costing every collision in the corpus. Collision recall went 0% to 100%.
3. A silent grounding classified confidently with an empty unknowns list, because a
   telemetry-derived score was masquerading as a text match.

---

## Honest limitations

- **All traffic is simulated.** There is no AIS feed. ~60,000 synthetic hulls move on
  34 real sea lanes with port anchorages and fishing grounds. The count matches the
  real world merchant fleet; nothing on the map is a real ship.
- **All incidents are fabricated.** Every one is injected from the control panel or
  declared from the bridge terminal. Nothing observes a real emergency.
- **Not connected to any real distress system.** No GMDSS, no Cospas-Sarsat.
- **Operator and vessel names are invented.** `Marslev Line`, `Zamir Line` and the rest
  are fictional. No real carrier, vessel or MMSI appears anywhere in this repo.
- **MRCC designators are fictional**, for example `MRCC SIM-ADEN`. No real rescue
  coordination centre's details appear anywhere.
- **Eval labels are not professionally validated.** The thirty scenarios and their
  expected classifications were written without review by a serving mariner or DPA.
  An eval is worth exactly what its labels are worth, and these need expert review.
- **The corpus may be too easy.** A pure keyword matcher scores 90% on it, which is
  suspicious. Real intake is messier, more fragmentary, and often not in English.
- **Packets are template grounded, not procedure grounded.** Retrieval over real SAR
  procedure summaries is M2 and is what would make the drafts defensible.

---

## Layout

| Path | What |
| --- | --- |
| `sesn/models.py` | Typed contracts. Every boundary speaks these. |
| `sesn/sim.py` | Vessel simulator, fault catalogue, deterministic under a seed |
| `sesn/baseline.py` | Deterministic classifier: the floor, and the offline fallback |
| `sesn/providers.py` | LLM provider chain with circuit breaker |
| `sesn/triage.py` | LangGraph triage agent |
| `sesn/response.py` | Nearest responders, SAR regions, per-recipient packets |
| `sesn/main.py` | FastAPI, websocket, approval gate, audit log |
| `web/` | Three portals, no build step, no framework |
| `evals/` | Graded corpus and scoring harness |
| `test_sesn.py` | Invariant checks |

## Stack

Python 3.12, FastAPI, LangGraph, pydantic, MapLibre GL with OpenFreeMap tiles.
No build step, no database, no paid services.

## License

BSL 1.1. Source visible, non-commercial use permitted, commercial use requires
permission, converts to Apache 2.0 after four years. Not OSI open source, deliberately.
