# Seafarers Emergency Support Network

## What this is

A coordination and decision-support layer for maritime distress incidents. Sits
*beside* GMDSS, never replaces it. When a vessel triggers or appears to be in
distress, the system classifies the incident, identifies the legally responsible
authority and the nearest capable responders, and drafts a tailored action packet
for each, for a human operator to approve before anything is sent.

Inspired by the Seafarers Emergency Support Network proposed by India at the 2026
BRICS Summit (Sept 12, 2026).

## Hard constraints: do not violate these

1. **Nothing auto-dispatches.** Every outbound message passes an operator approval
   gate. This is a liability requirement, not a UX preference.
2. **Supplementary to GMDSS, never a replacement.** This must appear in the README,
   the UI, and any generated message footer.
3. **Zero paid services.** Free tiers only. If a design needs a paid API, redesign it.
4. **No real distress integration.** No GMDSS, no Cospas-Sarsat. All vessel traffic
   is simulated; all incidents are operator-injected. Nothing in this system observes
   or touches a real emergency.
5. **No real contact details for actual MRCCs or vessels** in seed data or demos.
   Vessel names, MMSIs and callsigns are synthetic.
6. **The simulator is visibly a simulator.** The portal must never let an operator
   mistake simulated traffic for live traffic. Persistent banner, no exceptions.

## Stack

- **Backend**: Python 3.12+, FastAPI, single process
- **Agents**: LangGraph
- **LLMs**: multi-provider fallback chain: Gemini → Mistral → Llama via Groq, all
  free tiers, with circuit breaker on rate limits. Must degrade to the deterministic
  baseline classifier when no key is configured, so the demo runs offline.
- **Traffic**: in-process vessel simulator on a fixed tick, ~60,000 synthetic hulls
  (world merchant fleet scale) across 34 real sea lanes, 45 port anchorages and 15
  fishing grounds. Ships are a slots dataclass, not pydantic. At this count that is
  the difference between a simulator and a memory problem.
- **Realtime push**: FastAPI WebSocket. The client pushes its viewport, the server
  culls the frame to it and sends compact arrays `[mmsi, lat, lon, course, kind, flags]`.
  Names, flags and POB are fetched per vessel on click. Sending them for every hull
  on screen is most of the payload and none of the picture. Distressed contacts are
  never culled by the rendering cap.
- **Map**: MapLibre GL + OpenFreeMap tiles (no API key, no quota), full world scale
- **Frontend**: one static page, no build step, no framework
- **CI**: GitHub Actions

### Deferred until a milestone actually needs them

Introducing any of these before something breaks without them is over-building.

- **Postgres + PostGIS**: the simulator holds a few hundred vessels in memory;
  nearest-responder is a haversine sort. Add PostGIS when the vessel count or
  persistence requirement makes that false.
- **Qdrant**: needed for procedure retrieval (M2), not before.
- **aisstream.io**: real terrestrial AIS as an optional background layer behind the
  simulated fleet. The architecture keeps a single feed interface so this is a swap,
  not a rewrite. Requires a persistent host to hold the websocket open.

## Architecture

Simulate → Detect and enrich → Triage agent → Procedure retrieval → Operator approval → Dispatch

### Simulate
- Synthetic fleet on a tick loop: position by great-circle dead reckoning along a
  waypoint route, looping. Each vessel carries type, flag, POB, cargo, capability.
- **Fault injection from the ops panel.** The operator picks a vessel and an
  emergency, and the simulator mutates that vessel's state accordingly. This is the
  only way an incident is ever created.
- Injected faults must move the *telemetry*, not just set a label: a grounding sets
  nav status 6 and speed to zero, an engine failure drops speed and sets not-under-
  command, an AIS blackout stops position reports. The detector then has to earn its
  classification from the telemetry, exactly as it would on a real feed.
- Manual intake stays: portal form for free-text reports.

### Detect and enrich
Distress signals present in AIS, reproduced by the simulator:
- MMSI prefix `970` = AIS-SART (search and rescue transmitter)
- MMSI prefix `972` = man overboard beacon
- MMSI prefix `974` = AIS-EPIRB
- Nav status `6` = aground

Derived anomalies: speed-to-zero, course deviation from expected route, AIS blackout,
entry into a high-risk geofence.

Enrichment joins: crew manifest, cargo, flag state, P&I club, last port.

### Triage agent
LangGraph. Input: free text (radio transcript, sat-phone note, email) + structured
telemetry. Output: incident type, severity, confidence, and explicit list of unknowns.

Incident types: piracy/armed robbery, drone or missile attack, fire, flooding,
collision, grounding, machinery failure, medical evacuation, man overboard,
crew abandonment.

