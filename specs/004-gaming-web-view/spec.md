# Minimum local gaming DNS view — spec r2

Status: **draft for combined approval** · 2026-10-23.

## Outcome and revision boundary

Add an authenticated, server-rendered `/gaming` page for household DNS destination relevance, with reviewed namespace grouping, separately labelled saved model proposals, private CSV/JSON exports, local Exa MCP/Groq usage indicators and an explicit web analysis entry point. Retain Python/Jinja and existing local assets; no React, new service, dependency or schema migration.

Revision 2 applies the repository review and the owner's requests for usage indicators and web triggering. The owner authorized document changes, not implementation or a live provider run. Ordinary views remain offline; only an explicitly confirmed analysis can dispatch external work through the existing authorization and budget gates.

## Sources

- `../003/spec.md`, `../003/plan.md`, `../003/tasks.md`: grounding, bounded runs, accepted B3–B5 evidence and batch conventions.
- `../002-household-destination-report/spec.md`: reporting, privacy and explicit analysis boundaries.
- `../../destination-report/src/household_report/{classification,reporting,storage,web,app,settings}.py`: current contracts and composition.
- `../../destination-report/src/household_report/templates/report.html`, `../../destination-report/tools/import_inputs.py`, `../../destination-report/README.md`, `../../Makefile`: rendering, import, packaging and verification.

The earlier one-hour/82-row figure is supplied context, not a new runtime observation or acceptance fixture. No real 24/48-hour coverage is established here.

## Scope and decisions

- **AS1 resolved:** canonical location is `specs/004-gaming-web-view/{spec,plan,tasks}.md`; this set supersedes the attachment-named drafts in `specs/004/`.
- **AS2:** optional owner-reviewed `/input/gaming-namespaces.json`; no production rules supplied. An empty valid list is allowed and incomplete. The importer must exclude this exact filename.
- **AS3:** domain-summary exports, not raw rows; newest window by start time, not newest import time.
- **AS4 resolved:** the current category enum has no `gaming` value. Model-only eligibility is conservatively limited to a saved v2 grounded `gameplay_matchmaking` result. Other roles can be displayed for known-list entries but do not establish gaming relevance alone.
- **AS5:** use existing authentication, same-origin/CSRF protection, local ledger, analysis preview/confirmation and worker. No separate middleware or provider integration.

**OQ1 — Initial production rules:** owner supplies/reviews them locally later. Empty rules do not block synthetic acceptance; real usefulness remains unverified.

**OQ2 — Live provider setup:** indicators reflect locally configured provider state. Groq is not enabled or selected automatically; unavailable credentials/configuration keep triggering disabled. Any actual run requires a separate exact per-run authorization. No live run is part of acceptance.

## Acceptance criteria

All criteria are verifiable offline with synthetic inputs.

