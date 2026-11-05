# Household DNS Insights

[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](destination-report/pyproject.toml)
[![Package manager: uv](https://img.shields.io/badge/package%20manager-uv-6f42c1)](destination-report/uv.lock)
[![Tests: offline suite](https://img.shields.io/badge/tests-566%20offline-2e8b57)](CONTRIBUTING.md#verification)
[![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen)](CONTRIBUTING.md)

**A local-first observatory for household DNS traffic.** It captures what a home network actually asks for, runs bounded observation campaigns, and turns the result into reports that stay honest about what a DNS lookup can and cannot prove.

> **This is the public repository.** It contains the code, the design documents and the engineering record — with household-specific values removed. The live deployment (raw DNS evidence, session handovers, campaign state, credentials) stays in a private repository and is never published here. See [Public release](#public-release) for exactly what was removed or replaced.

The project began as a read-only investigation of a stock Starlink Gen 3 router. It is now a working system: a monitoring-only Pi-hole resolver, a capture bridge that moves settled windows into private storage, and a reporting application that produces frozen, evidence-backed reports on **possible gaming-related signals**.

> **It is not a gameplay detector, a parental-control tool or a clinical instrument.** A DNS lookup is a request. It is not proof that a game was played, that a connection succeeded, who made the request, or for how long.

## About

**Household DNS Insights** is a local-first system for observing what a home network asks its DNS resolver for, and for reporting those observations without overstating them.

- **Who it is for:** anyone running a home network who wants a readable, evidence-backed view of the names their devices look up — without blocking, without device profiling, and without handing traffic to a third party.
- **What it is not:** blocking, parental enforcement, gameplay detection, diagnosis, or any verdict about a person. A lookup is a request, not proof of what happened afterwards.
- **What it is made of:** a monitoring-only Pi-hole resolver, a capture bridge that moves settled windows into private storage, and a report application that produces frozen reports with explicit coverage, gaps and uncertainty.
- **Where it runs:** entirely on your own hardware. Ordinary reporting makes zero external calls; optional research runs are separately confirmed, budget-capped and recorded.

**This repository is the public, sanitized half of the project.** The live household deployment, its raw evidence and its session records live in a private repository — see [Public release](#public-release) for exactly what that split means.

The offline implementation is accepted and verified (566 offline tests; lock, format and lint clean). Live gates, campaign evidence and anything still pending are recorded in the [006 task ledger](specs/006-reliable-household-operation/tasks.md), and every operational step has its own runbook under [`docs/operations/`](docs/operations/household-bringup-runbook.md).

**Licensing:** no license file yet — ask the maintainer about reuse terms; do not assume an open-source license applies.

## What you get

- **Bounded campaigns.** Start a 72-hour observation; every hour becomes a settled capture window with its own state, and every gap stays visible instead of being smoothed away.
- **Frozen reports.** A campaign-wide report, a single local day, or the last 24/48 hours within campaign bounds — with observed names, lookup times, supporting evidence and the uncertainty attached to each claim. CSV and JSON follow the same frozen projection.
- **Coverage you can audit.** Each report shows what was collected, what failed, and what is simply unknown. A healthy web service is never mistaken for a working collector.
- **Two separate surfaces.** A shared household dashboard for reading reports, and a protected owner dashboard (TLS, login, CSRF) that is the only place optional research can be dispatched.
- **Optional, budget-capped research.** Selected public names can be classified by a provider you explicitly confirm, with per-run limits. Ordinary reporting makes zero external calls, and nothing is ever inferred from bandwidth patterns.

## How it fits together

```text
household devices
   │  DNS
   ▼
Starlink router ──► dish ──► space
   │  Custom DNS → 192.168.1.10
   ▼
Proxmox host — LAN relay (DNAT 192.168.1.10 → 10.10.10.20)
   ▼
Ubuntu VM 10.10.10.20
 ├─ Pi-hole, monitoring only, blocking off
 │     └─ pihole-FTL.db — the raw query log (the primary data)
 ├─ capture bridge — systemd timer, one tick per minute
 │     └─ read-only export of settled windows → private input directory
 └─ report app — FastAPI + Jinja, SQLite store
       ├─ shared dashboard   http://192.168.1.10:8787
       └─ owner dashboard    https://192.168.1.10:8789
```

Raw evidence, credentials, exports and backups live outside Git, in private `0700/0600` paths. See [current architecture](docs/reference/current-architecture.md) for the full component and data-flow description.

The addresses in the diagram are **documentation placeholders**. A real deployment will use your own router, relay host and VM addresses — see the [network policy contract](dns-pilot/network_policy.py) and the [bring-up runbook](docs/operations/household-bringup-runbook.md) for the values you are expected to change.

## Public release

The project is developed against a real household. Publishing it publicly means the code and its reasoning can be read by anyone while the household's data stays private. This repository is the sanitized half of that arrangement:

| Kind of material | In this repository | In the private repository |
| --- | --- | --- |
| Application, resolver, bridge, tooling, specs, runbooks | Full source | Full source |
| Household IP addresses, device addresses, MAC addresses | Replaced with documentation placeholders | Real values |
| Raw DNS query logs, snapshots, exports, backups | Never committed | Yes, in private `0700/0600` paths |
| Session handovers and internal transcripts | Removed; the feature ledgers in `specs/` keep the decisions | Yes |
| Campaign, report and snapshot identifiers | Replaced with synthetic examples | Real identifiers |
| TLS certificate fingerprints, credential paths, backup suffixes | Removed or masked | Real values |
| Credentials, API keys, owner passwords | Never committed | Yes, outside Git |

Everything in this repository is therefore safe to read, fork and discuss — but it is a **reference implementation**, not your running household. The specs, ledgers and runbooks describe what was built and why, with the household specifics removed.

**The private work continues there.** Live operation, campaign monitoring, capture windows and any change to the running system happen against the private repository and the live household, not here. Contributions to this public copy are made against synthetic fixtures; see [CONTRIBUTING.md](CONTRIBUTING.md).

## What it deliberately does not do

These are design decisions, not missing features:

- **No blocking, interception or router reconfiguration.** Blocking stays off, no endpoint agents, no debug modes, no household routing changes made by software.
- **No invented attribution.** On the router-forwarded path the requester appears as the router, so device and player attribution are reported as unknown.
- **No verdicts.** Counts are queries, not matches, players or intensity. First/last lookup times are not session boundaries.
- **No silent gaps.** A failed poll, a missing window or an unwritten interval is reported as a gap — absence is never presented as evidence.
- **No data leaving the host** except an explicitly confirmed, budget-limited research run of public text.

## Current status

Last updated **2026-11-05**. This is the recorded state of the private deployment this public copy was built from, not a live health check and not a claim about anyone's current network:

| Area | State |
| --- | --- |
| Offline implementation (feature 006, B1–B7) | **Accepted 2026-11-04** — 566 offline tests, lock/format/lint clean |
| L1 — matched release and network policy | **Verified** — both dashboards on one image ID, narrow binds, relay and guard proven |
| L2 — restart and reboot persistence | **Verified 2026-11-05** — VM and Proxmox reboots; no campaign activated by a reboot |
| Household resolver | **Restored and verified 2026-11-05** after router firmware reset the custom DNS setting |
| L3 — 72-hour campaign | **Running** — `camp-0123456789abcdef`, 2026-11-05 13:43Z → 2026-11-08 13:43Z, 7-day retention |
| T16–T17 — human acceptance | Pending — browser workflow from PC and phone |
| L4 — optional paid research | Not requested; separate gate, not required for completion |

A running campaign does not mean the observation is complete. L3 passes only when the first settled capture imports, freshness holds through the deadline, gaps are explicit and the frozen report plus exports agree. Read the [006 task ledger](specs/006-reliable-household-operation/tasks.md) before relying on any number here.

## Try it without a household

You do not need a Starlink connection, a Pi-hole or any real DNS data to run the application suite. Everything below is offline, synthetic and non-mutating:

```sh
git clone https://github.com/nawodyaishan/household-dns-insights-public.git
cd household-dns-insights-public

task help-contributors   # setup, checks and safety boundaries
task dev-setup           # locked environment + tracked pre-push hook
task quality             # lock, format, lint, offline tests
```

Prerequisites: Git, [Task](https://taskfile.dev/) (go-task ≥ 3), Python 3.13 and [uv](https://docs.astral.sh/uv/). Docker is optional and only used for explicitly requested synthetic container checks.

**Commands are capabilities, not permission.** Targets that deploy, collect, publish a dashboard, change network state or start a campaign have side effects and belong to documented, separately authorized gates. Never run `task campaign-benchmark` against an existing household image.

## Repository map

| Path | What lives there |
| --- | --- |
| [`destination-report/`](destination-report/README.md) | Report application, capture bridge, campaign tooling, development guide |
| [`dns-pilot/`](dns-pilot/OPERATIONS.md) | Monitoring-only resolver and its operational procedures |
| [`specs/`](specs/006-reliable-household-operation/spec.md) | Approved feature specs, plans and task ledgers (the decisions that survive sanitization) |
| [`docs/operations/`](docs/operations/household-bringup-runbook.md) | Bring-up, stack lifecycle and campaign runbooks |
| [`docs/reference/`](docs/reference/README.md) | Architecture and source-data inventory |
| [`docs/investigations/`](docs/investigations/README.md) | Historical Starlink capability and blocker research |

### Read next, by interest

- **How it works** → [current architecture](docs/reference/current-architecture.md), then the [safety and limits](#what-it-deliberately-does-not-do) above.
- **How it is run** → [household bring-up](docs/operations/household-bringup-runbook.md), [stack lifecycle](docs/operations/stack-lifecycle-runbook.md), [campaign runbook](docs/operations/005-campaign-runbook.md).
- **What was proven, and when** → the [R01–R18 acceptance packet](specs/006-reliable-household-operation/b7-acceptance-packet.md) and the [006 task ledger](specs/006-reliable-household-operation/tasks.md).
- **Why the edge cases are handled this way** → [investigation reports](docs/investigations/README.md) on what a stock Starlink router will and will not reveal.

## Contributing

Documentation, accessibility, privacy safeguards, synthetic tests and evidence-based reporting are all welcome — and none of them require household data. Start with [CONTRIBUTING.md](CONTRIBUTING.md); use invented domains and synthetic timestamps in every example, issue and screenshot.

**Licensing:** this repository has no license file yet. The owner must choose and add one before reuse, modification or redistribution permissions exist; do not assume an open-source license applies.
