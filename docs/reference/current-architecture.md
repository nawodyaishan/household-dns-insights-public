# Current architecture

Rewritten 2026-11-02 for feature 006 (reliable household operation). A deliberately simple description of the system as it exists **today** — the parts, what each one does, how data moves between them, and what is actually running. Supersedes the 2026-10-24 version, which described an undeployed schema-v2 single-writer app on Python 3.12.

For what each part can obtain, see [source-data-inventory.md](source-data-inventory.md).

---

## 1. The shape of it

```
Household devices
   │  (Wi-Fi / Ethernet, DNS pointed at the VM)
   ▼
★ Starlink router 192.168.1.1 ──► satellite dish 192.168.100.1 ──► space
   │        ▲
   │        │ gRPC :9000 — read-only inventory polls (on demand)
   │        │
   │   ┌────┴───────────────────────────────────┐
   │   │ Ubuntu VM 10.10.10.20 (Proxmox)        │
   │   │                                       │
   │   │  ★ DNS pilot container                │◄── read-only extraction, one
   │   │    starlink-dns-pilot (Pi-hole)       │    closed window at a time
   │   │    :53 LAN  :1053  :8443               │
   │   │    owns pihole-FTL.db — the DNS       │
   │   │    query log (the primary data)       │
   │   │                                       │
   │   │  ★ capture bridge (systemd timer)     │── identity preflight, bounded
   │   │    host_bridge.py, one tick/minute    │    export → import, heartbeat
   │   │           │                           │    status file (0644)
   │   │           ▼                           │
   │   │  ┌──────────────────────────────┐     │
   │   │  │ private input directory      │     │   0700, outside the repository
   │   │  │ ~/.local/share/household-    │     │
   │   │  │   report/input               │     │
   │   │  └───────────┬──────────────────┘     │
   │   │              │ import (idempotent; bridge + CLI are the writers)
   │   │              ▼                        │
   │   │  ┌──────────────────────────────┐     │
   │   │  │ ★ report application         │     │
   │   │  │   container household-report │     │
   │   │  │   FastAPI/Starlette + Jinja  │     │
   │   │  │   profiles: loopback 8787 /  │     │
   │   │  │   shared LAN 8787 / owner    │     │
   │   │  │   https 8789                 │     │
   │   │  │   state: app.sqlite3 (v7)    │     │
   │   │  └───────────┬──────────────────┘     │
   │   │              │                        │
   │   │  ★ stack driver (tools/stack_cli.py)  │── setup/check/start/status/
   │   │    typed lifecycle over one runner    │   stop/restart/upgrade/rollback/
   │   │                                       │   backup/restore/uninstall
   │   └───────┬───────────────┬───────────────┘
   └───────────┼───────────────┘
               │ LAN relays on the Proxmox host (separately owned units)
               ▼
   shared http://192.168.1.10:8787   owner https://192.168.1.10:8789
```

★ = the components that matter. Everything else is a helper.

---

## 2. Components

### 2.1 DNS pilot — the collector in production

| | |
| --- | --- |
| What | A Pi-hole container (`pihole/pihole:2026.10.0`) that answers every household DNS query and logs it in `pihole-FTL.db`. |
| Where | Container `starlink-dns-pilot` on the Ubuntu VM `10.10.10.20`; published on `10.10.10.20:53`, loopback `127.0.0.1:1053`, admin `:8443`. |
| Produces | The household's DNS query history: names, timestamps, client addresses, status codes. |
| Status | **Running and healthy** since 2026-10-22. |
| Boundary | Monitoring only. Blocking is off, upstreams are standard, and no household routing or topology change is performed by this project. |

### 2.2 Starlink router / dish — a secondary, bounded source

| | |
| --- | --- |
| What | The ISP router's own gRPC API. The router (`192.168.1.1:9000`) answers client-inventory calls; the dish (`192.168.100.1:9200`) exposes health/management services. |
| Used for | Client inventory only, via `wifi_get_clients`, and only when the owner runs a poll. |
| Status | `get_connections` returns `UNIMPLEMENTED`, `wifi_get_firewall` returns `PERMISSION_DENIED` — no bypass is attempted. |
| Boundary | Read-only diagnostics. The router's configuration, DNS, firewall and routing are never changed by this project. |

### 2.3 Host tools — the bridge between "live" and "stored"

| Tool | Purpose | Output |
| --- | --- | --- |
| `host_bridge.py` | One bounded capture tick: identity preflight (`source-check`), export of a settled window, import, durable sanitized heartbeat. Latches on identity/config mismatch until corrected or `--retry-check`. | `bridge-status.json` (0644, atomically replaced) + imported rows |
| `campaign_cli.py` | Typed campaign control/worker: start/finish/finalize/status/report, `source-check`, `bridge-status`. | Sanitized JSON only |
| `export_snapshot.py` | Extract one closed ≤1 h window from the resolver with a single read-only statement. | `snapshot-<start>-<end>.json`, append-only, `0600` |
| `poll_presence.py` | Sample the router's client inventory N times at a fixed interval. | `presence-<utc>-<nn>.json` envelopes, failures recorded as failures |
| `import_inputs.py` | Validate and import exported files into the store, idempotently. | Rows in `app.sqlite3` |
| `stack_cli.py` | Typed operator driver for the whole lifecycle (`setup … uninstall`); every external effect is one allowlisted argument array through one runner. | Sanitized JSON result |
| `campaign_benchmark.py` | Synthetic 120-hour campaign/recovery rehearsal in a private directory. | Benchmark report, no household data |

