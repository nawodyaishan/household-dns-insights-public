# Household report application

This directory contains the local application and host-side tools for bounded household DNS campaigns, gaming-related reports and optional evidence research. The current approved outcome and acceptance criteria are in [feature 006](../specs/006-reliable-household-operation/spec.md); its [task ledger](../specs/006-reliable-household-operation/tasks.md) is the source for implementation and live-gate status.

## Reporting and interpretation

Campaigns collect settled, bounded windows of DNS history through a host bridge. The application imports private evidence, tracks capture and coverage state, and generates frozen reports. Campaign-to-date, local-day and trailing 24/48-hour selections are clipped to the campaign and settled data; the older `/gaming` snapshot view is explicitly labelled as legacy and limited to one hour.

Reports distinguish reviewed associations from eligible saved model proposals, retain evidence and revision provenance, and expose matching page/CSV/JSON projections. Updating a report is an explicit local action: existing frozen reports are preserved. Exact-host human review is separate from model proposals; a generic CDN or provider label is not automatically a gaming association.

**A DNS lookup is not gameplay, a connection, an identified device or player, a session boundary or play time.** Alternative DNS paths and missing or expired data limit visibility. A lack of matching observations does not establish that no gaming occurred.

## Architecture and access

```text
Pi-hole → host capture bridge → private input → SQLite → report application
                         identity checks, gaps       ↘ optional owner research
```

The host bridge performs bounded source extraction; the browser-facing application container does not need the resolver database or Docker socket. The deployed 005-era environment and the planned 006 release are not interchangeable: check the [architecture and recorded deployment state](../docs/reference/current-architecture.md) before operations.

The shared LAN profile is deliberately accessible without a login over HTTP and cannot dispatch AI research. The owner profile uses TLS, authentication and CSRF protections. Treat anyone who can reach the shared profile as able to see its household data and use its allowed controls; LAN membership is not owner identity. Publication and network changes require separate approval.

## Optional research

Reports and ordinary refreshes, filters and exports do not require provider calls. Owner research is a separate preview-and-confirm workflow for bounded public candidates; it can return unknown and never discovers unobserved traffic. The worklist tracks reviewed, cached, researched, excluded and pending candidates. Paid mode requires disclosed tariffs and run/day ceilings, with a separate owner confirmation; unknown prices fail closed. The recorded 006 implementation supports paid ceilings via the legacy environment configuration path, **not** the operator JSON configuration path. No current model availability or pricing is guaranteed.

Keep credentials, observations, rules, reports and backups private. Never commit them or pass credentials through a browser. Read the [stack lifecycle runbook](../docs/operations/stack-lifecycle-runbook.md) and [campaign runbook](../docs/operations/005-campaign-runbook.md) for configuration, credentials and the effects of commands.

## Main components

| Path | Responsibility |
| --- | --- |
| `src/household_report/campaign.py` | Campaign lifecycle, bounded capture and source identity |
| `src/household_report/campaign_reporting.py` | Period selection, coverage and frozen campaign reports |
| `src/household_report/gaming.py` | Namespace associations and legacy gaming projection |
| `src/household_report/research.py`, `analysis.py` | Coverage/worklist and explicitly confirmed research jobs |
| `src/household_report/storage.py` | SQLite persistence and transactions |
| `src/household_report/web.py` | Dashboard routes and access controls |
| `tools/host_bridge.py`, `tools/campaign_cli.py` | Host-side capture and campaign control |
| `tools/stack_cli.py` | Explicit setup, lifecycle, maintenance and recovery commands |

See [current architecture](../docs/reference/current-architecture.md) for more detail and the [source-data inventory](../docs/reference/source-data-inventory.md) for evidence limits.

## Development and verification

Run from the repository root:

```sh
task help-contributors  # quick start and safety boundaries
task dev-setup   # locked development environment; also configures the Git hook
task quality     # lock, formatting, lint and offline tests
task check       # syntax, whitespace and private-file ignore checks
```

`task dev-setup` may download dependencies; the quality gate uses fake adapters and does not read live resolver data. `task runtime-check` requires Docker and uses synthetic inputs. See `task help` for other targets and their effects. The [006 task ledger](../specs/006-reliable-household-operation/tasks.md) records 552 offline tests at the T13 code state; those results are not a fresh test run.

See the [contributor guide](../CONTRIBUTING.md) for prerequisites, local checks and review expectations.

## Operational status and safety

As of 2026-11-02, 006 B1–B6 and T13 were implemented and offline-verified; T14's isolated release rehearsal and acceptance packet remain next. Review B4–B7 before any live work. Deployment, network migration, restart/reboot tests, a new 72-hour campaign and paid research each remain subject to their applicable separate live gates. A historical 18.591-hour campaign does not satisfy the 72-hour gate.

Use the [bring-up](../docs/operations/household-bringup-runbook.md), [lifecycle](../docs/operations/stack-lifecycle-runbook.md) and [campaign](../docs/operations/005-campaign-runbook.md) runbooks rather than copying old commands. Do not run `task campaign-benchmark` against the existing image identity without adapting it for an isolated rehearsal. Stopping the reporting stack is not a request to alter household DNS or routing.
