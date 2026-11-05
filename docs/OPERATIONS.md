# Configuration and operations

## Commands

```bash
# Synthetic local console (database: .ops-agent/demo.sqlite3)
ops-agent serve --port 8765

# Local service console (database: .ops-agent/monitor.sqlite3)
ops-agent serve --config examples/monitor.toml

# Bounded headless probe, then print JSON
ops-agent monitor --config examples/monitor.toml --cycles 3

# Continuous headless probe until Ctrl+C / SIGTERM
ops-agent monitor --config examples/monitor.toml

# Bounded synthetic report, in-memory database only
ops-agent demo --scenario cascade --output artifacts/demo.json
```

`--db PATH` overrides the state file for `serve`/`monitor`. A file first bound to demo cannot be reopened as monitor, or vice versa. Keep separate files. Ctrl+C stops the foreground process; no launch agent or daemon is installed automatically.

## Configuration format

```toml
[agent]
interval_seconds = 5

[[services]]
name = "my-api"
health_url = "http://127.0.0.1:9000/health"
log_file = "./approved-synthetic.log"
```

- 1–8 services; unique names containing letters, numbers, `_`, `.`, or `-`.
- Interval 1–3,600 seconds. This is the delay after a polling cycle, not a fixed-rate scheduler.
- Explicit numeric loopback address and port. `localhost` is deliberately rejected for probes to avoid hostname-resolution ambiguity. Console navigation supports `localhost` and `127.0.0.1`.
- Health endpoints must be HTTP without credentials, query, or fragment. Redirects are rejected. Network proxies are ignored.
- A log path is optional and resolves relative to the configuration file. The collector reads up to 32 KiB and 12 recent lines each cycle. Only regular application log files are accepted. Special device/FIFO paths are rejected without blocking.
- JSON log objects may provide `message` and `level`; plain text is also accepted. Evidence timestamps indicate collection time.
- The current implementation uses fixed threshold defaults in `detection.py`. Change them in source with tests if your service needs different SLOs.

## Endpoint contract

The endpoint should return a small JSON object with optional keys:

| Key | Type and bounds | Meaning |
| --- | --- | --- |
| `health_ok` | boolean | Application's current health judgment |
| `latency_ms` | finite number, 0–3,600,000 | Application latency metric, or probe round-trip when missing |
| `error_rate` | finite number, 0–1 | Fraction, not percentage |
| `cpu_pct` | finite number, 0–100 | CPU utilization reported by the application |
| `memory_pct` | finite number, 0–100 | Memory utilization reported by the application |

A successful empty response is accepted as a basic health success. Missing CPU/memory values remain unknown (JSON null), not OS measurements. HTTP failures, unreachable ports, and timeouts become failed probe samples; malformed JSON/range violations become collector-error audit events. Samples must be valid before entering the baseline.

## Continuous operation and an 8 GB Mac

The baseline application has no machine-learning runtime or heavyweight framework. It uses Python standard-library threads, SQLite, and static browser files. A local LLM is optional and usually dominates resource use.

Recommended progression:

1. Run the synthetic demo without a model.
2. Run the local example service and inspect collection, incidents, and recovery.
3. Measure the foreground process and browser memory in Activity Monitor.
4. If useful, install an appropriately small quantized model using official Ollama instructions. Start the agent with `--ollama-model` and measure again.
5. Only after validating the application, choose a process supervisor on a machine you control.

A laptop does not monitor while asleep, powered off, or disconnected from its local services. For genuinely continuous coverage, use an always-on host plus an appropriate supervisor and monitoring of this agent itself. No deployment, launchd job, login item, cloud hosting, or system configuration is created by this repository. Do not enable anything with elevated privileges just to run this demo.

## Console API

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/` | Static console |
| GET | `/api/overview` | Services, incidents, stats, events, local CSRF token |
| GET | `/healthz` | Agent process health and no-execution flag |
| GET | `/metrics` | Prometheus counters and active-incident gauge |
| POST | `/api/demo` | `{ "scenario": "cascade" }`; demo mode only |
| POST | `/api/incidents/{id}/ack` | `{}`; changes local acknowledgement only |

POST requires `Content-Type: application/json` and `X-Ops-Token` from the current overview. Requests with unexpected Host or cross-origin Origin are rejected. Tokens change on process restart. Only GET routes are suitable for unauthenticated scrape clients; the console itself is not an authenticated remote API.

## Metrics and retention

`ops_agent_samples_total`, `ops_agent_incidents_total`, and `ops_agent_incidents_open` are useful for observing activity. Model-call/failure counters are per-process; sample/incident totals persist in SQLite. `/healthz` says the server is responsive, not that every service or collector is working. Inspect `collector_error` events for probe/schema problems.

SQLite uses WAL. Keep runtime state out of Git. The application retains 2,000 samples, 1,000 events, and roughly 200 incidents plus older active incidents. Retention reuses pages and is not a guaranteed small file-size cap. Stopping the process before copying its database is the simplest backup approach; an online raw-file copy may omit WAL state.

## Troubleshooting

- **Port busy:** choose another `--port`; do not kill unrelated processes.
- **No model:** omit `--ollama-model` for deterministic operation. Review the diagnosis fallback notice and model-failure count.
- **Monitor looks empty:** verify the endpoint in your browser, check `collector_error` events, and use `examples/sample_service.py` as a known fixture.
- **Mode mismatch:** use a separate database file, rather than trying to reuse synthetic state for live service history.
- **Model inference stalls sampling:** use a smaller model or disable it. The 20-second timeout and cooldown bound work, but do not eliminate delays.
- **False positives/negatives:** inspect baseline and threshold evidence. The defaults are examples; validate against labelled incidents and actual service SLOs before relying on them.
