# Evaluation and verification

## What the offline evaluation measures

`python evals/run.py --seeds 20` replays ten hand-authored scenario families over 20 deterministic seeds, for **200 runs**. Each run uses a fresh in-memory store, 12 healthy frames across 3 services, then a bounded scenario.

Labels are active `(service, incident kind)` pairs at the end of each replay. Precision and recall count those labels, not individual samples. Recovery cases expect an empty active set even though historical incidents remain.

Scenario families:

1. Quiet baseline: no active incidents.
2. Sustained latency: checkout latency incident.
3. Sustained error rate: payments errors incident.
4. Memory pressure: inventory memory incident.
5. Cascade: the three preceding symptoms together.
6. One-frame spike: suppressed by consecutive-sample confirmation.
7. Confirmed health failure: availability incident.
8. Sustained CPU saturation: inventory CPU incident.
9. Healthy recovery: all previous cascade incidents resolved.
10. Malicious log instructions: memory incident, with no instruction execution or secret-value leakage into the report.

Each run also checks that the primary runbook matches the incident kind, all next steps require a human, and no executable-command field is emitted.

## Limits of this evidence

The generator and thresholds were authored together, so a perfect score is expected and only indicates regression consistency. These are not independent real-world incident labels. There is no estimate of production precision, recall, time-to-detect, business impact, or false-alert burden under seasonality.

The offline suite does **not** call a real LLM. Mocked tests validate the local model boundary, response schema, cooldown, and failure fallback, not model reasoning quality. The prompt-injection scenario demonstrates deterministic data handling and non-execution; it does not certify arbitrary models against all adversarial prompts.

The dashboard is tested separately for safe literal rendering, state transitions, repeated requests, retry handling, and accessibility structure. Browser screenshot/layout verification may require a machine with a supported browser sandbox.

## Reproduce checks

```bash
python -m pip install --no-deps .
python -m unittest discover -s tests -v
python evals/run.py --seeds 20 --output artifacts/evaluation.json
ops-agent demo --scenario cascade --output artifacts/demo.json
python -m compileall -q src tests evals examples
node --check src/ops_agent/static/app.js
node tests/test_dashboard.mjs
```

Coverage areas include numeric/input boundaries, redaction, baseline contamination, warmup thresholds, service isolation, incident deduplication, acknowledgement, recovery/reopen, restart rehydration, mode separation, retention, prompt/schema validation, model fallback, log rotation, loopback/redirect limits, actual HTTP collection, Host/Origin/token checks, API payload bounds, and Prometheus output.

Hosted CI is configured for Python 3.11/3.12/3.13 and uploads generated JSON reports. Verify the specific remote commit's CI before claiming all supported versions pass.
