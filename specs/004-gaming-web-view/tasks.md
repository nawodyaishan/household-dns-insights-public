# Minimum local gaming DNS view — tasks r2

Inputs: [spec r2](spec.md), [plan r2](plan.md) · 2026-10-23. Single approval: [spec.md#combined-approval](spec.md#combined-approval). **B1–B4 authorized by owner on 2026-10-23.** Shared specialist/tool assignments are in plan.md; no task-specific exceptions.

## Revision checkpoint

Owner requested application of the 004 review, then added Exa MCP/Groq usage indicators and web triggering. Revision 2 resolves canonical filenames, current model eligibility, mandatory importer exclusion and read-model precision. It retains server rendering and adds a separate interaction batch. On 2026-10-23 the owner approved the document set and explicitly authorized all batches through completion. The prior one-hour/82-row figure is supplied context, not newly verified evidence. No live run or data collection occurred for this revision.

## Ordered tasks

| ID | Change and evidence | Dependency | Criteria |
| --- | --- | --- | --- |
| T00 | Recheck repository instructions and referenced contracts; confirm rules loader, installed assets, ledger/provider/outcome semantics and existing exact-manifest confirmation. Record production rule usefulness as unverified. Stop dependent work on material authorization/schema drift. | Combined approval + B1 authorization | A1–A3, A11–A13 |
| T01 | Rules schema/validation/matching and mandatory exact filename exclusion in `tools/import_inputs.py`. Synthetic rules import without snapshot attempts; invalid actual snapshots still fail. | T00 | A2, A10, A11 |
| T02 | Pure allowlisted gaming projection: pinned snapshot, K/M/group/role semantics, current-result first-wins including newer unknown, attribution suppression, counts/bins/fingerprint. Clarify store read docstring if touched. | T01 | A1, A3–A5, A8, A9 |
| T03 | Read-model regressions including later-imported older snapshot, unsupported bounds, empty/list-unavailable, v1 exclusion, overlap and no client fields. B1 quality checks. | T02 | A1–A5, A8–A11 |
| T04 | Authenticated server-rendered page, local filters/details, navigation, responsive unknown states and fingerprint refusal. Preserve `/`. | B1 review + B2 authorization | A1, A4–A6, A8–A11 |
| T05 | Read-only local usage aggregation/cards with explicit UTC/run scope, provider isolation, outcome breakdown, measured versus reserved/charged tokens and missing-measurement handling. Test mixed providers/days and unchanged ledger. B2 quality and synthetic viewport/keyboard checks. | T04 | A6, A8–A12 |
| T06 | Local snapshot-wide review-candidates action using existing preview preparation; label actual scope, including unresolved non-gaming candidates. Reuse final exact-manifest confirmation, CSRF/token/reservation/idempotency/status path. No direct dispatch from page or preview. | B2 review + B3 authorization | A8, A10, A13 |
| T07 | Synthetic fake-adapter tests for disabled configuration, stale preview, budget denial, confirmed bounded execution and duplicate submit/replay. Distinguish permitted synthetic confirmation writes from read-only requests. B3 quality checks. | T06 | A8, A10–A13 |
| T08 | Shared allowlisted CSV/JSON exports with stale HTML 409, empty semantics, attachment/no-store headers and formula protection. Page/export selection equality. | B3 review + B4 authorization | A7–A10 |
| T09 | Full quality and synthetic installed/runtime checks; README setup, usage semantics, analysis disclosure/scope, limitations and rollback. Record actual evidence and gaps; stop disposable runtime. | T08 | A1–A13 |

## Batches and review stops

### B1 — Rules and gaming read model (T00–T03)

State: **complete**. T00–T03 implemented: versioned rules validation/matching, exact importer exclusion, pinned one-hour read model, first-wins current analysis inherited from the existing report, separate K/M predicates, client-free selected timeline and fingerprint. Verification: focused gaming tests (8) and import tool tests (17) passed; `make quality` passed (276 offline tests, lock/format/lint). One pre-existing Starlette/httpx deprecation warning appeared. No household database, namespace list, resolver, provider or MCP was read/called. Continue to B2 under the owner's full-scope authorization.

### B2 — Page and local usage indicators (T04–T05)

State: **complete**. T04–T05 implemented: authenticated `/gaming`, POST/CSRF filters, no client fields, responsive server-rendered groups/evidence/timeline, empty/unavailable states, and Exa/Groq usage aggregation from the local SQLite ledger with provider/outcome/token-measurement separation. Focused gaming route and storage usage tests passed; `make quality` passed (279 offline tests, lock/format/lint). Ordinary view/filter usage left the ledger unchanged; no provider/MCP call. Browser viewport tooling was unavailable; CSS uses the existing responsive breakpoint and keyboard-native forms/details. Continue to B3 under full-scope authorization.

### B3 — Explicit web analysis entry (T06–T07)

State: **complete**. T06–T07 implemented: authenticated explicit action opens the snapshot-wide preview, includes unresolved non-gaming candidates, and passes a gaming-origin scope that suppresses device-attribution lookup on preview/confirmation. Existing rebuilt preview token, CSRF, enabled-provider, atomic reservation, worker, replay/idempotency, and status paths remain in use. Synthetic fake-runner test confirms the preview performs no call, final confirmation submits the exact full-window candidate set, and no attribution lookup or attempt ledger write occurs in the synthetic runner path. Existing analysis tests cover disabled provider, stale/tampered token, budget denial, bounded execution, and replay/idempotency; `make quality` passed (283 offline tests). No real provider calls. Continue B4 under full-scope authorization.

### B4 — Exports and packaged acceptance (T08–T09)

State: **complete**. T08–T09 implemented: POST/CSRF CSV and JSON exports share the page's predicates/order, use a strict allowlist, include pinned snapshot/rules/fingerprint/filter metadata, return 409 HTML on stale state and 404 on missing snapshots, and are private no-store attachments. CSV neutralizes formula-leading values; empty CSV has headers only. Synthetic tests prove page/export selection equality and omission of client/raw-row fields. `make quality` passed (284 offline tests; lock/format/lint); synthetic `make runtime-check` passed (3 container checks). README covers rules setup, ledger semantics, export limits and analysis scope. Pre-existing Starlette/httpx deprecation warning remains. No real provider, Exa MCP, resolver or household evidence was used. No migration or dependency added.

## Continuation

Current state: spec/plan/tasks r2 approved; B1–B4 complete and verified. `make quality` (284 offline tests) and synthetic `make runtime-check` (3 container checks) pass; browser viewport tooling unavailable, so responsive CSS/native keyboard controls were verified by implementation and in-process tests, not headed-browser automation. No real external calls, data collection or deployment occurred. Owner separately requested commit and push after all batches; proceed with the requested Git workflow. Any future real external analysis still requires its exact per-run authorization through the existing flow.