`Unknown` is a first-class answer. A bare SART hit with no voice contact does not
name an incident type, and a triage that guesses there is worse than one that abstains.

### Procedure retrieval
Qdrant over SAR procedure summaries, maritime security best practice, flag-state
circulars, and per-customer emergency response manuals.

**Key requirement**: generates a *different* draft per recipient class.
- MRCC → position, POB count, incident classification, SAR region
- Nearby merchant vessel → SOLAS duty-to-assist request, ETA, hazards
- Naval/coast guard asset → threat detail, rules-of-engagement relevant context
- Ship manager / DPA → full picture
- Next of kin → drafted for a human to review and send, never auto-sent

Use public summaries only. Do not reproduce copyrighted IMO publications
(IAMSAR, BMP5) into the vector store.

### Nearest responder
Haversine distance over live simulated positions, filtered by vessel capability and
computed ETA. Overlay the IMO SAR region → MRCC mapping so output names the legally
responsible authority alongside the closest hull.

### Dispatch
Approval gate → append-only audit log → channels. Nothing leaves the system; in
simulation, "dispatch" writes to the audit log and marks the packet sent. Every
decision logged with inputs, model outputs, and approver identity. Assume logs become
evidence in a marine board inquiry.

## Portals

Three front ends over one world. They are separate because the jobs are separate.
one screen serving all three is how real ops consoles end up unusable.

### `/vessel`: seafarer portal (bridge terminal)
For a master or crew member aboard one hull. Deliberately larger type and lower
density than the ops console: it gets read by someone having the worst day of their
career.

- One-action distress declaration; position, course, speed and POB attach automatically
- **Shore status in plain language**. This is the gap in current systems. A crew
  declares distress and then has no idea whether anyone ashore has picked it up, what
  was concluded, or who is coming. The portal answers exactly that: received →
  classified → drafted → approved and released, with names.
- Nearest assistance with distance and ETA
- The triage agent's declared unknowns, shown to the crew as "what shore still needs
  to know", for the people who can actually answer them

### `/ops`: operations portal
For the shore watch. Dense, dark, map-dominant.

- World traffic picture at fleet scale, viewport-culled
- Incident queue with severity, confidence and pending-approval counts
- Triage detail: classification, basis, declared unknowns, classifier and latency
- Per-recipient packets behind the approval gate
- Manual intake for reports arriving by radio, sat phone or email
- Append-only audit log

### `/control`: control panel
For engineers and demos. Amber accent so it is never mistaken for the ops console.

- Search 60,000 hulls, inject any of 12 emergencies
- Live fleet statistics and simulator pause
- LLM provider chain and circuit-breaker state
- Active casualty list with stand-down

Every portal carries the persistent banner: simulated traffic, decision support only,
supplementary to GMDSS and never a replacement.

## Engineering standards: this must not read as vibe-coded

- Typed tool contracts (pydantic), not string-interpolated prompts
- **Deterministic eval suite** over a fixed corpus of incident scenarios, scoring
  classification accuracy per incident type. This is the single most valuable
  artifact in the repo. It gates CI. Report the numbers in the README.
- The deterministic baseline classifier is kept permanently as the floor. An LLM
  triage that cannot beat it is not earning its latency, cost, or failure modes.
- Structured tracing on every agent hop (inputs, outputs, latency, provider used)
- Circuit breaker + explicit fallback on the LLM provider chain
- Simulator is deterministic under a fixed seed, so a scenario replays exactly

## Milestone 1 (complete)

1. ✅ World map, ~60,000 hulls moving in real time, viewport-culled
2. ✅ Control panel injects any of 12 emergencies into any vessel
3. ✅ Vessel renders red, telemetry changes, incident opens in the queue
4. ✅ LangGraph triage agent classifies it
5. ✅ Five per-recipient response packets, all pending approval
6. ✅ Eval suite with a CI gate, plus `test_sesn.py` invariant checks
7. ✅ Three portals: seafarer, operations, control

### Next
- Fill the agent column of the eval table (needs a free-tier API key)
- Procedure retrieval over Qdrant (M2), which is what makes the packets
  procedure-grounded rather than template-grounded
- Expert review of the eval corpus labels

Do not build the full system before publishing. Publish M1, then iterate in the open.

## README must include

- Architecture diagram
- **Honest limitations section**: simulated traffic only, no real AIS, not connected
  to any real distress system, decision support only, eval labels are not
  professionally validated
- Eval results table, baseline and agent side by side
- The GMDSS disclaimer

## License

BSL 1.1. Source-visible, non-commercial use permitted, commercial use requires
permission, converts to Apache 2.0 after four years. Not OSI open source, and that is
intentional.
