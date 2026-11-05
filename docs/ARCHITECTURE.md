# Architecture and design decisions

## Components and boundaries

1. `Sample` validates finite numeric ranges, timestamp timezone, short service IDs, and bounded log count.
2. `Collector` reads explicit numeric-loopback health endpoints and optional local log paths. Requests use no proxy and never follow redirects. Unsupported/bad JSON produces a collector-error event rather than fabricated telemetry.
3. `Detector` maintains independent bounded reference windows for each service and metric.
4. `Engine` serializes ingestion, groups incidents by service and signal kind, retrieves triage only on creation, and tracks acknowledgement and recovery.
5. `Triage` ranks local runbooks by symptom type and token overlap. A local model may choose only among retrieved IDs. Operational steps remain authored, versioned text.
6. `Store` serializes SQLite access across the polling and HTTP threads. The database retains samples, incidents, counters, audit events, and a demo/monitor mode binding.
7. `ConsoleServer` serves static assets and protected local API routes. It has no shell, upload, remote URL, or action-execution API.

## Detection math

For each service/metric, keep the latest 60 accepted values. A reference baseline becomes available after 8 accepted observations. Let `m = median(window)` and `MAD = median(abs(x - m))`.

```text
adaptive = max(m + max(6 × 1.4826 × MAD, minimum_delta), m × minimum_ratio)
threshold = min(absolute_guardrail, adaptive)
```

During warmup, only the absolute guardrail applies. A value must be strictly greater than the threshold for two consecutive samples. Health failure also requires two consecutive samples. Anomalous values are not added to their own reference distribution, even before confirmation.

| Metric | Absolute guardrail | Minimum delta | Minimum ratio |
| --- | ---: | ---: | ---: |
| Latency | 2,000 ms | 150 ms | 2.5 |
| Error rate | 0.10 | 0.03 | 3.0 |
| CPU | 95% | 25 points | 1.7 |
| Memory | 92% | 20 points | 1.5 |

This is transparent robust-statistical detection, not a trained predictive model. Floors avoid overreacting to almost-constant low-noise metrics. Fixed thresholds are demonstration defaults, not universal SLOs. Per-service SLOs, seasonality, and workload normalization are future work.

## Incident state machine

```text
Two consecutive violations -> OPEN
OPEN -> ACKNOWLEDGED (human click, local state only)
OPEN or ACKNOWLEDGED -> RESOLVED (3 consecutive non-abnormal samples)
New violation after resolution -> new OPEN incident
```

Active incidents are deduplicated by service/kind. Repeated abnormal samples update occurrence count, signal values, latest evidence, and timestamp. The original diagnosis is retained; it is not a continuously refreshed investigation. Acknowledged incidents remain active and can recover normally. A single good sample cannot resolve a sustained incident.

Restart restores accepted reference windows and confirmation streaks from a separate persisted detector-state table, independent of raw-sample retention, and restores active incident state. Recovery streaks restart at zero. No external action is triggered by replay.

## Retrieval and constrained generation

Runbook score is 100 for a matching signal kind plus one per keyword overlap in log text. Only positively scored candidates are retained (up to two). This intentionally simple lexical retrieval is inspectable and adequate for a five-runbook catalogue. It is not vector search or a claim of semantic understanding.

Local-model response schema:

```json
{"summary":"A hypothesis, not a verified cause.","confidence":"low","runbook_ids":["RB-LATENCY"]}
```

The validator rejects additional keys, unknown IDs, oversized summaries, high confidence, and common command/URL/instruction patterns. That last filter is supplementary, not a full semantic prompt-injection detector. Security comes primarily from **absence of executable capabilities**, output provenance, safe text rendering, and fixed action templates. A plausible but false summary is still possible.

## Persistence and resource bounds

- 2,000 most-recent telemetry samples.
- 1,000 most-recent audit events.
- At most 12 evidence lines per incident, 1,000 redacted characters per line.
- Up to 64 engine service identities and 5 active kinds each; live config limits services to 8.
- Approximately 200 recently updated incidents plus older still-active incidents. Resolved older rows are pruned.
- 60 baseline values per metric per service.
- 16 simultaneous console request threads and 5-second socket reads.
- 2 KiB API request bodies, 16 KiB health responses, 32 KiB model responses.
- 32 KiB maximum log read per collector cycle, with at most 12 recent lines.

SQLite freed pages are reused but the on-disk file does not necessarily shrink. Retention is a debugging convenience, not durable audit retention. WAL supports local concurrency; this remains a single-process application, not a distributed service.

## Limitations and tradeoffs

- Fixed thresholds and a short baseline do not model seasonality, business impact, dependency topology, or cross-service causal attribution.
- Each correlated symptom can create its own incident. A cascade scenario is three related synthetic symptoms, not a causal graph inference.
- Detector state is persisted after each valid sample, separately from incident updates. A process crash between those writes can leave a sample or confirmation one step ahead of the incident state; replay is not a distributed exactly-once guarantee.
- Telemetry order is arrival order; timestamps are validated but not used for event-time sorting. Adapters should emit current samples, not out-of-order replays.
- Missing CPU/memory values stay unknown and cannot resolve existing resource incidents. A healthy endpoint does not mean an entire distributed service is healthy.
- Health failures infer an error rate of 1 for the probe, not measured application traffic.
- Optional log tails are best-effort evidence, not a durable log shipper. Rotation, long lines, or rapid append can drop data, and partial lines can be read separately. There is no persistent log cursor.
- Probe failures become availability/error signals. Invalid telemetry creates an audit error and leaves the last sample; monitor-mode services become unknown after 60 seconds without a fresh sample.
- Service status is based on confirmed active incidents; one unconfirmed anomalous sample can still appear healthy. Last-seen time and raw values are shown.
- Model calls are synchronous within ingestion. Dashboard reads remain available, but acknowledgement and next sampling can wait for inference.
- The monitor has no external notifications, authentication roles, HA failover, reliable scheduling while a computer sleeps, or autonomous actions.
