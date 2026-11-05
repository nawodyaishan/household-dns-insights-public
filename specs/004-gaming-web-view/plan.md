# Minimum local gaming DNS view — plan r2

Input: [spec r2](spec.md). Status: **draft** · 2026-10-23. Single approval: [spec.md#combined-approval](spec.md#combined-approval).

## Architecture

Retain Python/Jinja and local assets. Snapshot + current exact-domain analyses + reviewed rules → pure `gaming.py` projection → page/CSV/JSON. `reporting.py` composes the projection from existing snapshot reads; the dependency remains one-way (`reporting → gaming`, `gaming` standalone) to satisfy the tested module boundary. The usage panel is a separate local read model. Analysis entry reuses the existing snapshot-wide preview/confirmation/worker, never dispatches from a report read and never implies visible gaming entries are the complete analysis scope.

### Verified integration points

- `Store.snapshots()` orders by window start descending then ID. Explicit `snapshot_id` prevents overlapping snapshots entering the report.
- `ReportService.report(attributions={})` suppresses its callback; `None` does not. Its full report still contains client information, so use a fresh allowlisted projection rather than passing that report to the template/export.
- `latest_analysis_results()` returns all qualifying completed v2 rows newest-first; `build_report` selects the first usable model result per domain. Preserve newer unknowns and the ordering `created_utc DESC, analysis_id DESC, item_id`; clarify the misleading store docstring if touched. Test newer unknown versus older positive explicitly.
- Current category schema has no `gaming`; M uses v2 grounded `gameplay_matchmaking` only. Do not expand classification contracts.
- `tools/import_inputs.py::_snapshot_files()` takes every non-presence `*.json`. Excluding exactly `gaming-namespaces.json` is mandatory.
- Existing `/analysis/preview` and `/analyses` rebuild a snapshot-wide preview and validate its token. Reuse this scope, not a new selected-domain dispatcher.
- `Store.budget_usage()` mixes providers at day scope and budget charges can include reserved tokens. It is not a provider-specific measured-token report. Add a narrow read aggregation rather than relabeling those totals as Groq usage.

## Affected modules

| Component | Work |
| --- | --- |
| `gaming.py` | Pure rule validation/matching, K/M selection, grouping, counts, subset timeline and fingerprint |
| `reporting.py` | Pinned-snapshot orchestration into the pure gaming projection, with attribution suppressed |
| `storage.py` | Existing reads; narrow read-only ledger summary joined to analyses for provider identity; no schema change |
| `web.py` | Authenticated GET/POST `/gaming`, POST exports, read-only usage context and guarded analysis-preview entry; reuse existing final confirmation |
| `templates/gaming.html`, base/static assets | Navigation, responsive groups/details, indicators and analysis action; keep `/` behavior |
| composition/settings | Optional rules loaded from existing read-only input directory; inject read services without provider capability |
| `tools/import_inputs.py` | Exact reserved-filename exclusion, preserving invalid-snapshot failure |
| existing analysis templates/service, only as needed | Reuse exact manifest/confirmation/status contracts; do not bypass authorization or add direct provider calls |
| offline/runtime tests and README | Synthetic coverage, packaging and owner setup/limitations |

## Rules contract

Optional `/input/gaming-namespaces.json`, host `HR_INPUT_DIR`, private mode 0600. List: `schema_version=1`, owner `revision`, `rules`; SHA-256 of bytes; maximum 256 KiB and 1,000 rules. Rule: unique `rule_id`, `namespace`, `match` (`exact`/`suffix`), `group_id`, `group_label`, `group_kind` (`game`/`platform`), nonempty `review_note`. Bound identifiers/text and require consistent group labels/kinds. Reject URL/wildcard/IP/reverse/protocol/single-label entries and ambiguous equal-precedence rules. Owner excludes public-suffix/shared-provider roots; syntax alone cannot establish ownership or detect every broad suffix. No new public-suffix dependency.

Load once per request; reject the whole invalid list with a sanitized reason. No stale fallback, watcher or automatic inventory conversion. Distinguish empty from unavailable. Track schema documentation and reserved-domain synthetic examples only.

## Snapshot, selection and provenance

Pin newest-by-start ID, enforce closed ≤1h bounds and display explicit unavailable state for unsupported data. Later filters/imports do not replace the selected snapshot. Pass `attributions={}`; omit client fields even from the intermediate gaming projection.

Basis all/list/model means K ∪ M/K/M; group and role filters combine with AND. K determines the display group; M-only is game unknown. Role filters use current saved results, absent/rejected as unknown. Six specific roles may be displayed on K entries; only gameplay/matchmaking independently selects M. Sort descending persisted-row count then stable group ID/domain. Account separately for reverse/protocol exclusions.

Read source inputs once per request. Fingerprint snapshot period digest, rules bytes/status, relevant current analysis identities/payloads and interpretation version. Exclude generation time and usage-ledger counters: unrelated provider work must not invalidate an export. Filter/export POSTs carry expected fingerprint; mismatch is HTML 409 with reload, missing snapshot 404. No silent substitution. Recompute selected timeline from preserved row identities, not household totals.

## Usage read model and web analysis action

Aggregate ledger attempts for current UTC `dispatch_day` and optional explicitly selected run, joined with `analyses.provider`. Define counts as recorded reservations/attempts, with outcome breakdown so pending/refused/failed are not presented as completed remote calls. Preserve the existing chargeable-outcome accounting for budget totals. Split Exa search/fetch/discovery from provider catalog/probe/completion. Groq panel filters provider exactly; show other configured providers truthfully without attributing their tokens to Groq. Exa totals are app-wide for the labelled period, not Groq-specific.

Return measured prompt/completion sums plus measurement completeness/missing counts, reserved tokens and budget-charged tokens as separate fields. Unknown is unavailable. Limits retain their configured global/day/run scope; show no Groq-specific remaining quota derived from a global budget. Provider enabled/disabled is local configuration, not a health claim. Never return candidate bodies, provider error bodies or secrets. Usage refresh is explicit page refresh; no external monitoring loop.

“Review analysis candidates” submits snapshot ID and fingerprint with CSRF to a local preview entry. Validate freshness, then reuse snapshot-wide candidate preparation. This includes unresolved non-selected destinations and states that scope clearly. No network work during preview. Final confirmation must use the existing server-rebuilt token, disclosure/manifest, enabled-provider checks, budget reservation and idempotency path. Reuse status/history; retain the snapshot return context without domain-bearing URLs. Never start on GET or on merely opening `/gaming`. Do not automatically enable Groq, switch provider or read external account quotas. If existing confirmation cannot enforce the specified exact manifest, stop the dependent task and amend the plan before changing authorization semantics.

## Export contract

One row per selected normalized domain: domain, group ID/label/kind, query count, first/last UTC query, independent known-list/model-selection flags, rule ID, saved state/role/proposed service, safe unknown-reason code, analysis ID/date, household scope/device unknown. JSON metadata and repeated CSV columns carry export schema version, snapshot ID/bounds, timezone, namespace revision/hash, fingerprint and selected filters. JSON also includes counts/coverage, qtype/status/reply distributions and limitations. Empty CSV is headers only; JSON retains metadata. Omit clients, raw rows, filesystem paths, credentials and evidence bodies. Quote CSV and neutralize formula-triggering cells including whitespace/control prefixes. Same projection/order as page; no display cap truncation. Usage is shown on the page, not mixed into domain exports.

## Security, recovery and verification

Reuse auth, origin/CSRF, no-store, escaped Jinja output and local assets. New requests must not log domains, evidence or bodies. Existing `/` GET-search behavior is outside this guarantee. Model citations expand locally without fetching. Page reads leave ledger/results unchanged; only explicitly confirmed synthetic analysis tests may write synthetic attempts/results.

No schema migration or new dependency. Roll back code and optional rule file without deleting observations/analyses/ledger. Any unexpected migration or authorization redesign requires amendment. Ordinary requests remain offline; actual implementation acceptance uses fakes only and authorizes zero real external calls.

No additional specialist needed for document revision; repository contracts suffice. For implementation use installed `backend-security-coder` guidance for the new triggering boundary and `ui-ux-designer` for server-rendered interaction/accessibility, loaded in the main agent only when relevant. No subagents. Use CodeGraph MCP only if indexed (currently unavailable for this repository), otherwise targeted local tools. Use Context7 MCP for specific library API questions with public generic queries only; no private evidence. Use an available browser for synthetic viewport/keyboard checks; no installation or external asset loading. Do not confuse development-tool MCP calls with application Exa ledger usage.

Tests: exact/suffix adversarial rules; mandatory importer exclusion plus invalid snapshot; overlapping windows and later-imported older window; unavailable widths; K/M union and newer unknown; attribution suppression; selected bins; page/export equivalence; stale fingerprint; hostile text/CSV/log capture; mixed-provider/day/outcome/token completeness; disabled/stale/denied/confirmed/replayed analysis using no-call fakes; non-editable resources and loopback runtime. Run focused checks and `make quality` at batch boundaries; `make runtime-check` for final acceptance. Missing offline prerequisites are gaps, not passes. No inherited test counts. Stop disposable previews afterward.
