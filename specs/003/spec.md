# Gaming destination evidence and grounding — spec r2

## Outcome, sources and revision boundary

**Next-phase goal:** Make existing gaming-related DNS observations inspectable by destination role, with reproducible source grounding, explicit unknowns, and an optional live classification check under a separately approved per-run budget.

This is a follow-on to 002, not a replacement for its approved requirements. The existing `specs/003/` directory is the feature location. The owner approved the r2 planning set and authorized offline B1 implementation; B2 requires a separate batch authorization and B3 requires its own exact run authorization.

Sources supplied for this draft:

| Source | Repository reference / supplied filename | Use |
| --- | --- | --- |
| S1 | `../002-household-destination-report/spec.md`, r3, acceptance A1–A19 and Combined approval | Existing product, privacy, budget and isolation requirements |
| S2 | `../002-household-destination-report/plan.md`, r3, module map and operational gates | Existing module boundaries, contracts, persistence and tooling |
| S3 | `../002-household-destination-report/tasks.md`, r3, T14–T16 and B4 | Implementation records and T15/T16 evidence |
| S4 | `../../doc/handover/2026-10-23-1708Z-destination-report-b4.md` | Latest supplied operational checkpoint and unresolved items |
| S5 | `../../README.md` | Resolver topology, commands and documented limitations |

Evidence status: S4 reports a packaged but stopped household app, AI off, a running Pi-hole pilot, 253 passing offline tests, three earlier container checks, one actual-domain job returning `unknown`, and successful network-disabled replay. B1 reran the offline quality gate at the current code state (259 tests); earlier container checks were not repeated. Its separate evidence review supports a downloads/updates role; it did not change the automated result. The private gaming inventory uses deterministic namespace rules, not AI verification or proof of gameplay. B1 inspected the local T16 files and app contracts at HEAD `bdc5168`; it made no provider call, live resolver read or secret read.

Resolve historical contradictions by keeping dated records and using the explicit T16 completion record/S4 for this baseline. Older claims that no app or external calls exist are historical. Current HEAD differs from the handover HEAD because documentation was updated subsequently; S1/S3 still record no B4 owner acceptance. Do not backfill approvals or claim the app is deployed.

**Explicit assumptions**

- **AS1 — Phase identity:** retain the user-supplied `specs/003/` directory and the feature title above; do not create a parallel slugged feature or overwrite other work.
- **AS2 — Priority:** improve gaming endpoint roles and grounding before expanding collection, providers or deployment. This follows the latest gaming goal and T16 failure; it remains the proposed scope.
- **AS3 — Reuse:** the named modules exist on disk; T00 must inspect their contracts and actual behavior before modifying them.
- **AS4 — Evidence availability:** the private saved T16 bundle and gaming inventory directories exist. File readability, contents and completeness must be checked without external calls during authorized implementation.
- **AS5 — Public disclosure interpretation:** only an owner-selected, explicitly approved public namespace and public source excerpts may be sent externally, as in 002. This is not blanket permission to disclose names derived from household history. Until OQ2 is resolved for a run, use local evidence only.

**Explicit open questions**

| ID | Question | Default / effect if unresolved |
| --- | --- | --- |
| OQ1 | Has the owner accepted 002 B4, and what is the complete local T16 evidence set, including the rejected response if retained? | S3 still says pending review; verify locally in T00 and ask the owner for acceptance rather than infer it. Record missing artifacts. Do not push, rewrite history or re-create missing model output. |
| OQ2 | Does the owner permit one exact public candidate derived from observations to leave the host, or should this phase remain entirely offline? | No candidate disclosure or external call until an exact per-run authorization is recorded. Private rows, identities and timing never leave. |
| OQ3 | Which candidate, evidence mode, provider/model and numerical per-run limits are authorized for the optional validation? | No live run. Prefer the same T16 candidate for comparison, but do not select or substitute it automatically. |
| OQ4 | Does the implementation enforce search-only, fetch, discovery and provider limits separately? S3 records a deferred Exa search-only sub-cap. | Verify offline; repair a missing gate before any optional live run. Do not claim the deferred cap is implemented. |
| OQ5 | Which bounded excerpts, links and request/response artifacts actually reached T16, and why did its quote differ? | Diagnose locally; do not assume prompt wording alone explains it or make a diagnostic network call. |
| OQ6 | Do saved imports contain raw rows and sufficient coverage for the requested report period? | Use only verified imports; aggregate inventories cannot reconstruct raw rows or full 24/48-hour coverage. No new exports or polling in this phase. |

## Actors and privacy boundary

One authenticated local owner inspects saved reports and evidence and, optionally, authorizes one bounded classification run. The implementer works locally within the approved batch. Existing server-side configuration and secret-file handling remain in place; no credential discovery, copying or permission changes are part of this phase.

Private data remains on the host: raw DNS observations, counts/times linked to candidates, client identifiers, device inventory, private/tenant/tokenized labels, reports, local paths, credentials and full diagnostic bodies. Tracked docs/tests use synthetic fixtures and sanitized descriptions; actual candidate names and evidence are referenced through local private artifacts, not copied into commits or external prompts by default.

The only conditional external payload is the public material enumerated in an approved run manifest (OQ2/OQ3). Display that payload locally before confirmation. Reject a candidate if making it public would disclose a private identifier; reducing a name must also reduce its permitted claim scope. Raw household data is never a model input. Retrieved sources are untrusted data, not instructions. The model receives no tools or credentials. Ordinary reporting, preview and replay perform no external calls.

## Acceptance criteria

### Local observations and reporting

