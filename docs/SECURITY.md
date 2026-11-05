# Security model

## Intended deployment

A single operator on a trusted development machine, observing synthetic or approved local service telemetry. The dashboard binds only to `127.0.0.1`. Do not reverse-proxy it to a public/shared network. It is not a multi-tenant production monitoring product.

## Threats and controls

| Threat | Control | Residual risk |
| --- | --- | --- |
| Malicious log instructions | Logs remain data; fixed runbook templates; model cannot execute tools | Summary text can still be misleading |
| Browser-based request forgery | Allowed Host/Origin, per-process token on POST, JSON requirement, no CORS | A compromised local process can fetch the token |
| DNS rebinding | Console rejects unexpected Host; probes require numeric loopback IPs | Other local processes remain trusted |
| SSRF / cloud metadata requests | Loopback-only URL validator, no userinfo/query/fragment, no redirects/proxies | User-configured loopback endpoint can itself proxy elsewhere |
| Secret disclosure in logs | Bounded best-effort redaction before persistence/model use | Unknown formats and other sensitive content may remain |
| Model hallucination or unsafe commands | Bounded schema and ID allowlist, authored human-review steps, no executor | Natural-language hypotheses require judgment |
| Resource exhaustion | Bounded inputs/retention/threads; HTTP and model timeouts | An untrusted local actor can still consume resources |
| HTML injection | API values use DOM textContent; CSP; fixed static paths | Browser/OS compromise is outside scope |
| Synthetic data contaminating monitoring | Separate default databases and persistent mode binding | Operator can deliberately edit database files |
| Misleading stale state | Last-seen labels; monitor state unknown after 60 seconds | Alerting is unavailable if the entire process stops |

## Data flow

- Default demo: synthetic data stays in local process/SQLite/browser. No network traffic beyond loopback.
- Live monitor: only configured loopback health endpoints are read. Optional local log paths are read, never modified.
- Ollama opt-in: redacted incident evidence and selected runbooks go to the local Ollama endpoint. Whether Ollama, its model, or its own server logs retain/transmit data is outside this program's control; review your installation.
- No analytics, remote asset/CDN requests, push notifications, or cloud-model calls exist in this code.

The database is not encrypted. OS account controls and disk encryption remain your responsibility. Use non-sensitive logs, inspect evidence, and do not treat regex redaction as authorization to ingest secrets. Runtime databases, environment files, credentials, and generated artifacts are excluded by `.gitignore`.

## Operational authority

The API can inject synthetic observations and acknowledge a local incident. It cannot restart a process, modify a service, change firewall rules, scale infrastructure, run a shell command, send external messages, or perform a deployment. Adding any of these capabilities requires a new design, explicit authorization, auditable review, and new tests.

## Reporting issues

Report reproducible defects with synthetic examples. Do not include real credentials, personal data, production logs, or database files in public issues.
