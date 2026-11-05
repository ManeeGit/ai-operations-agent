# Local verification record

Verified on 2026-11-05 in a Linux cloud workspace with Python 3.12.14. These results apply to this source snapshot; they are not a claim about a published deployment or a user's Mac.

| Check | Result |
| --- | --- |
| Python unit/integration suite | 55 passed |
| Seeded offline evaluation | 200/200 passed across 10 scenario families and 20 seeds |
| Synthetic label precision / recall | 1.0 / 1.0; 180 true-positive labels, 0 false positives, 0 false negatives |
| Dashboard DOM/API contract suite | 10 groups passed |
| Python compilation | Passed |
| JavaScript syntax check | Passed |
| Wheel build and installation | Passed; runbooks and all 3 static assets present |
| Installed bounded demo CLI | Passed |
| Real loopback monitoring CLI | 3 health probes produced 1 expected memory incident |
| Console process smoke | HTML, API, CSRF-protected scenario injection, metrics passed |
| SIGTERM shutdown | Passed |
| Independent code review | Three concrete findings fixed and regression-tested; targeted recheck passed |

Review fixes covered malformed/truncated HTTP responses, wall-clock deadlines for slow headers/bodies, and accepted-baseline persistence across more than 1,000 anomalous samples and restart. Additional guards reject non-regular log files without blocking and keep missing resource metrics unknown.

The evaluation is deliberately synthetic and authored alongside the detector. It proves consistency of these scenarios, not production incident accuracy. The real local model was not installed or exercised. Mocked tests cover its response/fallback boundary only.

Screenshot, browser layout, and actual browser CSP enforcement were **not verified** because the available Chromium process was restricted by the environment. The dependency-free DOM contract harness does not substitute for pixel-level browser QA. Hosted GitHub Actions, Python 3.11/3.13 execution, real 8 GB Mac resource use, and always-on deployment are also **not verified** here.

A single in-memory 48-sample cascade replay measured 15,744 KiB peak resident memory for the Python process in this Linux workspace. This excludes browser and model memory and is not a Mac capacity guarantee.
