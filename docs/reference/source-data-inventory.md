# Source data inventory

Written 2026-10-24. Every source this project can draw on: **what it holds, how it is obtained, when it is available, and what it cannot show.** Counts are aggregate and dated; names, addresses, MACs and credentials stay in the private directories.

Vocabulary: `CONFIRMED` (observed working), `NOT OBSERVED` (bounded test found no such feed), `ACCESS DENIED` (the call was refused), `UNKNOWN` (not established either way).

---

## 1. Summary map

| ID | Source | Status | Granularity | Availability |
| --- | --- | --- | --- | --- |
| S1 | Pi-hole FTL query log (household DNS) | CONFIRMED (live) | One row per DNS query, with client address and timestamp | Continuously, since 2026-10-22 17:51 UTC |
| S2 | FTL volume backup | CONFIRMED (one snapshot) | Full resolver configuration + database | On demand; one archived snapshot from 2026-10-22 17:56 UTC |
| S3 | Aggregate observation sampler | CONFIRMED | Counts per 15-minute window, no names | While the sampler runs; it is not running now |
| S4 | Router client inventory (`wifi_get_clients`) | CONFIRMED | One record per associated client, per poll | On demand only (bounded polls) |
| S5 | Reflected gRPC schemas (router + dish) | CONFIRMED (captured) | Interface definitions | Captured once; re-capturable |
| S6 | Router/dish runtime read calls | NOT OBSERVED / ACCESS DENIED | — | `get_connections` → UNIMPLEMENTED; `wifi_get_firewall` → PERMISSION_DENIED |
| S7 | Exported snapshot evidence files | CONFIRMED (one window) | Full query rows for one closed hour | Only the hours actually exported |
| S8 | Imported application database | NOT CREATED | — | The app has never run; the store holds nothing |
| S9 | Private validation run evidence (T16 / B3 / B4) | CONFIRMED | One window, provider requests/responses, ledgers | Frozen historical artifacts |
| S10 | Gaming namespace inventory (private, deterministic) | CONFIRMED (file set) | Namespaces derived from observed names | Static file set, refreshable offline |
| S11 | Generated destination reports (HTML/JSON) | CONFIRMED | One report per produced run | Static artifacts |
| S12 | Provider side: Groq / OpenRouter / Exa MCP | CONDITIONAL | Model completions, public search excerpts | Only under an explicit per-run authorization |
| S13 | Host static facts (`PRIVATE_RAW.json`) | CONFIRMED | OS and checker results | One-shot |
| S14 | Repository documents and specs | CONFIRMED (tracked) | Design intent, acceptance criteria, task history | In the repository |
| S15 | Starlink router/dish hardware inventory | CONFIRMED (one snapshot) | 11 records (10 clients + 1 controller) | Point-in-time only |

---

## 2. The primary source: household DNS queries (S1)

**What it is.** The Pi-hole `pihole-FTL` SQLite database inside the `starlink-dns-pilot` container. One row per DNS query with query timestamp, queried name, client address, query type, response status, reply type, EDE, DNSSEC flag and reply time.

**How it is obtained.** Read-only, host-side, on demand:

```
task snapshot-export START=<epoch> END=<epoch>
# = uv run --project destination-report python destination-report/tools/export_snapshot.py \
#      --input-dir ~/.local/share/household-report/input --start … --end …
```

The tool runs exactly one statement through `docker exec … pihole-FTL sqlite3 /etc/pihole/pihole-FTL.db "PRAGMA query_only=ON; …"`. It refuses to write a window that is not closed (≥60 s old) or is wider than one hour, never overwrites an existing file, and prints only counts, bounds and a digest.

**When it is available.** Continuously, since the DNS cutover on 2026-10-22 (~17:51 UTC), because the pilot logs every query it serves. Read at 2026-10-24 00:31 UTC the log held **130,101 query rows** spanning **30 h 40 min**, **3,457 distinct queried names**, and **5 distinct client addresses**. Latency: the newest row was current to within a second of the read.

**What it cannot show.** No packet contents, no page content, no transport success beyond the resolver's own status codes, no application-level activity, no play time, no per-application attribution. A name was *queried*; that does not prove the connection was made, the download happened, the game launched, or anyone was at the keyboard.

**Sensitivity.** High. It contains the complete household browsing history by name. Never printed in conversation, never exported unredacted, never sent to a provider. The exported file and the resolver database are both git-ignored.

**Availability caveat.** Coverage depends on the resolver being up and on clients using it. Wired and wireless devices that bypass the resolver (hard-coded DNS, DoH) leave no row; the pilot is configured for the Starlink custom-DNS setup, not as an enforced network-wide sinkhole.

