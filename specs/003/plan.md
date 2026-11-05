# Gaming destination evidence and grounding — plan r2

Input: `spec.md` r2. Single approval record: `spec.md#combined-approval`. This phase extends the existing modular monolith; it does not rebuild 002. All assumptions AS1–AS5 and open questions OQ1–OQ6 are defined in the spec. The owner authorized offline B1 implementation; external access and optional B3 spending remain separately gated.

## Validated evidence and decision

The supplied T16 record reports successful Exa/Groq execution, a rejected quotation, an immutable `unknown` item, no new cache rule, and zero-call replay with networking disabled. It reports 1,717 prompt plus 272 completion tokens, against a 2,048 completion cap and a 133,120-token internal reservation. Those are historical measurements, not next-run settings or pricing guarantees.

The handover reports a separate public-source review supporting installer/content delivery. That establishes a useful diagnostic target; it does not prove the exact model-visible excerpt contained the needed wording or that a prompt-only change will solve the issue (OQ5). The private gaming inventory's namespace matches provide a shortlist, not validated endpoint roles. Suggested discovery/connectivity candidates remain hypotheses.

**Proposed decision:** inspect and reproduce the failure locally, make citation selection deterministic while preserving semantic uncertainty, surface the result in the existing report, and offer one optional budgeted validation. No new collection or attribution capability is necessary for this slice (AS2).

### Historical extraction probe

002 reports a tested one-statement read-only SQLite export and a bounded API pagination problem; do not reopen that investigation. This phase consumes saved inputs only. The aggregate gaming inventory and the raw T16 analysis snapshot cover different scopes and cannot be substituted for each other. Verify manifests, columns and row IDs before presenting a period (OQ6); retain a shorter or partial window when that is all the evidence supports.

### Classification validation

Separate four checkpoints: provider response received, structured response parsed, citation integrity passed, role association supported. Add source inspection without converting the failed T16 result into a success. The same text can be quoted correctly while supporting only ownership or downloads, not gameplay. Validation must preserve this distinction.

## Existing proof-of-concept components to reuse

Reuse `household_report.reporting`, `classification`, `analysis`, `storage`, `contracts`, existing Groq/Exa adapters, authenticated report/status templates, immutable imports and the call ledger. The proof-of-concept CLI remains a compatibility entry point, not a second classification implementation. The separate local gaming inventory may supply reviewed candidate hints only after its saved schema and rules are inspected (AS4/OQ6).

Reference private evidence by local manifest/path; never add it to fixtures or build context. Preserve the live sampler and its loaded code. No sampler correction or deployment belongs to this plan.

## Existing preflight and operational gates

The B1 audit confirmed HEAD `bdc5168`, an otherwise clean tracked working tree before these edits, the existing `specs/003/` drafts and the named private directories. T00 inspected local file contents, hashes, B4 acceptance and versioned contracts without provider calls, secret reads, resolver access or Git writes. B4 owner acceptance remains unrecorded (OQ1); the saved T16 job remains `unknown`. Preserve unrelated work.

Offline B1/B2 need combined document approval and implementation authorization; a completed B1 must stop for human review before B2, even if both were mentioned in the initial authorization. They must not be blocked merely because no next live budget exists. Starting a disposable loopback container is part of B2 only if that batch is authorized; no permanent service is enabled. B3 requires a fixed local run manifest, per-run authorization and effective ledger enforcement. Missing artifacts stop only the dependent evidence comparison; synthetic offline tests can still proceed. A new export, collector, provider selection or disclosure expansion is outside this slice.

## Architecture — a small modular monolith

Keep the existing Python/FastAPI/Jinja2/SQLite application and locked dependencies. Proposed local flow: saved evidence bundle → deterministic bounded spans → explicit model request or offline fixture → reference/schema/scope validation → versioned result → existing report. The real model path remains behind the existing analysis gate. No additional model-based extraction, reviewer agent or automatic repair loop.

### Module map and ownership

