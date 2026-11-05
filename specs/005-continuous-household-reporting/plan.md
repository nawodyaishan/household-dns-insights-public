# 005 — Targeted household gaming observation — plan r2

> **Superseded statements (2026-11-02, note only).** Two inspection claims below
> are historical: the store is now schema **v7** (not v2), and a `.codegraph/`
> index exists. The command surface grew into the `stack-*` lifecycle documented
> in [`docs/operations/stack-lifecycle-runbook.md`](../../docs/operations/stack-lifecycle-runbook.md).
> The plan body and its approval record are left unchanged as evidence.

Input: [spec r2](spec.md). Approval is recorded only in [spec.md](spec.md#combined-approval). Approved for B1 offline implementation · 2026-10-24. Replaces plan r1; this plan alone does not authorize live operations.

## Approach and source alignment

Deliver one bounded campaign end to end in five reviewable batches. Reuse the existing Python/FastAPI/Jinja application, SQLite, export/import tools and Compose packaging. [MVP §§2–7/9](../../docs/project-scope/mvp-spec-v1.md), [source inventory](../../docs/reference/source-data-inventory.md) and [architecture](../../docs/reference/current-architecture.md) supply context; the spec's baseline qualifications take precedence over overstated historical descriptions. Local inspection confirms schema v2 and the existing manual exporter and auth boundary. No `.codegraph/` index exists; use targeted `rg` and file reads.

## D1 — Ownership and orchestration

The application owns campaign state and durable jobs in SQLite. The web route validates a request and records a job; it never executes a shell, accesses Docker or reads FTL. A single supervised **host bridge** uses a fixed application CLI inside the existing running container to claim typed work and record results. It executes the existing narrowly configured host-side extraction and asks the application CLI to import the completed artifact. No exposed admin HTTP endpoint, Docker socket mount or web-supplied shell is introduced.

The bridge's host service account already needs Docker access, which is privileged access in practice; do not describe it as a sandbox. Fixed operator configuration controls executable, container and database paths. A returned job supplies only validated IDs, UTC bounds and lease tokens. The bridge independently rejects out-of-campaign/unsettled/oversized windows and unrecognized operations. Artifact paths must stay inside the private input root, reject symlink/path traversal and use atomic writes. Sanitized status prints counts/bounds/IDs only.

Use a system-level systemd service/timer template running as the chosen non-root operator account, with Docker/network ordering, no interactive-login dependency and a host lock preventing overlapping ticks. Installation is explicit operator work. A tick runs at most 10 chunks or 10 minutes, whichever comes first; a 60-second timer checks for more work. Inactive campaigns produce no source reads. All subprocesses have deadlines. Unit behavior must be verified against the installed systemd version before installation. No user-linger assumption and no second independent import timer.

Application CLI and HTTP process may write concurrently: SQLite WAL, short transactions, `BEGIN IMMEDIATE`, busy timeout and atomic lease/claim transitions coordinate them. Container ownership alone is **not** a single-writer guarantee. Never hold a write transaction during FTL I/O or report rendering. Integration tests use separate connections/processes.

## D2 — Durable model and recovery

Add schema v3 through a tested v2 migration; preserve old snapshots, classifications and provider ledger. Proposed entities:

| Entity | Contract |
| --- | --- |
| Campaign | ID, UTC start/end, display timezone, pinned rules copy/hash, retention days, state and audited owner changes |
| Source generation | Operator-assigned resolver-generation identity and continuity evidence; reset uncertainty blocks cross-generation merging |
| Capture chunk / attempt | Campaign, half-open bounds, generation, attempt identity, settling/capture times, lease, artifact digest, import outcome, retry count and gap reason |
| Local job | Typed capture/report request, deduplication key, state, lease token/expiry, bounded retry policy, sanitized error |
| Frozen campaign report | Immutable payload/projection, requested and actual bounds, exact capture revisions, rule/result fingerprints, coverage, creation time and expiry |

Campaign states: active → finalizing → complete or complete-with-gaps; early finish changes the end and enters finalizing. A recoverable capture failure does not imply campaign failure. After the end, only finalization/backfill within original bounds is allowed until the spec's 24-hour allowance expires. Extension is owner-only while active and cannot exceed start + 120 hours; never extend an already completed campaign.

Store state before dispatch. Write evidence atomically, then import and acknowledge. A crash after file write is recovered by digest validation/import; a crash after import is recovered by idempotent acknowledgement. Stale workers cannot acknowledge a reassigned lease. Corrupt/conflicting existing artifacts are quarantined privately with an error, never overwritten. Check wall-clock validity before scheduling; backward jumps pause new work, forward jumps enforce original bounds. Report build cancellation/restart cannot alter a previously frozen result.

## D3 — Extraction identity, settling and coverage

Reuse `extraction_query()` and its single read-only statement. Keep source reads ≤3600 seconds even though report windows allow 120 hours. Permit a validated zero-row envelope with explicit successful-read metadata; update exporter, validator, importer and report contracts together. A zero-row result with unavailable retention context remains coverage-unknown, not certified empty history.

Plan prospective non-overlapping chunks clipped to start/end. Capture after the proposed 120-second grace; validate grace in B5 and expose delayed data rather than promise completeness. Preserve initial evidence. Permit a bounded reconciliation capture for recently completed chunks (one later pass, initially 10 minutes after initial capture) to detect late persistence; store it as a new revision. Frozen reports remain unchanged. Changed status/reply fields on the same identified query are revisions, not new queries; conflicting immutable fields trigger a provenance error.

Canonical identity is `(source_generation, source_query_id)`, with timestamp/immutable row fields as consistency checks. Never deduplicate by `(timestamp, domain, client, type)`: legitimate repeated queries may share those fields. Generation continuity requires a configured identity plus continuity checks; ID regression/reset or inconsistent overlap pauses import for operator resolution. No claim that every reset can be inferred from DNS rows alone. Legacy snapshots lacking generation identity remain readable in legacy views; exclude them from automatic campaign union unless explicitly reconciled by the owner. Prospective v1 does not need legacy backfill.

Coverage tracks acquisition separately from household visibility: scheduled, settling, captured, successful-empty, import-pending, failed/retryable, expired, partial and identity-unknown. Do not infer outages from quiet bins or oldest/newest rows alone. Catch up while source history remains retained; retries are bounded and resume by chunk status rather than a single high-water mark that skips failures. Full reports include unresolved intervals. Finalization deadline prevents infinite retry after campaign end.

## D4 — Frozen reporting and reviewed rules

Add a campaign report service rather than silently raising every legacy custom-window limit. Reuse gaming K/M predicates and allowlisted projection. Pin a validated private namespace file at campaign start; invalid/missing rules block readiness, while an owner-acknowledged valid-empty set is permitted and visibly labelled. Rule edits require an explicit new report revision; they never rewrite an older report. Saved eligible M results are optional and labelled; new provider calls are disabled.

Generate requests choose only campaign-to-date or an available local calendar day. The job captures an immutable requested end; eligible capture ends are bounded by campaign end and settling delay. It advances pending local work up to that end within a 10-minute report-job deadline, then produces a partial report with explicit pending/gaps or a clear failure if no trustworthy source state exists. No report with pending work claims complete coverage. A distinct successful-empty report is valid. Later requests can create a newer frozen report.

Use a deterministic key over campaign ID, requested bounds, selected capture revisions, coverage revision, rules hash, eligible saved-result fingerprint and interpretation version. Store the projection as a new report entity, not by forcing multiple snapshots into the old `reports.snapshot_id` foreign key. Same key reuses output. Export by immutable report ID; legacy live-view stale-fingerprint behavior remains unchanged. Counts and CSV/JSON derive from the exact saved projection. Local-calendar-day filters use timezone-aware boundaries clipped to UTC campaign bounds (including DST).

## D5 — Public LAN surface and protected owner controls

Add explicit `/household` campaign/report routes; retain existing `/`, `/gaming`, `/inventory`, diagnostics and analysis routes as authenticated owner surfaces. Public routes expose only active/unexpired campaign summaries, status, frozen gaming projection and its exports. Aggregate unknown/unmatched counts are allowed; unrelated browsing names, raw clients, provider usage and inventory are not. Opaque IDs are not authorization: enforce route-specific projection access on every fetch/export and deny expired reports even by direct ID.

Owner campaign controls use existing authentication/CSRF. Anonymous generation uses a short-lived signed same-origin token, strict Origin/Host checks, no permissive CORS, POST-only dispatch, global one-active-report admission and a small bounded queue (maximum 10). Equivalent requests coalesce; rate-limit per viewer plus globally and return 429 with retry guidance. No user-controlled SQL, file paths or free-form capture intervals. Escape labels, neutralize CSV formulas and preserve security headers. Test alternate route/export/diagnostic paths, not only the main page.

Keep local assets and Jinja with small JavaScript status polling. No React, CDN or Node runtime. Publish through an explicit LAN Compose override with configured bind address, allowed hosts, public origin and certificate SAN/trust. Keep loopback default intact. Document the actual path from household LAN to VM; do not assume the existing DNS relay publishes the app or automatically alter Proxmox routing. If new network configuration is required, present the concrete change separately for authorization.

## D6 — Provider boundary

005 is AI-off at application configuration, CLI/worker and route boundaries. Mount no provider secrets in the campaign profile; fail preflight if AI is enabled. Tests use adapters that fail on any provider invocation, including malicious direct POST attempts. Preserve legacy adapters, saved evidence and ledgers. Do not claim the current web preview enforces exact selected candidates or a per-job monotonic deadline: those are deferred repairs documented in MVP §5. Exa used by a coding agent for public documentation is separate from runtime household enrichment.

## D7 — Operations, retention and rollback

Extend Make with proposed `campaign-preflight`, `campaign-install`, `campaign-start DAYS=3 RETAIN_DAYS=7`, `campaign-status`, `campaign-report`, `campaign-stop`, `campaign-backup`, `campaign-retire` and `campaign-uninstall`. These targets do not exist today. Start/finish CLI and protected owner UI call the same application service. Preflight checks source/schema using only authorized reads, private paths, rules, time, Docker readiness, disk headroom and configured LAN origin. Separate an offline config check from a live readiness check so installation/build cannot silently read household data.

Expiry removes anonymous availability; explicit owner retirement removes campaign-owned artifacts/state after a backup/retention preview. Track ownership so shared legacy snapshots, rules/classification evidence and provider ledger are not accidentally deleted. Document that manually downloaded reports and backups cannot be revoked by server expiry; manage those copies separately. Do not change FTL's independent seven-day retention.

Keep existing container hardening and initially its 512 MiB/1 CPU limits. The project scope's VM proposal (1 vCPU/2 GiB/20 GiB) is only a starting budget. Measure five-day synthetic representative workloads and actual bounded operation; record peak memory, CPU, latency and storage growth. No GPU/local model or queue server. Bound logs and avoid raw-data logging.

Persist SQLite/WAL and inputs on local storage. Use SQLite backup API plus a manifest/digests for matching referenced artifacts; verify restore in isolation. Record campaign bounds/progress and namespace revisions in the backup. Recovery runbook covers Proxmox onboot, Ubuntu Docker/service startup, guest agent where appropriate, host power-restoration dependency and original deadline enforcement. Controlled restart checks need authorization; physical outage testing is unnecessary. DNS continuity/failover is excluded.

Rollback: disable bridge and campaign profile, retain private evidence, restore a tested pre-migration backup into an isolated compatible installation if needed. Do not claim old binaries accept v3 just because its changes are additive. Never silently downgrade a live database. Stopping the app removes report availability; finishing capture can leave final reports available until expiry.

## Specialist and tool assignments

No additional domain specialist is needed: existing Python/SQLite/Jinja patterns and repository guidance cover implementation. Installed `agentic-sdd-architecture-review` is assigned before B1 acceptance to scrutinize the host privilege boundary, public permissions, migration and retention; `agentic-sdd-verification-review` is assigned at each batch boundary. These are available skills, not invoked agents. No subagents are planned.

| Need | Conditional tool selection |
| --- | --- |
| Code and contracts | `rg`, targeted reads and local tests; CodeGraph only if an index later exists |
| Uncertain library/service behavior | Context7 if available for the installed version; otherwise primary documentation via Exa MCP or web, using generic queries only |
| Browser behavior | Available browser MCP if exposed; otherwise documented owner second-device checks. Do not assume disabled tools are available. |
| Verification | Focused offline tests, `make quality`; `make runtime-check` after runtime changes and final integration. No live data/provider calls in these gates. |

The existing public-source research in MVP §9 is reused; no new external factual question required research for this draft. Before live installation, verify systemd/Proxmox behavior against actual installed versions.

## Risks and evidence required

Main risks are source-identity ambiguity, late persistence, duplicate/replayed jobs, public-route leakage, privileged host-bridge misuse, incomplete restart behavior and storage growth. D1–D7 define mitigations, not proof. Batches test crash boundaries, two-connection SQLite contention, repeated identical-but-distinct queries, DST, empty/error distinctions, anonymous access and no-provider dispatch. B5 distinguishes offline packaging evidence, owner-authorized source/LAN/recovery checks and a completed real campaign. Clinical usefulness remains a separate research question, not an engineering acceptance claim.

## R3 access plan — approved for offline B5A

Input: [approved spec r3 access amendment](spec.md#r3-access-amendment--approved-for-offline-b5a). This replaces the D5 owner-versus-viewer boundary and the LAN HTTPS requirement **only** in the opt-in 005 profile; it does not revise the loopback owner profile, campaign evidence model, AI-off rule or independent live authorization.

1. Introduce an explicit, opt-in **LAN shared-control HTTP mode** in settings and Compose, pinned to one private VM bind and the same `http://IP:port` public origin/Host. Refuse wildcard, loopback and mismatched hosts; never make the default Compose profile anonymous. Remove campaign-profile TLS/owner-credential prerequisites only in this mode; do not weaken unrelated external HTTPS requirements or mount any credentials/provider configuration. Preserve the existing image isolation and private state/input mounts.
2. In `web.py`, make all **existing** web pages/API views and actions reachable without a login in shared-control mode; replace session-bound CSRF on state-changing forms with a mode-appropriate same-origin action token/nonce or equivalent browser-origin check that also rejects requests with missing or forged Origin where necessary. Keep body caps, exact Host, fetch-metadata checks, rate/queue bounds and no-provider dispatch. An attacker on the reachable LAN has the same UI power as any household visitor; these controls mitigate cross-site or accidental actions, **not** LAN identity or HTTP interception. Retain an explicit confirmation for campaign start/extend/early finish and other existing consequential browser actions. Remove login/logout links in shared mode without erasing them from the default profile. Host-only backup/retirement/install remain outside the browser, not silently elevated into public routes.
3. Update offline and packaged tests for the two independent profiles: passworded HTTPS loopback regression versus HTTP shared LAN without credentials. Exercise route/action matrix, direct requests, raw diagnostics/export visibility, hostile Host/Origin/fetch metadata, no Origin cases, login bypass attempts, confirmation, provider refusal, existing limits and exact port/config mounts. Update preflight and runbook to check the actual HTTP origin, absence of TLS dependency and absence of mounted secrets; keep `MODE=live` read-only and opt-in. Exercise Compose merge with one binding. Do not count synthetic requests as proof of LAN reachability or privacy.
4. Before any T16 execution, review the actual bind/port, accessible subnets, exposed raw data and actions, HTTP risks, owner/operator distinctions and recovery path with the owner. A second-device browser test determines whether `10.10.10.20` is routable from the household LAN; no router/Proxmox/firewall change is automatic. If unreachable, pause and ask for a separately approved narrow network remedy. Do not install/publish/start based solely on approval of this design.

Specialist addition for the r3 amendment: load the installed `backend-security-coder` for the trust-boundary and no-session action review; use `agentic-sdd-architecture-review` for the consequential access change and `agentic-sdd-verification-review` at the new batch boundary. Tools: targeted local discovery (no CodeGraph index), repository offline/runtime checks, Docker Compose config inspection, and a browser on a second household device **only when live access is separately authorized**. No extra subagents are planned. Principal failure mode is treating a host binding as an access-control guarantee or letting the HTTP path weaken the old loopback profile.

## R4 dashboard relay design — approved for offline B5B

Approval: the owner authorized this design for offline T20–T21 on 2026-10-26 (“approve the new batch”). Any “pending” or “draft” phrasing in the original design description below records its state **before** that decision; live root work and publication remain unauthorized.

Input: [pending r4 spec amendment](spec.md#r4-household-dashboard-relay-proposal--pending-combined-approval). The installed Pi-hole relay's `ip starlink_dns_pilot` table is owned by the DNS pilot; **do not** add a web rule to, replace or reinstall that table. The application is already capable of accepting a distinct public URL and exact allowed Host; `campaign_preflight.py::_origin` currently rejects `public URL IP != VM bind IP`. `Makefile` defaults also point to the inaccessible VM origin. Do not install the existing r3 profile unchanged and assume a new DNAT fixes the browser.

1. **Offline T20:** add an explicit relay-profile input to preflight and deployment settings; allow only VM bind `10.10.10.20:8787` paired with approved browser origin and sole Host `192.168.1.10:8787` when that relay profile is selected. Direct mode must still require bind = origin; unknown/blank/mismatched relay addresses, additional hosts/binds, public/WAN addresses and inconsistent Compose must fail. Keep the credential-free AI-off app, same-origin action checks, old loopback profile and host-only controls unchanged. Document both addresses and the private paths in the runbook. Re-run offline/profile/hostile Host and Origin tests and packaged runtime checks.
2. **Offline T21:** prepare a distinct marker-owned Proxmox nftables rule/table plus a dedicated systemd unit for **only** TCP/8787 from `wlo1`, source `192.168.1.0/24`, destination `192.168.1.10`, to `10.10.10.20:8787`, preserving source. No change to the DNS relay's existing 53/8443 policy, Starlink router, bridges or NAT for other services. A separate narrow VM-side ingress/forwarding guard must block unauthorized direct/proxy/container paths to this app port without changing Pi-hole protection or unrelated ports; design and verify its order relative to Docker, Tailscale and boot, with fail-closed behavior and an independent rollback. Preflight must refuse changed interface addresses, forwarding state, occupied relay port, unowned table/unit, or incompatible firewall state. Root helper supports print/check, explicit install/status/rollback, makes a private before-state backup and cannot broadly flush rules. Offline tests validate exact rule scope, both allowed and denied paths, independent rollback and DNS policy preservation; they do not claim live ACL proof.
3. **T16 continuation after combined r4 approval and separate concrete root/publication authorization:** owner reviews printed rules, source subnet/audience and rollback, confirms a household device for testing; on Proxmox the owner runs the reviewed helper, not the agent via implicit sudo. Apply the VM guard before LAN publication. Render exact Docker merge and run offline/live preflight against verified source generation; install bridge and publish only after all boundaries pass. Use the second device to visit `http://192.168.1.10:8787`, exercise existing pages/actions and observe permitted/denied path counters without dumping raw domains. Recheck DNS 53/8443, VM direct and nonhousehold paths, restart persistence and rollback isolation. Stop and undo dashboard-only exposure on failure; no automatic topology repair or household DNS cutover.

Technical architecture review verdict for this **draft**: **Needs changes before live application** (address mismatch, direct VM bypass paths and boot/firewall ordering are not handled by existing r3 code). The r4 design explicitly requires these offline corrections and proof; it is not a claim they are already implemented. The approved r2/r3 work does not authorize T20–T21 or Proxmox root execution. No new specialist exception: use the plan's backend-security guidance for the relay trust boundary and verification/architecture review at the amended batch checkpoint.