---

## 3. Resolver configuration backup (S2)

**What it is.** A full archive of the Pi-hole container's configuration and database volume.

**How.** `PRIVATE_DNS_BACKUPS/20261022T175608Z/` — `etc-pihole.tar.gz` plus a `metadata.json` recording the image digest, the volume name and the method ("service stopped, full volume archive").

**When.** Created on demand at a deliberate stop point; restoring it is a service-stopping operation and is owner-run.

**Value.** Recovery path for the pilot; also a frozen point-in-time copy of the household's DNS history and configuration, useful for before/after comparison of any future change.

---

## 4. Aggregate observation sampler (S3)

**What it is.** `dns-pilot/observe_queries.py` writing one JSON object per sample to `PRIVATE_OBSERVATION/samples.jsonl`: query totals, distinct-name counts, response-status histogram, resolver database size, oldest/newest row times and **per-client query counts**.

**How.** `task dns-observe` (one sample), `task dns-observe-start` (48 hours at 900-second intervals), `task dns-review` (print the recent rows).

**When.** Only while the loop is running. The 2026-10-22 run is finished; `samples.jsonl` holds that run's history.

**What it cannot show.** No names, so it cannot answer "what was queried"; only volume, shape and health. It has a **client-address dimension**, so the file is private even though it is name-free.

---

## 5. Router client inventory (S4)

**What it is.** Per-poll records of the clients the Starlink router reports: identifiers, addresses, interface type (e.g. `ETH`/`WIFI`), rates, byte counters, booleans such as `active`. Router gRPC endpoint `192.168.1.1:9000`, service `SpaceX.API.Device.Device/Handle`, call `{"wifi_get_clients":{}}`.

**How.**

```
task presence-poll COUNT=9 INTERVAL=15
# = uv run --project destination-report python destination-report/tools/poll_presence.py \
#      --input-dir ~/.local/share/household-report/input --count 9 --interval 15
```

Each sample spawns one short-lived `fullstorydev/grpcurl:v1.9.3` container with host networking and writes an envelope file (`presence-<UTC>-<nn>.json`) into the private input directory. The importer validates these envelopes unchanged and stores them in `inventory_polls`.

**When.** On demand only; there is no continuous presence sampler yet (that is the subject of the drafted 005 feature). Nine samples at 15 s were taken on 2026-10-22; failed samples are stored as failures, never as absence.

**What it cannot show — verified limits.** From [`STARLINK-DESTINATIONS-AND-PRESENCE-REPORT.md`](../investigations/STARLINK-DESTINATIONS-AND-PRESENCE-REPORT.md):

- `CONFIRMED`: client records are retrievable.
- `UNKNOWN`: whether a client staying listed means "still connected", and for how long a disconnected client lingers in the listing.
- `UNKNOWN`: whether the `active` flag means anything beyond a transient association signal — it flipped intermittently on two clients and correlated with nothing observable.
- **No connection transition was ever observed**, so transition detection remains unvalidated.
- Wired clients may never appear in a Wi-Fi client listing, so absence proves nothing about them.
- Presence is *network association*, not OS uptime, not human presence, not application activity.

**Sensitivity.** Highest in the project: identifiers, addresses and MAC-adjacent fields. Excluded from every export by default.

---

## 6. Reflected router/dish schemas (S5) and refused runtime calls (S6)

**What exists.** `PRIVATE_INVESTIGATION/` holds 41 captured artefacts: reflected protobuf message/service definitions for the router and the dish (`Request`, `Response`, `EventLog`, `UXEvent`, `WifiClient`, `GetConnections*`, `WifiGetClients*`, `WifiGetFirewall*`, `WifiGetHistory*`), plus the responses of the calls that were actually attempted.

**How.** `investigate_readonly.py` (bounded, read-only) drives `grpcurl` against the router and dish and writes each raw envelope to `PRIVATE_INVESTIGATION/`.

**When.** Captured 2026-10-22/23; re-capturable at any time. gRPC reflection is enabled on both endpoints.

**Runtime results (bounded, 2026-10-23):**

| Call | Endpoint | Result | Verdict |
| --- | --- | --- | --- |
| `get_connections` | router and dish | gRPC `UNIMPLEMENTED` | NOT OBSERVED |
| `wifi_get_firewall` | router | gRPC `PERMISSION_DENIED` | ACCESS DENIED — no bypass attempted |
| `get_log` (broad syslog) | router | never invoked | Deliberately excluded (broad dump) |

