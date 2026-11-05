# 006 B7 Acceptance Packet — R01–R18 Traceability with Live Omissions

**Feature:** 006 — Reliable household operation and understandable gaming reports
**Batch:** B7 (T13–T14), task T14 — integrated release rehearsal and acceptance packet
**Evidence level:** P (packaged synthetic integration). O = offline implementation, L = separately authorized live operation, H = human acceptance.
**Status:** T13 and T14 implemented and offline-verified; **B4–B7 reviewed and accepted by the owner on 2026-11-04**. No live operations performed.
**Commit baseline:** `f9bfb86` (T13) plus T14 rehearsal tests; `make quality` = 557 offline tests, lock/format/lint clean.
**Live gate:** L1–L3 remain owner-executed and are recorded below as unevaluated, never marked passed.

---

## How to read this packet

Each requirement R01–R18 (from [spec r1](spec.md#requirements-and-measurable-acceptance)) is mapped to:

- **Evidence** — the offline (O) / packaged synthetic (P) implementation that covers it, with test files.
- **Status** — `implemented` (code present), `verified` (offline tests pass), or `pending-live` (requires an L gate).
- **Live omissions** — what the L1/L2/L3 gates must establish before the requirement can be claimed live.

Passing O/P is not L/H (spec §Requirements). The accepted 18.591-hour 005 campaign is historical evidence, not the 006 72-hour gate.

---

## Traceability matrix

| ID | Requirement (short) | Evidence level | Test coverage | Status | Live omissions (L gate) |
|----|---------------------|----------------|---------------|--------|-------------------------|
| R01 | One explicit private config path; strict loader; secret-free example; precedence; no `.env.auto` | O/P | `tests/offline/test_settings.py`, `tests/offline/test_stack_cli.py` (example-config round trip, duplicate keys, frozen dataclass fix), `src/household_report/operator_config.py` | verified | None (offline-complete) |
| R02 | Shared credential parser; bare/dotenv equivalence; reject missing/dup/malformed/permissive/unsafe; AI-off needs no keys | O/P | `tests/offline/test_settings.py`, `src/household_report/credentials.py`, `src/household_report/operator_config.py` | verified | None (offline-complete) |
| R03 | One immutable image ID for both dashboards; mixed images block start/upgrade; no startup downloads | O/P | `tests/offline/test_release.py`, `tests/offline/test_packaging.py`, `tools/release_manifest.py`, `src/household_report/release.py` | verified | Deployed image IDs must be read live and compared at L1; current running images differ (status report) |
| R04 | Both 8787/8789 relay paths from one manifest; independent rollback; DNS/8443 unchanged; packet matrix incl. direct VM/container paths and forged Hosts | O/P | `dns-pilot/test_network_contract.py` (17), `dns-pilot/test_dashboard_relay.py` (4), `dns-pilot/network_policy.py`, `dns-pilot/network_contract.py` | verified | Actual nft/conntrack/Docker-iptables behavior, hook ordering, anti-spoofing, second-device paths — `network_contract.live_preconditions()` names them unevaluated |
| R05 | Shared origin `http://192.168.1.10:8787`; owner origin `https://192.168.1.10:8789`; no wildcard/IPv6; owner auth/TLS/CSRF; shared cannot dispatch AI | O/P | `tests/offline/test_packaging.py` (compose binds, AI-off defaults), `tests/offline/test_stack_cli.py` (owner profile maps credentials), `compose.ai.yaml`, `compose.lan.yaml` | verified | Wildcard `0.0.0.0:8789` bind migration to the 006 manifest; TLS cert SAN/trust; second-device TLS/login/CSRF; shared AI POST denial — all L1 |
| R06 | Identity preflight before capture/import; mismatch fails closed; first registration explicit; source-reset recovery separate | O/P | `tests/offline/test_host_bridge.py` (10), `tests/offline/test_campaign_cli.py`, `tools/host_bridge.py`, `src/household_report/campaign.py` | verified | Install-time identity preflight runs only when owner executes L1; real systemd timer not exercised |
| R07 | Status shows timer/bridge/capture/import/report; last-success UTC+local timestamps; failure visible without bridge self-reporting | O/P | `tests/offline/test_collector_status.py`, `tests/offline/test_web.py` (collector panel), `src/household_report/collector_status.py` | verified | Real timer/systemd state; live capture tick; heartbeat against actual bridge — L |
| R08 | Distinct states: no campaign / waiting / empty / partial / stale / failed / expired / historical; zero work is not capture success | O/P | `tests/offline/test_collector_status.py`, `src/household_report/collector_status.py` (latch, 720s/900s bounds) | verified | Live capture/import freshness; settled-data distinction — L3 |
| R09 | Finite retries; idempotence via generation/query identity; restart catch-up retains deadline; no silent renewal | O/P | `tests/offline/test_maintenance.py` (journal, backup, restore, guards), `tests/offline/test_stack_cli.py` (interrupted-stage resume) | verified | Controlled restart/reboot persistence; retained-history catch-up; original deadline preservation — L2/L3 |
| R10 | setup/check/start/status/stop/restart/upgrade/rollback/backup/restore/uninstall/journal; default stop preserves evidence; isolated restore | O/P | `tests/offline/test_stack_cli.py` (30, full driver walkthrough), `tools/stack_cli.py`, `src/household_report/maintenance.py`, `docs/operations/stack-lifecycle-runbook.md` | verified | Real Docker/systemd apply of stack-* commands; install/migrate/publish — L1 |
| R11 | Campaign-to-date / local day / 24h / 48h periods; requested vs actual bounds; DST; legacy one-hour snapshot labelled | O/P | `tests/offline/test_campaign_reporting.py`, `src/household_report/campaign_reporting.py`, `src/household_report/campaign.py` | verified | Live period rendering against a real campaign — L3 |
| R12 | Game/platform/service, lookup times, endpoint purpose, evidence; purpose vocabulary; deterministic summaries without paid call | O/P/H | `tests/offline/test_gaming.py`, `tests/offline/test_campaign_reporting.py`, `src/household_report/gaming.py`, `PURPOSE_BY_ROLE` | verified (O/P); H pending | Owner comprehension of report — H (T17) |
| R13 | Exact-host review proposals; reject generic labels and CDN/publisher broadening; model vs human-reviewed distinguishable | O/P/H | `tests/offline/test_gaming.py` (`validate_review_proposal`), `src/household_report/gaming.py` | verified (O/P); H pending | Human acceptance of reviewed rules — H (T17) |
| R14 | Explicit "generate updated report"; immutable predecessor/revision; same-input reuse; page/CSV/JSON parity | O/P | `tests/offline/test_campaign_reporting.py`, `src/household_report/storage.py` (schema v7 lineage), `src/household_report/campaign_reporting.py` | verified | Live report revision against real evidence — L3 |
| R15 | Select exact eligible names; preview binds candidates/period/model/budget; changed inputs need new preview; unresolved refusals don't loop | O/P | `tests/offline/test_research.py`, `tests/offline/test_analysis.py`, `src/household_report/research.py`, `src/household_report/analysis.py` | verified | Live owner selection/confirmation from a second device — L3/L4 |
| R16 | Coverage states with denominators; worklist ≤20; >40-name progression without repeats; terminal dispositions | O/P | `tests/offline/test_research.py`, `tests/offline/test_analysis.py`, `src/household_report/research.py` | verified | Live owner research worklist — L4 (optional paid) |
| R17 | Safe error codes; budget enforcement (atomic reservations); paid mode needs explicit ceilings/disclosure; ordinary flows make zero calls | O/P | `tests/offline/test_settings.py` (paid-mode fail-closed), `tests/offline/test_analysis.py`, `tests/offline/test_openai_compatible.py`, `src/household_report/settings.py` | verified (O/P); optional L | Live Mistral readiness/price check; paid-mode spend ceiling — L4 (optional, not required for completion) |
| R18 | Runbooks/architecture/project scope describe commands, two access profiles, host deps, schema, limitations; fresh install + migration rehearsed | O/P/H | `docs/operations/stack-lifecycle-runbook.md`, `docs/operations/household-bringup-runbook.md`, `docs/reference/current-architecture.md`, `tools/stack_cli.py` | verified (O/P); H pending | Owner acceptance of outcomes and report comprehension — H (T17) |

---

## Integrated rehearsal evidence (T14)

The rehearsal test `tests/offline/test_release_rehearsal.py` (4 tests, added for T14) runs one disposable offline flow:

1. **AI-off shared profile:** `setup → check → start → stop → restart → status` through `stack.StackDriver` with a `FakeRunner`, asserting zero external effects, neutralized ambient compose vars, campaign not started, network unchanged, spend disabled.
2. **AI-on owner profile:** `setup → start` asserts `compose.ai.yaml` is used, provider credentials mapped into container paths (never the secret value), `HR_PORT=8789`.
3. **Maintenance transaction:** `upgrade → rollback → backup → isolated restore → uninstall → journal`, asserting the six-stage journaled transaction completes, backup digests verify, restore is isolation-only into an empty 0700 directory, uninstall removes only owned publication and retains evidence/DNS.
4. **120-hour synthetic campaign:** `campaign_benchmark.prepare` starts a 5-day campaign, acknowledges/imports 14,400 synthetic windows, freezes a to-date report, exports JSON+CSV, finalizes. `campaign_benchmark.verify` (separate process view) confirms the frozen report digest is unchanged, generates a completed-day report, and performs backup/verify/isolated restore. Resource measurements recorded: peak RSS ~77 MiB, CPU ~10 s, total < 1 s for the synthetic clock.

Resource measurements with accurate scenario labels:
- `campaign:scenario_label = 120h-full-campaign`; `campaign:scenario_label_recovery = 120h-full-campaign-recovery`
- `peak_rss_kib`, `cpu_seconds`, `database_bytes`, `archive_database_bytes`, `artifact_bytes` recorded per phase.

---

## Live omissions (unevaluated, never marked passed)

These are established only at the separately authorized L gates; this packet records them as pending:

| Gate | What must be established live | Owner action |
|------|------------------------------|--------------|
| L1 | Install/migrate/publish: rendered network/unit scripts, exact endpoint/interface/source list, release pair, migration preview, schema backup/restore proof, maintenance window, rollback commands; second-device allowed/denied paths; TLS/login/CSRF; shared AI denial; no wildcard bind | Owner executes root steps; DNS/8443 unchanged |
| L2 | Restart/reboot: boot order/guards, intended stopped-state behavior, both matching releases and bridge availability; distinguish application restart vs VM reboot vs Proxmox reboot | Owner selects components/hosts and outage window |
| L3 | Campaign: first settled capture/import, status/failure visibility, sustained operation through deadline, retained-history recovery, explicit gaps, final report/export; new 72-hour observation with start/end, retention, generation, namespace revision, disk budget | Owner explicitly authorizes start/end, retention, generation, namespace revision, disk budget |
| L4 | Optional paid research: exact public names, provider/model/endpoint, category caps, currency ceilings, readiness/price check — separate explicit confirmation | Separate explicit owner confirmation; not required for feature completion |

---

## Completion statement for B7

- T13 (command surface + canonical operator docs): implemented, offline-verified, pushed (`f9bfb86`).
- T14 (integrated release rehearsal + R01–R18 acceptance packet with live omissions): implemented, offline-verified (557 tests), this packet.
- **The owner reviewed and accepted the combined B4–B7 review packet on 2026-11-04**, closing offline implementation for 006 B4–B7.
- No deployment, LAN publication, capture, campaign, or paid call has occurred. Advancing to B8/L1 requires the separately gated L1 approval and owner-executed root steps; L2, L3 and optional L4 each need their own decision and evidence record.