| Existing owner | Proposed change | Boundary |
| --- | --- | --- |
| `classification.py` | Deterministic span preparation, request instructions, citation/scope validation and role enums | Pure logic; no network, secrets or accounting |
| `contracts.py` | Candidate-scoped span references and versioned result fields only as necessary | No parallel object framework |
| `analysis.py` | Pass bounded evidence, checkpoint results, use explicit new analysis revision and operation limits | Sole external dispatch path |
| `storage.py` | Persist span/evidence/policy provenance in existing versioned payloads; enforce relevant ledger counters | All SQL; no semantic classification policy |
| `reporting.py` and existing templates | Display role, hint/proposal/review state, source span and unknown reason | Reads and filters never dispatch |
| `integrations/groq.py`, `integrations/exa_mcp.py` | Reuse wire contracts; change only if a locally reproduced compatibility defect requires it | One accounted attempt per operation; no hidden retries |
| `inventory.py`, resolver scripts | No new behavior | No attribution, polling or network changes |

### Dependency direction and read/write separation

Retain `web → reporting/inventory/analysis`, `analysis → classification/storage/injected ports`, and the existing composition root. Grounding is pure policy; adapters normalize data. Read endpoints receive no provider/MCP capability. Preview, cached report, source expansion and status polling cannot create a call. UI confirmation reaches only the existing protected analysis command.

### Small contracts at real extension points

**B1 implementation:** each bounded source retains its source ID and URL; deterministic span IDs bind candidate, source, SHA-256 of model-visible text and offsets. Version 2 requests send spans rather than accepting generated quotations. The host verifies selected spans and persists exact text, URL, digest and offsets with the result; old version 1 results retain their reader. Role evidence is checked separately from citation integrity. Reject unknown IDs, cross-candidate spans, changed hashes/offsets, instruction-like text and unsupported role cues. Never treat an arbitrary model quote as source text.

This design is proposed, not demonstrated implementation (AS3). Version the request/result contract; retain the old reader for saved T16 evidence. The old quote validator must continue rejecting the saved bad quote. Do not normalize or rewrite old text to make it pass. A source link/URL can support an installer-host relationship only when the stored evidence actually contains that relationship; a generic publisher page is insufficient (OQ5).

### Expansion rules — add behavior without creating infrastructure

Add only fields and pure helpers required by this defect and report. Reuse the two existing external ports and one SQLite store. No new agent framework, embeddings, vector database, scheduler, message bus, browser crawler or automatic CDN resolver. New gaming role labels are a presentation/schema change, not a new traffic-measurement capability.

### uv, Ruff and Lefthook — one lightweight quality path

Use existing locked tools and `make quality`; do not change the interpreter, package manager or hooks for this feature. New offline tests use synthetic evidence and fake transports. Private regression inspection is an explicit local command, not a pre-push dependency. Do not run `make dns-check` as an offline gate: the README identifies live-resolver access within it. No package downloads, provider/MCP calls or real private artifacts in ordinary checks. Dependency changes require a concrete compatibility need, not a new framework preference.

## Durable data and snapshot identity

Keep the existing ten-table layout unless source inspection proves a required field cannot be stored compatibly (AS3). Prefer versioned JSON payload additions over a migration. Any necessary migration touches only separate application state and must be reviewed and tested; never the live FTL database.

Retain original analyses, rules, evidence hashes, ledger charges and source rows. A policy change alone cannot start a job. Explicit Reanalyze creates a new identity/revision with policy/schema/evidence provenance; replay of the previous identity returns its original `unknown`. Keep candidate roles distinct from namespaces and raw observations. Do not merge conflicting labels or multiply DNS counts when showing a candidate in multiple UI groups.

## Cache, disclosure and grounding

1. Verify saved candidate/evidence manifests locally. Identify whether the failed quotation was invented, paraphrased, clipped, normalized differently or attached to the wrong source; label an unproven cause unknown (OQ5).
2. Build deterministic evidence spans from the exact bounded source text. Preserve source/candidate IDs, URL, offsets and content hash. Use synthetic content for committed fixtures.
3. Test selecting correct and incorrect span IDs without inference. Ask the model, only in an authorized run, to select supplied evidence references rather than regenerate quotations.
4. Validate response shape, requested candidate identity, role/category enum, span scope and citation integrity. Preserve missing/ambiguous outputs. A verbatim reference alone cannot authorize an unsupported service or gameplay claim.
5. Keep four display states distinct: local namespace hint, grounded model proposal, separately reviewed mapping, unknown. Use existing verification fields where possible. Do not automatically promote a proposal to human-verified; no new manual review system is required.
6. Preserve cache precedence and dot-boundary suffix behavior. Use exact-host scope for the validation candidate. Never generalize one tested CDN host to every tenant or publisher endpoint.
7. Save result, evidence and usage before any next action. Render a local deterministic summary; no extra model call.