`WifiGetHistoryResponse` contains resolver-health counters (drop rate), **not** query names. Reflected fields such as service-address maps and seconds-since-success counters do **not** establish household traffic: they may describe router/dish management connections. Provenance for those fields is **UNKNOWN**.

---

## 7. Exported snapshot evidence (S7)

**What it is.** One JSON file per exported closed hour, holding that hour's query rows, plus window bounds, a row count and a data digest.

**How.** `tools/export_snapshot.py` (see S1), then `tools/import_inputs.py` to copy rows into the application store, or `task snapshot-export` + `task app-import`.

**When.** Only for hours the owner actually exported. Today exactly one window has been exported and imported (the T16 window, 82 rows); the private input directory on this host does not yet exist.

**Limit.** Evidence coverage is *exported* coverage, which is far smaller than *logged* coverage. Nothing in the dashboard may imply otherwise.

---

## 8. The application store (S8)

**What it is.** `app.sqlite3` with the schema of `src/household_report/storage.py` (currently version 2): `snapshots`, `dns_rows`, `reports`, `classifications`, `analyses`, `analysis_items`, `call_attempts`, `inventory_polls`, `device_settings`, `device_bindings`.

**How.** Written only by the application container (single-writer rule) through `tools/import_inputs.py`; read by the dashboard and the exporters.

**When.** **Not created.** The application has never been packaged or deployed on this host: no owner password, TLS material, private input directory or state directory exist. Only the Groq and Exa credential files are present.

**Limit.** Everything the dashboard has ever shown came from the private validation databases (S9) or the static report files (S11), not from a live store.

---

## 9. Private validation evidence (S9)

**What it is.** The frozen artifacts behind the accepted 003/004 work:

| Directory | Contents |
| --- | --- |
| `t16-2026-10-23/` | The first imported window (82 rows), the T16 report, selection and replay scripts, one saved model result that validated as `unknown` |
| `b3-2026-10-23/` | The 2026-10-23 single authorized run: one Exa search (5 public sources), one catalog probe, one completion — result rejected by the then-broken contract; raw request/response bodies and an isolated database |
| `b4-2026-10-23/` | The post-fix re-run under the same envelope: result accepted (`ai_grounded`, `downloads_updates` role, two supporting spans, one cache rule) |
| `gaming-inventory-2026-10-23/` | Deterministic namespace inventory built from observed names (no AI verification), review candidates and next candidates |

**When.** Frozen history. The B4 run is the only accepted grounded model result in existence; there is **no grounded `gameplay_matchmaking` result**, so the model half of the `/gaming` eligibility predicate is empty.

**Value.** Replayable proof of what the system did, what it cost and why it rejected a result. This is the audit trail a clinician, reviewer or auditor would ask for.

---

## 10. Gaming namespace inventory (S10)

**What it is.** A private, deterministic list of namespaces (service and platform groupings) derived from names observed in the household data — *not* AI verification and *not* proof of gameplay.

**How.** `PRIVATE_DESTINATION_REPORT_VALIDATION/gaming-inventory-2026-10-23/` (inventory build script, summary, candidate lists).

**When.** Regenerable offline from imported rows; the reviewed, owner-usable form is the optional private `gaming-namespaces.json` in the application's input directory, which the importer excludes by name.

**Limit.** A namespace list is a *list of names*. It says nothing about play time, participation, or which device did the querying.

---

## 11. Generated reports (S11)

**What it is.** HTML/JSON destination reports produced by the reporting module for the one available window, in three variants (proof of concept, produced report, reviewed report) under `PRIVATE_DESTINATION_REPORTS/`, each with `observations.json`, `classifications.json`, `report.json`, `report.html` and a mobile preview image.

**When.** Regenerable from the store; the checked copies are static snapshots of a single hour.

---

## 12. Provider side (S12) — conditional and budgeted

**What it is.** Groq (model completions), OpenRouter (alternative provider), Exa MCP (bounded public web search/fetch). Implementations live in `src/household_report/integrations/`.

**How.** Only through the existing analysis flow: candidate preparation -> preview -> explicit confirmation of an exact manifest -> atomic budget reservation -> dispatch -> validated result. Credential files: `~/.config/starlink-monitoring/destination-report/{groq-api-key,exa-api-key,exa-mcp.json}` (mode `0600`, outside the repository); a local `.env.local` may override the Groq key.

**When.** Never automatically. A run needs its own exact manifest (candidate set, provider/model, numerical caps for search/fetch/discovery/catalog/probe/completion, token ceiling, deadline). Prior authorizations are spent and never reused.

