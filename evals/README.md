# Eval suite

Deterministic scoring of incident triage over a fixed corpus. Every change to the
triage agent (prompt, model, provider, tool contract) is judged here before it
ships. The numbers go in the root README.

```bash
dotnet run                      # print the table
dotnet run -- --out results.md  # also write it
dotnet run -- --gate            # exit 1 on regression, for CI
```

## Corpus

`corpus.json`, 30 graded scenarios covering all ten incident types plus `Unknown`.
Each is a plausible intake (VHF transcript, sat-phone note, manager email, or AIS
telemetry with no text at all) paired with an expected type and severity.

All vessel names, MMSIs and positions are synthetic. Nothing here is a real vessel
or a real distress case.

The corpus deliberately includes cases where the cause and the effect are different
incident types (an attack that starts a fire, a grounding that floods the engine
room), and cases where the only signal is a distress MMSI prefix with no voice
contact, where the correct answer is `Unknown`, not a guess.

## Metrics

| Metric | Why |
| --- | --- |
| Incident type accuracy | Drives which authority is notified |
| Severity exact / within one band | Drives response urgency |
| **Under-triage rate** | The one that matters. Calling a critical incident routine is not symmetric with the reverse. |

Per-type recall and precision are reported too. An overall average hides a single
incident type collapsing to zero.

## Baseline

`Baseline.cs` is a keyword + AIS-rule classifier, not the product. It exists so the
agent has a floor to beat. Its term lists are written from maritime vocabulary, not
fitted to the corpus; fitting them would make the floor meaningless.