Local acceptance fixtures must include supported download evidence, a provider-only source, an unsupported gameplay claim, a shared CDN, irrelevant-but-verbatim text, a cross-candidate citation, truncated text and prompt-injection text. The fixed fixture set can validate policy behavior; it cannot establish real-world precision/recall or completeness of gaming discovery.

## Groq/OpenRouter adapters and model preflight

Reuse the previously exercised Groq `openai/gpt-oss-120b` as the proposed optional test configuration, subject to OQ3 and current authorized preflight. This is not a default switch or a claim of present availability/free billing. Preserve the existing supported request settings unless offline evidence identifies a compatibility issue. OpenRouter remains available as previously implemented but is not expanded or tested live in this phase.

Catalog refresh, synthetic probe and completion are separate accounted operations. If a new schema needs a synthetic live probe, include it explicitly in a newly approved run manifest; do not hide it within a one-completion budget. Disabled/unavailable AI leaves reports working.

## Exa runtime integration — separate from OpenCode

Reuse the packaged application's bounded MCP client and existing secret references. No OpenCode session forwarding, key copying or MCP startup on views. OQ3 selects either stored public evidence (zero search/fetch calls) or one newly authorized search; do not silently refresh old sources. Bound and record initialization/discovery separately. Only the allowlisted requested tools may run; no observed-domain browsing or autonomous agent tool.

Raw observations never enter Exa. An approved public candidate still reveals that name to the service; the owner must decide whether this is permitted (OQ2). If not, B3 is skipped. App budgets cannot cap calls by other clients sharing the same Exa account or promise a monetary ceiling without independently configured account controls.

## Budgets, concurrency and recovery

**Proposed B3 envelope, not authorization or confirmed runtime settings:** one candidate, one job, one MCP initialization/discovery session if needed, zero extra fetches, at most one model-catalog request, zero synthetic probes, one completion, zero retries/fallbacks, and no model summary. Research mode is explicitly either saved evidence (zero searches) or fresh evidence (at most one search). OQ3 must settle the mode and exact payload before execution.

Proposed content limits: at most three public sources, 2 KiB UTF-8 per excerpt, 16 KiB total serialized request, and 2,048 completion tokens; proposed wall-clock limit 180 seconds and per-call limit 30 seconds. These are test-design choices, not measured requirements. If they cannot accommodate the chosen evidence/schema, revise the local preview rather than exceed them.

Use the existing verified token-bound mechanism. Where the implementation lacks a proven request tokenizer bound, retain conservative context-plus-completion reservation; do not replace it with `characters/4`. The old 133,120 reservation is historical, not a universal next-run value. B1 adds independent ledger counters for search, fetch, discovery, catalog, probe and completion, with zero caps enforced and a strict mapping constructor requiring every operation cap. T07/T08 still need to bind that mapping to the exact approved run manifest. Freeze the actual model-derived reservation and remaining per-job/day allowance in that manifest (OQ3). Display actual measured input/output separately. Missing usage retains the charge. No dollar amount is invented; an exact monetary ceiling remains unresolved until account/pricing controls are known.

T04 must verify and, if absent, implement separate search/fetch/discovery/completion counters in the existing ledger (OQ4). Count all setup attempts and uncertain dispatches. Atomic duplicate confirmation, concurrent work and restart must not duplicate a job or reset a reservation. A changed policy does not grant new spend. Interrupted calls remain uncertain; no automatic resume after boot, no remote exactly-once claim.

## Inventory, presence and strict attribution

No new inventory work. Keep the existing device page independent and local. This phase always labels destination rows `Household — device unknown`; it does not enable the old conditional attribution feature even if a binding table is populated. A name that suggests a game, region or server role supplies no device identity or measured geography. Do not infer endpoints used for a match from simultaneous presence or DNS times.