All run on the host as an unprivileged user (the bridge unit is explicitly non-root), read only, and print counts and digests — never names, addresses or payloads.

### 2.4 The report application — the only user-facing surface

| | |
| --- | --- |
| What | A Python 3.13 / FastAPI(Starlette) + Jinja service in one non-root Docker container. |
| Where | `household-report` container. Three profiles: **loopback** `127.0.0.1:8787` (self-signed TLS), **shared LAN** `http://192.168.1.10:8787` (no credentials, cannot dispatch AI), **owner** `https://192.168.1.10:8789` (TLS, password, CSRF, AI-capable). |
| Reads | The private input directory (read-only mount) and the private state directory (writable). |
| Never | Reads the resolver, holds the Docker socket, uses host networking, or has an administrative credential. |
| Status | **Deployed by feature 005** — shared `10.10.10.20:8787` and owner `0.0.0.0:8789` (the wildcard bind and the historical manual 8789 DNAT rule are exactly what 006 replaces at gate L1 with the reviewed single-VM-bind manifest). |

**Routes** (owner profile adds the owner-only ones; shared control is refused for them)

| Route | Purpose |
| --- | --- |
| `/login`, `/logout` | Single owner password, session key, CSRF and same-origin protections |
| `/household` | Default destination: campaign-aware summary with period selector (campaign-to-date / local day / 24 h / 48 h, clipped to settled data with requested-vs-actual bounds) |
| `/household/generate` | Explicit local "generate (updated) report": freezes the current evidence/rules into an immutable revision with predecessor lineage |
| `/household/reports/{id}`, `/export.{csv,json}` | Saved frozen reports; page and exports use the same projection, filters and counts |
| `/household/owner`, `/household/owner/review` | Owner-only: collector status, exact-host association review with evidence/revision provenance (refuses shared control) |
| `/gaming` | Labelled legacy one-hour snapshot view, linked to the campaign summary |
| `/` | Destinations report with Windows (24 h / 48 h / custom) and local filters |
| `/inventory` | Device inventory and presence timeline from stored polls |
| `/analysis`, `/analysis/preview`, `/analysis/coverage`, `/analyses`, `/analysis/{id}` | Optional research: local coverage/worklist read model, preview → confirm → budgeted run, status/resume/reanalyze |
| `/diagnostics/*`, `/healthz` | Local report/analysis JSON and liveness |

### 2.5 The store — one SQLite file

`app.sqlite3` (**schema version 7**) in the private state directory. The bridge/campaign CLI and the application container are the two writers; the maintenance lock quiesces both for backup/migration.

| Group | Tables |
| --- | --- |
| Evidence | `snapshots`, `dns_rows`, `campaign_queries`, `source_generations`, `capture_chunks`, `capture_attempts`, `campaign_capture_revisions` |
| Reports | `reports`, `frozen_reports` (immutable, with `revision`/`predecessor_report_id` lineage), `campaign_job_results`, `campaign_rules_revisions`, `campaign_retirements` |
| Rules/classification | `classifications` (reviewed + grounded proposals with evidence spans) |
| Research | `analyses`, `analysis_items`, `call_attempts` (the usage ledger: reserved vs measured tokens, request/token/exa/currency ceilings) |
| Campaigns | `campaigns`, `campaign_owner_events`, `local_jobs` |
| Inventory | `inventory_polls`, `device_settings`, `device_bindings` |

Migrations are explicit and idempotent (`PRAGMA user_version`); a database newer than the application is refused, and rollback across an incompatible schema must go through a verified isolated restore — never an in-place downgrade.

### 2.6 Releases, maintenance and recovery

| | |
| --- | --- |
| Identity | One `ReleaseManifest` (image ID, source revision, lock/base/host-bundle digests, schema version). Tags are labels; both dashboards must run the manifest's image ID — a mixed pair is never "upgraded". |
| Setup | `task stack-setup CONFIG=…` validates the operator JSON, prepares private 0700 paths, renders the bridge units and writes a `stack-prepared.json` bound to a digest of the exact configuration. No install, publication, capture or research. |
| Upgrade/rollback | A six-stage maintenance journal (`stop-bridge → stop-writers → backup → migrate → recreate → check`) under an exclusive lock; recorded before each stage, so an interruption is resumable and never presents one old/one new instance as success. |
| Backup/restore | Consistent SQLite + artifact backup with a manifest (digests, schema, release, campaign deadlines), verified on read. Restore targets an **empty private directory only**; production promotion is a separate owner operation. |
| Uninstall | Preview first; removes only owned publication (compose project, rendered units). Evidence, configuration, images, backups and DNS are retained. |

### 2.7 Integrations — the optional, budgeted edge

