# AI Operations Agent

**A local-first operations copilot that turns abnormal telemetry into evidence-backed incident triage.**

Observe services, catch sustained anomalies, retrieve relevant runbooks, and review suggested next steps in a lightweight local console. Optional Ollama inference adds a constrained explanation. The agent never runs remediation commands.

Python 3.11+ · SQLite · Vanilla JavaScript · **Zero runtime dependencies** · MIT

## Why this project

A useful operations agent needs more than an LLM prompt. It needs trustworthy telemetry boundaries, stable detection, evidence selection, incident lifecycle management, explainable fallback, and a clear limit on authority. This project implements those pieces as an inspectable, small application.

**Built:** streaming robust baselines, absolute guardrails, incident deduplication and recovery, runbook retrieval, constrained local-model output, bounded persistence, a local dashboard, Prometheus metrics, and an offline evaluation suite.

**Not claimed:** verified root-cause analysis, production SRE replacement, autonomous remediation, or a guarantee of 24/7 availability on a sleeping laptop.

## Run in two minutes

No API key or model download is needed.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --no-deps .
ops-agent serve
```

Open **http://127.0.0.1:8765**. The console starts with a synthetic checkout-latency incident. Try **Cascade**, inspect each incident's evidence and runbook, acknowledge an incident, then choose **Healthy** to observe recovery. Acknowledgement only changes local tracking state.

A completely offline, bounded replay:

```bash
ops-agent demo --scenario cascade --output artifacts/demo.json
```

For a source checkout without installation:

```bash
PYTHONPATH=src python -m ops_agent serve
```

## What happens to a signal

```text
Local HTTP health + optional log tail       Seeded synthetic demo
                 \                         /
                  Validated, redacted sample
                              |
               Robust rolling baseline + guardrail
                              |
           2-sample confirmation / incident deduplication
                              |
                  Relevant runbook retrieval
                              |
             Optional local Ollama summary (bounded)
                    | invalid or unavailable
                    +------ deterministic fallback
                              |
            SQLite incident + evidence + audit event
                              |
                Local console / JSON / Prometheus
                              |
                    Human reviews next steps
```

There is deliberately **no remediation executor**. The model cannot add tools, write shell commands, change detection rules, or create new operational steps. Proposed steps come from versioned runbooks.

## Live local monitoring

Start the included harmless example service in another terminal:

```bash
python examples/sample_service.py --scenario memory
```

Then observe it:

```bash
ops-agent serve --config examples/monitor.toml
# Or a bounded headless check:
ops-agent monitor --config examples/monitor.toml --cycles 3
```

The health endpoint accepts a JSON object:

```json
{"health_ok": true, "latency_ms": 80, "error_rate": 0.002, "cpu_pct": 30, "memory_pct": 42}
```

All metrics are optional. Missing latency uses measured probe round-trip time; missing error rate uses 0 for a successful health check or 1 for a failed probe. Missing CPU and memory are **unknown** (JSON null), not measured zero utilization. Use an application-specific endpoint that supplies metrics for meaningful resource monitoring. See [configuration and operations](docs/OPERATIONS.md).

## Optional local AI

The deterministic path is fully functional. To enable model-assisted summaries, install Ollama separately from its official source, choose and download a small model yourself, and run:

```bash
ops-agent serve --ollama-model YOUR_INSTALLED_MODEL
```

Only **http://127.0.0.1:11434/api/generate** is used; proxy environment variables and redirects are disabled. No cloud-model integration is included. The agent does not install Ollama, download a model, or enable a background service for you.

The model receives bounded, redacted evidence and candidate runbooks. It returns JSON containing a short summary, low/medium confidence, and allowlisted runbook IDs. Invalid output or connection failure falls back to deterministic triage. Calls have a 20-second timeout, 30-second cooldown, 2,048-token context, and 256-token output budget. A model call can slow the polling loop; this is not a low-latency inference service.

On an **8 GB Mac**, start without a model. If desired, use a small quantized model supported by your installed Ollama version, close heavy applications, and measure memory locally. Model memory and speed depend on architecture and quantization; neither has been benchmarked on the user's Mac. [Deployment notes](docs/OPERATIONS.md#continuous-operation-and-an-8-gb-mac)

## Test and evaluate

```bash
python -m unittest discover -s tests -v
python evals/run.py --seeds 20 --output artifacts/evaluation.json
python -m compileall -q src tests evals examples
node --check src/ops_agent/static/app.js
node tests/test_dashboard.mjs
```

The evaluation covers healthy baselines, sustained latency/errors/memory/CPU problems, a multi-service cascade, isolated-spike suppression, failed health checks, recovery, and malicious log instructions. All data is synthetic. Precision/recall here are **regression metrics on hand-authored cases, not production detection accuracy**. Optional real-model quality is not evaluated by these deterministic tests. [Evaluation design](docs/EVALUATION.md)

GitHub Actions is configured for Python 3.11, 3.12, and 3.13. Local verification does not imply hosted CI has run.

## Safety and privacy

- Loopback-only console and numeric-loopback health probes. No remote dashboards or arbitrary URL fetching.
- State-changing API calls require a session token, JSON, and an allowed Origin/Host. No permissive CORS.
- Sensitive-looking log values are redacted before SQLite/model use. Redaction is best effort, not a DLP guarantee.
- Bounded log reads, model responses, requests, thread count, samples, and events.
- Separate demo/monitor databases; mismatched mode reuse is rejected.
- Logs and model text are untrusted data, never executable instructions.
- No telemetry analytics, paid APIs, notifications, Slack integration, Docker socket, or subprocess execution.
- Local database and console contain operational data. Other processes/users with local access may read it. Do not expose the port or feed sensitive production logs without a separate security review.

See the [threat model](docs/SECURITY.md) and [known limitations](docs/ARCHITECTURE.md#limitations-and-tradeoffs).

## Repository guide

| Area | Purpose |
| --- | --- |
| `src/ops_agent/detection.py` | Robust baseline, absolute limits, consecutive-sample confirmation |
| `src/ops_agent/engine.py` | Incident lifecycle, recovery, metrics, orchestration |
| `src/ops_agent/triage.py` | Runbook retrieval, constrained local-model bridge, fallback |
| `src/ops_agent/collectors.py` | Loopback HTTP probe and bounded explicit log tail |
| `src/ops_agent/storage.py` | Thread-safe bounded SQLite persistence |
| `src/ops_agent/server.py`, `static/` | Local protected API and dashboard |
| `evals/` | Seeded synthetic regression cases and score report |
| `tests/` | Unit, persistence, HTTP, safety, and collector tests |
| `docs/` | Architecture, operations, threat model, evaluation |

## Portfolio discussion

Useful interview topics include why baseline contamination matters, how alert confirmation trades speed for noise reduction, why model authority is restricted independently of prompt quality, how recovery differs from acknowledgement, and where synthetic evaluations stop providing evidence. Extend this project by adding authenticated remote collectors, richer time-series metrics, or real incident labels, with explicit tests and a new threat assessment.