**Measured reality from the accepted runs.** Two authorized runs total (B3 and B4): each used 1 catalog call, 1 Exa search and 1 completion; reserved 131,584 tokens; measured 3,367 + 245 (B3) and 3,409 + 231 (B4) prompt/completion tokens; elapsed ~6 s and ~9 s. Zero-call replays after both runs added zero attempts.

**Limits.** The usage counters in the UI are *local ledger aggregates*, never provider account totals, balances, costs or rate-limit headroom.

---

## 13. Host static facts (S13) and hardware inventory (S15)

**S13.** `PRIVATE_RAW.json` — `started`, `os`, `checks` from the one-shot read-only host inspection. Fixed snapshot of the VM.

**S15.** The 11-record Starlink inventory (10 clients + 1 controller) captured in the original probe: per-client interface type, uplink/downlink rates and byte counters. Point-in-time; several records carried empty detailed statistics and two all-zero throughput arrays, so the accounting period was never established. Eight Wi-Fi clients had populated byte counters.

---

## 14. Repository documents (S14)

Tracked, sanitized and public-safe:

| Document | What it gives a future session |
| --- | --- |
| `specs/001-dns-monitoring-pilot/` | The authorized DFS pilot: scope, plan, tasks, cutover evidence |
| `specs/002-household-destination-report/` | The report product: privacy, budget, isolation requirements |
| `specs/003/` | Grounded gaming roles, deterministic citations, budget gates (B1–B5 accepted) |
| `specs/004-gaming-web-view/` | The `/gaming` view, usage indicators, exports, analysis entry (B1–B4 accepted) |
| `specs/005-continuous-household-reporting/` | **Draft**: continuous collection, window-scoped gaming view, continuous presence (awaiting approval) |
| [`STARLINK-DESTINATIONS-AND-PRESENCE-REPORT.md`](../investigations/STARLINK-DESTINATIONS-AND-PRESENCE-REPORT.md) | Historical capability and campaign evidence |
| [`REPORT.md`](../../REPORT.md), [blocker research](../investigations/STARLINK-BLOCKERS-RESEARCH-REPORT.md) | Earlier investigation and blocker analysis |
| `README.md`, `destination-report/README.md`, `dns-pilot/OPERATIONS.md` | Topology, commands, operations, recovery |

**Note.** `docs/future_work/` holds brainstorming transcripts, not specifications. Their marketing sections contain unverified claims (contributor counts, compliance alignment, testing claims) and must never be reused as fact.

---

## 15. Coverage matrix — what each source can answer

| Question | S1 | S2 | S3 | S4 | S6 | S12 |
| --- | --- | --- | --- | --- | --- | --- |
| Which names were queried? | **Yes** | copy | counts only | no | no | no |
| When exactly? | **Yes** (per row) | copy | 15-min buckets | poll-level only | no | no |
| Which client address issued them? | **Yes** (column exists) | copy | counts only | inventory only | no | no |
| Which *device* issued them? | Only via the address | copy | no | mapping only, unproven | no | no |
| How long was something used? | **No** | copy | no | no (transitions unvalidated) | no | no |
| Was a connection successful? | Resolver status only | copy | status histogram | no | no | no |
| Remote IP/port activity? | **No** | no | no | no | NOT OBSERVED | no |
| Firewall rules / DNS history? | n/a | snapshot | no | no | ACCESS DENIED / NOT OBSERVED | no |
| Was a game actually played? | **No** | no | no | no | no | role proposal only |

**Net reading.** The household's DNS *names and times* are available with confidence (S1). A device's *presence* is observable with a bounded, unvalidated link to connection state (S4). Everything else — sessions, durations, gameplay, remote addresses — is unavailable from this setup, and no amount of aggregation of S1 will produce it.

---

## 16. Practical notes for a future session

- **What to read first:** this file, then the relevant `specs/<nnn>/tasks.md` continuation paragraph.
- **What to re-verify before trusting:** the resolver row count and uptime (`task dns-health`), the store contents (does `app.sqlite3` exist yet?), the presence sampler's reachability, and the countdown of the 005 batches.
- **What never to do:** print query names, client addresses, MACs or provider bodies into a conversation, a tracked file or an external prompt; widen a read-only probe into a broad dump; change router, DNS, firewall, DHCP or routing to make a feature work; reuse a spent provider authorization.
- **Where new evidence goes:** `PRIVATE_*` directories and the private input/state directories outside the repository. Nothing new belongs in a tracked file except sanitized summaries like this one.