`src/household_report/integrations/` holds the provider adapters (`openai_compatible` covering OpenRouter/Groq/OpenAI/Mistral-compatible endpoints, `exa_mcp`), reached through two small ports declared in `contracts.py` (`ModelProvider`, `EvidenceClient`). Every call passes the **dispatch gate**: an exact approved candidate set, numerical per-operation caps, an atomic budget reservation against `call_attempts` (token, request, Exa-operation and, in paid mode, currency ceilings — all in one `BEGIN IMMEDIATE` transaction), a monotonic deadline, no retries on refusal, and strict validation of the grounded citation before anything is stored.

Fresh configuration is AI-off with spend disabled. Paid mode requires owner-set tariffs and per-run/UTC-day currency ceilings that fail closed at load and at reservation; the analysis page discloses them per run. The models are *proposals*: they never enter the reviewed rule set without exact-host human review, and nothing leaves the host without an explicit per-run confirmation.

### 2.8 Repository gates

`task quality` = lock check + format check + lint + the offline suite (**552 tests** at the 2026-11-02 baseline; fake adapters, real SQLite, in-process only). `task runtime-check` = synthetic checks against the packaged container. `task dashboard-relay-check` = relay/guard/network-contract tests. `task dns-check` = resolver compose/guard/sampler contracts. `task campaign-benchmark` = the synthetic 120-hour rehearsal. The tracked pre-push hook runs the offline gate. All are non-mutating and offline: no downloads, no auto-fix, no network, no resolver access.

---

## 3. Running state (as recorded by the 006 plan inventory, 2026-11-01; not re-checked in this session)

| Piece | State |
| --- | --- |
| DNS pilot container | **up, healthy** — logging household queries |
| Application | **Deployed (005-era)**: shared `10.10.10.20:8787` and owner `0.0.0.0:8789`; the installed VM guard is still the 4-drop v1 and the 8789 DNAT rule is the historical manual one — 006 migrates both at gate L1 |
| Capture bridge / campaign | Installed bridge captured **one completed campaign (18.591 elapsed hours)**; last capture/import `2026-10-31 09:06 UTC`; **no active campaign** — the three-day 72-hour campaign is gate L3 |
| Store | 19 snapshots, 115,873 DNS rows, 17 classification rules, five analyses (two completed, two partial, one failed), two frozen reports (73 chunk records: 19 imported, 54 expired) |
| Provider credentials | One owner-configured AI run happened in 005 (see the [005 task ledger](../../specs/005-continuous-household-reporting/tasks.md)); 006 keeps AI-off by default and any real paid run behind gate L4 |
| Feature state | 006 B1–B6 implemented and offline-verified; B7 (rehearsal + acceptance packet) in progress; review of B4–B7 happens once at the B7 packet |

---

## 4. Design rules the system follows

1. **The app never touches the resolver.** Evidence moves host → private file → import. The container cannot query the resolver even if it wanted to.
2. **Two writers, one lock.** The application container and the bridge/CLI write the same store; migrations and backups run under an exclusive maintenance lock with both writers quiesced.
3. **Read-only everywhere.** No configuration change to the resolver, the router or the household; blocking stays off.
4. **Local by default.** Nothing leaves the host except an explicitly confirmed, budget-capped run of public text.
5. **Absence is not evidence.** Missing windows, failed polls and unwritten gaps are reported as gaps; a name was *queried*, not *used*.
6. **Append-only evidence.** Exported files are never overwritten; re-imports are idempotent; frozen reports gain revisions, never edits; deletions are owner decisions.
7. **Claims are narrower than the data.** No play time, no sessions, no device attribution of DNS queries, no complete visibility.
8. **Specification before change.** New behaviour starts as a spec, plan and task set with one combined approval; live operations need their own authorization (gates L1–L4).
9. **Identity is never rebound silently.** Source generation/identity mismatches fail closed and latch until an explicit correction or retry-check.
10. **One explicit configuration path.** The operator JSON (or the legacy environment, never both) drives the stack; contradictory mixed paths are refused.

---

## 5. Known gaps

| Gap | Consequence | Where it is being addressed |
| --- | --- | --- |
| 005-era publication diverges from the approved policy | Owner bind is `0.0.0.0:8789`, the 8789 DNAT rule is a historical manual entry, and the installed VM guard is the 4-drop v1 | Gate L1 applies the reviewed 006 manifest (single VM bind, owned 8789 table/unit, six-drop guard) with backups and independent rollback |
| No live 006 restart/reboot evidence | Persistence across reboot is claimed only where tested | Gate L2 |
| Only one short historical campaign (18.591 h) | Collection reliability is proven synthetically (120-hour benchmark), not through a live 72-hour run | Gate L3 |
| No live AI validation under 006 | Mistral readiness/prices are documented, not exercised | Gate L4 (optional; not required for completion) |
| Operator-config spend policy not wired | Paid-mode ceilings live in the legacy environment path only | Recorded in 006 tasks; extend on owner request |
| Presence is sampled only on demand | No continuous per-device periods | Deliberate: presence is optional and on-demand |
| No cleanup of old windows | Private directories grow indefinitely | Owner decision; retirement/backup are explicit owner commands |