- **A1 — Recorded baseline:** identify the existing T16 job, source/evidence hashes when available, rejection reason, saved result, ledger totals and cache state without altering them. Record missing artifacts and the distinction between reported and reverified facts. Old T16 remains `unknown` in its immutable record.
- **A2 — Gaming-role inspection:** use the existing report view to distinguish local namespace hints, provider associations, source-grounded model proposals, separately reviewed mappings and unknowns. Roles may include downloads/updates, launcher, authentication, telemetry, discovery/connectivity, gameplay/matchmaking and shared infrastructure; assign a specific role only when evidence supports it. Discord/Twitch or a publisher namespace alone do not establish a particular game or endpoint function.
- **A3 — Observation integrity:** retain every imported row, fixed `[start,end)` bounds, source identities, DNS outcomes and first/last query times. Count role/classification coverage over both distinct domains and DNS rows with explicit denominators. Preserve unknown/excluded/reverse observations. Show actual available coverage and gaps; deterministic inventory matches are not complete gaming coverage.
- **A4 — Meaning:** label all observations as household DNS queries. No device attribution, inferred gameplay, transport success, connection/session counts or play time. A download endpoint observation does not prove a download occurred; a discovery endpoint does not prove participation in a match.

### Bounded external classification

- **A5 — Reproducible grounding:** add deterministic source-span references, or an equivalently strict mechanism verified offline, so accepted evidence quotations come from the exact bounded text supplied to the model. Unknown source/span IDs, cross-candidate references, changed text, truncation and unsupported quotations remain rejected. No fuzzy quote repair or silent validator relaxation.
- **A6 — Semantic support:** exact text matching establishes citation integrity, not truth of a role. Validate field scope and evidence relevance separately; provider ownership cannot justify gameplay/matchmaking. Keep model proposals distinguishable from human-reviewed mappings. Missing role evidence yields a broader supported association or `unknown`, with a reason.
- **A7 — Versioned results:** preserve original evidence, analyses, cache versions and charges. New policy/schema versions create explicit new revisions only on authorized commands. Views do not reclassify saved reports. Cache replay and identical confirmation must not create external attempts; failed grounding creates no successful mapping.
- **A8 — Budget gates:** every external run requires an exact approved candidate set and numerical limits for discovery, catalog/probe/completion, search/fetch, tokens, retries and duration. Reserve through the existing ledger before dispatch; zero allowance means zero calls. Count ambiguous outcomes and attempts, distinguish actual usage from reservation, and never describe a token reservation as a bill or an Exa monetary cap. Repair any missing relevant operation-specific gate before use (OQ4).
- **A9 — Offline-first validation:** reproduce the known rejection from saved material if available and demonstrate valid-citation and invalid-citation cases with synthetic fixtures. Also test verbatim-but-irrelevant evidence, shared-CDN ambiguity and invented gameplay/device claims. Test success is not measured live-model accuracy. No model request is needed to implement these checks.
- **A10 — Optional live check:** after separate run authorization, exercise at most the approved work in an isolated application DB/container. Save observed outcomes and usage; keep `unknown` if validation fails. A completed HTTP/job path is not classification success. Demonstrate unchanged-repeat zero-call replay and ordinary AI-off reporting. No automatic retry or household AI enablement follows any result.

### Inventory and attribution

- **A11 — No attribution:** all destination views in this phase remain household-level even if existing inventory contains a matching IP or name. Do not enable device DNS filters, binding imports or attribution by timing, rules or AI.
- **A12 — Existing inventory boundary:** the existing separate device view may remain usable, but no device categorization expansion, prospective polls, backfilled presence or identity research is included. A gaming-domain inventory is a list of names, not a device inventory.

### Availability and deployment boundary

- **A13 — Isolation:** no changes to resolver/router/firewall/DHCP/DNS/NAT, retention, sampler or collection schedule; no service restart for this feature. Use existing saved inputs and separate private application state. No live Pi-hole DB migration/mount, Docker socket, host networking, LAN exposure or permanent app start. Existing loopback packaging may be tested only within its authorized batch; household AI remains off.
- **A14 — Maintainability and verification:** extend existing feature modules, two integration ports, one SQLite store, templates and locked uv/Ruff/Lefthook path. No new service, agent loop or database server. Run the existing offline quality gate plus focused grounding, accounting, immutable-replay and UI tests. Runtime checks remain explicit and separate; document actual results rather than importing historic test counts as new passes.

## Exclusions

New traffic/connection capture; device attribution or agents; play-time inference; automatic domain research or model calls; new collectors/exports or 24/48-hour reconstruction; provider/model benchmarking; a second research backend; fuzzy quote acceptance; unbudgeted repair calls; migration or removal of original private evidence; DNS/filtering/network changes; reboot testing; broad application deployment; automatic commits/pushes; and any claim of complete gaming visibility or guaranteed classifier accuracy.

## Combined approval

Decision: **approved for offline B1 implementation**. Actor: repository owner. Date: 2026-10-23. Evidence: conversation instruction, “use sdd skills and proced with specs/003.” Reviewed scope: spec r2, plan r2 and tasks r2 as present at that instruction. This authorizes the documented offline B1 work; it does not authorize external provider calls, live network changes, B2 execution or an optional B3 run.

This is the single combined document-approval record for phase 003. Batch execution authorizations and post-batch reviews belong in `tasks.md` as continuation evidence: execute and verify one batch, then stop for human review before starting the next, even if the original authorization mentions both. B3 always requires an explicit per-run budget and public-disclosure decision; prior T15/T16 authorization is spent and does not authorize another run. If B3 is declined, record it as not executed and accept/reject the offline outcome separately. No phase-002 acceptance, push permission or runtime authorization is inferred from this decision.