- **A1 — Frozen snapshot:** select the first `Store.snapshots()` entry (window start descending, then snapshot ID), and pass its explicit ID to reporting. Display identity, `[start,end)`, timezone and capture/import times. Pin filters/downloads/analysis preview to that snapshot. Later importing an older window must not change the default. No imports shows an empty state; unsupported widths over one hour or open bounds show an unavailable state with a sanitized reason, never silent fallback. No 24/48h/custom selector.
- **A2 — Namespace data:** validate versioned rules outside templates. Normalize case/trailing dot; exact wins, otherwise longest dot-boundary suffix. Reject conflicting equal-precedence rules and invalid/broad syntax; never substring-match. Missing/invalid lists are unavailable, not successful zero matches; valid empty lists are explicitly empty. Owner scope review does not prove ownership. Coexistence with snapshot import is tested without loosening snapshot validation.
- **A3 — Eligibility:** K is a reviewed namespace match. M is an exact-domain saved v2 `ai_grounded` result, displayed as `model_proposal`, with role exactly `gameplay_matchmaking`. Include K ∪ M once per domain and show independent list/model labels. Resolve newest completed v2 result first, including newer unknowns; never filter positive results before choosing the current result. Legacy v1 results do not independently select M. No free-text/category gaming inference. B5's downloads/updates result cannot independently select M but can be displayed if K matches. With empty rules and no qualifying M, the view is empty; this is not evidence of no gaming activity.
- **A4 — Groups and unknowns:** K supplies one game/platform group; platform matches never become specific games. M-only entries use “Model proposals — game unknown”. Saved service names remain proposals; disagreements stay visible. Distinguish not analyzed, unknown/rejected and provider association. Unknown/shared-infrastructure roles do not select M. Never promote a proposal into a reviewed rule.
- **A5 — Counts:** show domain and persisted-row counts for snapshot, eligible union and current selection; expose K/M overlap without double counting. Account separately for reverse/protocol namespaces and non-selected destinations. Recompute subset bins from preserved row identities; repeated rows remain counted. Show first/last query, DNS outcomes and saved role/evidence, never duration or play time. Empty bins mean no recorded queries.
- **A6 — Page:** basis/group/role filters, reset, link to `/`, wrapping domains, keyboard-accessible local details and readable 390px layout. Text distinguishes evidence bases and unknowns. Show “No destinations met the known-list or gameplay-matchmaking predicate” for an empty eligible union. No remote assets or evidence fetching.
- **A7 — Exports:** authenticated explicit CSV/JSON downloads use the same selected projection without a display prefix limit. Pin snapshot/list/result fingerprint; stale requests return HTTP 409 with an HTML reload message, not a download. Missing snapshot is 404; no snapshot means no export. JSON always includes metadata/limitations; empty CSV has headers only. Export fields and formula protection are defined in plan.md.
- **A8 — Offline reads:** views, refresh, filters, evidence expansion, usage display, exports, preview and synthetic import make zero provider/MCP/resolver/admin calls. Gaming read requests add no ledger attempts or classification writes. Only explicit final analysis confirmation may dispatch through existing gates; no automatic retry, reclassification or list promotion.
- **A9 — Household only:** page, projection and exports omit clients, device IDs and bindings, including with synthetic device bindings present. Pass an empty attribution mapping to suppress the callback. No inventory join; scope household/device unknown.
- **A10 — Privacy:** escape hostile labels/evidence; allowlisted exports omit credentials, paths, clients and raw provider bodies. Capture logs to prove new requests do not expose domains/evidence/request bodies. Domain-bearing selections travel in same-origin POST bodies. Preserve CSRF, origin, no-store and download headers. This is scoped to the new routes; existing `/` GET-search logging is not claimed fixed.
- **A11 — Compatibility:** `/`, import and existing analysis pass regression checks; missing/invalid rules do not disable general reporting or M. Non-editable packaging and synthetic runtime checks pass. Schema remains v2; no new dependency or service. Revert feature code and optional rules without deleting observations/results/ledger.
- **A12 — Usage indicators:** show separate Exa MCP and Groq cards from the app's local ledger, labelled “local recorded usage — not provider account totals”. Display explicit current UTC dispatch-day bounds and, when selected, a run's ID/status and usage. Separate Exa search/fetch/discovery and Groq catalog/probe/completion counts; exclude other providers from Groq counts. Show measured prompt/completion tokens separately from reservations/budget-charged usage; null measurements are unavailable, never zero. Show locally configured limits only with their actual scope; do not invent provider balances, dollar cost, rate-limit headroom or current connectivity. Include pending/failure counts and incomplete measurements. No account API or MCP health probe. OpenCode's own MCP usage is not in this ledger.
- **A13 — Web triggering:** an explicit “Review analysis candidates” action opens a local preview for the pinned snapshot using the existing candidate preparation rules, including eligible unresolved non-gaming destinations so an empty gaming list does not prevent investigation. Preview clearly lists the actual candidates/exclusions and does not imply it is limited to visible K ∪ M. The existing flow is snapshot-wide; do not silently substitute a selected-only scope. Require explicit confirmation of exact candidates, provider/model, disclosure and bounded run manifest, valid session/CSRF, enabled configuration and atomic budget reservation before dispatch. Reuse existing replay/idempotency/deadline behavior and status view. Reject stale previews without calls. An unavailable provider disables start with a reason. Synthetic fakes prove successful confirmation, disabled/budget-denied/stale cases and double submission. No live run is authorized by this document.

## Exclusions and limitations

No new collection, live resolver access, backfill, scheduled refresh, namespace crawler/editor, AI contract/schema change, network changes, LAN deployment or permanent service start. No private inventory copied into fixtures or commits. No raw-row export or general dashboard redesign. Production rules/evidence stay private.

DNS relevance cannot prove a connection, successful download/login, game launch, match, session, device/player identity or play time. Grounding is not independently verified activity. Neither predicate provides complete gaming detection; resolver retention is not imported coverage.

## Combined approval

**Approved** — owner approved spec r2, plan r2 and tasks r2, and authorized implementation of B1–B4 on 2026-10-23. The owner's instruction “proceed with all batches until finishing 004 all” authorizes continuation through all defined batches without intervening batch authorization. This does not authorize real external calls, deployment or data collection. Amendments: none recorded.