## UI, access control and failure behavior

Extend the existing destination details/status view with role, classification method/state, uncertainty, source reference and exact supporting span. Unknowns show the specific failure stage without revealing credentials or raw provider bodies. Show observed query timestamps in UTC with UTC provenance available; counts remain query counts. Keep a local hint separate from verified provider/role fields.

No new dashboard framework or public exposure. Test existing authentication, escaped source/model content, 390px rendering, keyboard access, preserved row totals and zero external requests on ordinary views. Use a disposable loopback instance for authorized B2 checks and stop it afterward. The app remains usable with AI off; stale/partial imports are labeled. Do not present a real multi-day view as validated unless the saved inputs actually cover it (OQ6).

## Affected components, specialists and verification

Expected changes: `destination-report/src/household_report/{classification,contracts,analysis,storage,reporting}.py`, relevant templates, focused offline tests, and this phase's spec/plan/tasks. **Default specialist assignment: `test-driven-development`** for test-first grounding and ledger changes against the existing Python suite. That skill was not present in this session's skill catalog, so B1 followed existing tests and `make quality`. No independent specialist agents are required or authorized. **Conditional tools:** targeted local search/read for code (there is no `.codegraph/` index), `make quality` for offline verification, `make runtime-check` and local browser checks only in an authorized B2, and Context7 only for a concrete framework/API compatibility question. Exa/Groq are external runtime operations exclusively behind an approved B3 manifest, not planning tools or default test dependencies.

Verification sequence: baseline local evidence audit → deterministic positive/negative grounding fixtures → immutable old-result and budget regression checks → authenticated zero-call UI/container checks → optional explicitly budgeted real run → network-disabled replay. Reuse the existing quality/runtime targets where their actual scope fits. Do not require an arbitrary higher test count, repeat paid diagnostics to improve appearance, or treat one accepted answer as broad model accuracy.

Record code revision, fixture/input hashes, commands actually run, results, unresolved issues and whether network was enabled. For the optional run, separate transport success, citation validation and reviewer-assessed role support. If it remains unknown, preserve that outcome and stop at the approved limit. Do not mark the product goal achieved solely because a job returned HTTP 200.

## References and unverified assumptions

Use S1–S5 and their repository paths in `spec.md`. No new web research or technical capability discovery was performed for this planning request; vendor URLs in 002 are references for future authorized compatibility work, not proof of current behavior.

AS1–AS5 and OQ1–OQ6 are the authoritative assumption/question register. B1 verified module contracts, T16 artifact schemas/hashes, operation gates and B4 acceptance status locally. The exact provider response, current shared-account limits and real multi-day coverage remain unverified. The README's blanket MagicDNS-bypass statement is not used as a premise: this phase reports resolver-path uncertainty without changing client settings or asserting a measured bypass. Historical namespace matches remain hypotheses until evidence supports their role.

### B1 implementation record — 2026-10-23

Implemented version 2 candidate-scoped source spans, strict span and role validation, exact supporting-span persistence, analyzer revisioning, and per-operation ledger caps. The saved T16 response body was not retained, so its rejected quotation cannot be reproduced; the saved result remains `unknown`, with zero rules and the original three charges. The read-only snapshot has 82 rows over one hour; the aggregate gaming inventory has 137 matched names and 5,037 rows and cannot restore raw history. `make quality` passed: lock check, Ruff formatting, Ruff lint and 259 offline tests. No provider/MCP call, live resolver read, runtime container, secret read or configuration change occurred. State: **awaiting human review**; B2 needs separate authorization.

### B4 contract reconciliation — 2026-10-23

B3 showed that the version 2 request carried two id vocabularies — source ids (`evidence_ids`) and span ids (`span_ids`) — and constrained only `span_ids`, so a model could duplicate span ids into `evidence_ids`. This is consistent with, not a change to, the planned design: the host deterministically reconstructs cited text from spans. The version 2 request now sends and requires spans only; the host derives the cited sources from the validated spans, and a legacy `evidence_ids` list must still match or the result is rejected. This narrows the "small contracts at real extension points" section: version 2 no longer asks the model for evidence identifiers it cannot validate. Offline regression and replay evidence are in `tasks.md` (T10, B4).
