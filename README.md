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

**Requires Python 3.12 or newer.** No database, no API key, no build step, no Docker.

```bash
git clone https://github.com/ShantanuTaro/seafarers-emergency-support-network.git
cd seafarers-emergency-support-network

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/uvicorn sesn.main:app
```

Then open **<http://127.0.0.1:8000>** and pick a portal.

The first request takes a second or two while the simulator seeds 60,000 vessels.
Stop the server with `Ctrl+C`.

| Flag | Why |
| --- | --- |
| `--port 8077` | Run on a different port if 8000 is taken |
| `--reload` | Restart on file changes while developing |
| `--host 0.0.0.0` | Reachable from other machines on your network |

### Where to start

1. Open **`/control`**, search for a vessel (try `marslev`), pick one, and inject a
   **Grounding**. It is the interesting case: nav status goes to 6, the ship stops,
   and no voice report is generated at all, so triage has to work it out from
   telemetry alone.
2. Switch to **`/ops`**. The incident is in the queue with its classification, the
   basis for it, and five drafted packets all sitting unapproved. Put a name in the
   operator field and approve the MRCC packet.
3. Open **`/vessel`**, sign in to that same ship, and see the approval appear from the
   crew's side.

### Optional: enable the LLM triage path

With no key configured, triage falls back to the deterministic baseline classifier and
the whole system runs offline. To use the agent path, put one key in `.env` at the
repo root:

```bash
cp .env.example .env      # then fill in whichever key you have
```

```ini
GEMINI_API_KEY=
MISTRAL_API_KEY=
GROQ_API_KEY=
```

One key is enough. `.env` is gitignored and read at import time; an exported variable
still wins over the file, so `GROQ_API_KEY=... .venv/bin/uvicorn sesn.main:app` works
for a one-off. Free tiers, no card required: [Gemini](https://aistudio.google.com/apikey),
[Mistral](https://console.mistral.ai/api-keys), [Groq](https://console.groq.com/keys).

The chain tries them in that order, skips any provider without a key rather than
waiting on it, trips a circuit breaker on rate limits, and falls back to the baseline
if every provider is down. `/control` shows the live state and the exact model each
provider is being asked for.

The models live in `CHAIN` in [`sesn/providers.py`](sesn/providers.py):
`gemini-2.0-flash`, `ministral-8b-latest`, `llama-3.3-70b-versatile`. Override any of
them from `.env` with `GEMINI_MODEL`, `MISTRAL_MODEL` or `GROQ_MODEL`. Mistral's
default is `ministral-8b-latest` rather than `mistral-small-latest` because a new
free-tier key authenticates but returns 429 on the latter, which trips the breaker on
the first incident and quietly drops triage to the baseline. Every incident's audit
entry records which provider and model actually answered.

### Tests and evals

```bash
.venv/bin/python test_sesn.py            # 11 invariant checks
.venv/bin/python -m evals.run            # triage eval table
.venv/bin/python -m evals.run --agent    # same corpus, LangGraph path (needs a key)
.venv/bin/python -m evals.run --gate     # regression ratchet, exits 1 if triage got worse
.venv/bin/python check_web.py            # portal JS syntax (needs node, skips without)
```

All of the above run in CI on every push.

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
people who can answer them. A message thread runs both ways between the bridge and
the watchkeeper, so the unknowns can be closed by the people who hold the answers.

### `/ops`, the operations console

Dense, dark, map dominant. The incident queue is always on screen, and opening one
incident adds its detail below the list rather than replacing it: a console that
swaps the queue for a detail view hides every casualty that arrives while an operator
is reading one. Full triage detail: classification, the basis for it, declared
unknowns, which classifier ran and how long it took. Manual intake for reports
arriving by radio, sat phone or email. Append only audit log.

Clicking any contact on the map opens the vessel inspector: what the hull is, what it
is carrying, persons aboard, live telemetry, and a direct line to its bridge
terminal. Those messages are not generated by the system and are not one of the gated
packets. A named operator writes each one and the audit log records it.

Casualties are drawn from the frame's own distress list rather than the culled
viewport rows, and they paint last. A ship in distress is red on the map wherever the
operator has panned to, and is never underneath the traffic around it.

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
