# Household destination dashboard and on-demand analysis — tasks r3

Inputs: spec r3 and plan r3. Single combined-approval record:
`spec.md#combined-approval`. Specialist/tool assignments are in plan.md;
no task-specific exceptions. R3 retains r2's product scope/four batches and refines
the implementation into a small modular monolith with uv and Lefthook/Ruff tooling.
No implementation batch has started; do not scaffold unused frameworks or layers.

## Current evidence checkpoint (requested separately; not a future feature batch)

| ID | Objective / acceptance result | Verification | State |
|---|---|---|---|
| E1 | Correct UTC deadline, independent-read totals, 900s-average rate claim, retry deduplication and household-origin wording. Keep PID 37817 and historical series intact. | Red/green snapshot/rate/timeout tests; dated handover corrections; process identity and private series checks. | Complete; new sampler code is on disk only, not loaded by the existing loop. |
| E2 | Extract one complete recent hour and reconcile raw rows, IDs, outcome and presentation counts in one snapshot; preserve all query-view columns and preceding-minute rate context. | 04:00–05:00 UTC on 23 Oct: 5,991 rows, 589 domains, 49 reverse rows, 976-row measured peak span. | Complete; private raw evidence and traceable JSON/HTML saved. |
| E3 | Review small actual-domain sample and the top 20 non-reverse names using cached verified mappings and Exa. Preserve subdomains; retain unknowns, broad provider labels and CDN ambiguity. | Cache/source claims in report; secondary source explicitly qualified; offline repeatable rendering. | Complete as assistant-reviewed research; no autonomous AI/Exa client implemented. |
| E4 | Present the private report before dashboard expansion. | Counts reconcile; all domains/row IDs inspectable; local 390px viewport fits; zero remote assets. | Delivered; owner requested runtime/dashboard/device expansion. This is not combined approval of revised r2 documents. |

## Ordered implementation tasks

All are pending the selected batch's execution authorization. The combined r3
approval is recorded in `spec.md#combined-approval`. Shared specialist/tool
assignments are in plan.md; no exceptions.

| ID | Objective / acceptance result | Dependencies | Focused verification | State |
|---|---|---|---|---|
| T00 | Establish one installable `household_report` package, uv project/lock/interpreter pin and locked Ruff/Lefthook dev group; root Make quality targets and pre-push config. Declare owned lint/test scope and separate offline/runtime suites. Do not replace custom hooks without deliberate integration. | r3 approval | Locked clean-environment install/import and legacy CLI compatibility; offline lock/format/lint/tests pass; formatting/lint/lock/test failures block pre-push; no tracked-file changes, downloads, Docker, provider/Exa or live evidence access from the hook. | Done in B1: `destination-report/` uv project + committed `uv.lock`, 3.13 pin, Ruff/Lefthook dev group, Make `dev-setup`/`lock-check`/`format-check`/`lint`/`test-offline`/`quality`, tracked `.githooks/pre-push`. |
| T01 | Implement `reporting`'s frozen 24h/48h/custom bounds, stable period hashes and versioned private imports, retaining every source row/field; reuse one shared query/interpretation implementation. | T00 | Actual available-period reconciliation; timezone/late-flush/ID-reuse/empty/partial-retention/size/timeout fixtures; no provider/MCP/web import dependency. | Done in B1: `household_report.reporting` promoted from the proof of concept; 24h/48h presets, DST-safe custom bounds, coverage, stable period digests; legacy CLI is a thin shared-implementation entry point. |
| T02 | Add the single `storage` implementation with the ten-table model, named atomic operations and immutable report/classification versions. Put exact/suffix cache policy in pure `classification`, not SQL/web/adapters. No live FTL migration or generic repository framework. | T01 | Exact precedence, dot boundaries, field-scoped provider-only suffix, expiry/unknown handling and unchanged saved results after global cache updates; all application SQL stays in storage. | Done in B1: `household_report.storage` with the ten-table schema, `user_version` migrations, immutable rules/reports, atomic claims and the one `call_attempts` ledger. |
| T03 | Implement pure `classification` public-candidate privacy, typed shared contracts and grounded-result validation, ranking safe unknowns by DNS rows with disclosure preview. | T02 | Tokenized/local/reverse/private-tenant exclusion; broad candidate never promoted to specific service; unknown evidence IDs/quotes/actions/extra domains rejected; policies test without external clients/credentials. | Done in B1: pure `household_report.classification` exact/suffix resolution, disclosure exclusions, ranked candidates and strict grounding validation. |
| T04 | Implement `analysis` job/candidate identity and the central dispatch gate using `storage` atomic claims/reservations. Compute day/job charges from the one call-attempt ledger, not duplicate daily counters. | T02 | Two processes/tabs, midnight rollover, insufficient reservation, unknown token upper bound, timed-out calls and restart cannot overspend/reset counters; no network held under DB write lock; boundary tests prevent views/adapters bypassing the gate. | Done in B1: `household_report.analysis` identity, bounded claims and the single dispatch gate that reserves from the ledger inside `BEGIN IMMEDIATE` before one adapter attempt. |
| T05 | Add composition-root/settings wiring and thin Groq/OpenRouter `ModelProvider` adapters (`describe_model`, `complete`) with no default model ID. Core policy validates availability/capabilities/probe/accounting bounds; adapters normalize wire data/usage without retries. | T03–T04 | Shared adapter conformance tests plus stub catalogs/endpoints, supported/unsupported schema modes, invalid credentials, output caps, missing usage, redacted errors; probes/attempts consume limits. | Done in B2: `settings.py` (no default model, owner-only secret reads), `app.py` composition root, `integrations/{common,groq,openrouter}.py`; fake-transport tests for metadata limits, truncation, substitution, usage, redaction and one attempt per call. |
| T06 | Enforce OpenRouter free-only model/endpoint/pricing constraints and optional explicitly approved same-provider free fallbacks. | T05 | Paid/unknown-price/opaque auto-router/paid plugin/fallback rejected; 429 does not change to a paid or cross-provider model; provenance records actual returned route. | Done in B2: zero-price plus explicit allowlist required, `openrouter/auto` refused, `allow_fallbacks: false` and `require_parameters: true` sent, silent substitution and non-zero reported cost refused, missing measured usage refused in free mode. |
| T07 | Implement the Exa `EvidenceClient` adapter using staged configuration/key, explicit bounded MCP discovery and allowlisted search/fetch. Return normalized evidence through the port; no cache/budget policies or retry loops inside the adapter. | T03–T05 | Shared evidence-port conformance plus fake MCP handshake/auth/schema drift/disconnect/429/oversize evidence; reject arbitrary tools, model tool use, key-bearing output and OpenCode session forwarding. | Done in B2: `integrations/exa_mcp.py` allowlists only `web_search_exa`/`web_fetch_exa`, rejects `agent_run`/`web_search_advanced_exa`, fails closed on schema drift and unknown payloads, enforces HTTPS/public hosts, dedupes and caps evidence; fake-session tests only. Search-only sub-cap still deferred (below). |
| T08 | Wire `analysis` evidence-then-model batches through the two injected ports and dispatch gate, with bounded retries, pure grounding checks, per-item checkpoints, cross-report cache and unknown causes. | T05–T07 | Small-batch grounding with fake ports; every attempt charged; no invalid/uncited promotion; partial/budget-deferred results retained; a new model adapter requires no reporting/inventory/storage-policy changes. | Done in B2: `AnalysisService.run` resolves cache first, then bounded evidence search, one batch model request, pure grounding, per-item checkpoints, at most two separately reserved attempts, budget deferral, and cache promotion only for grounded/provider-only results. |
| T09 | Complete frozen preview/Analyze/Reanalyze/Resume identity and interrupted-state handling; conditionally save one local summary on the terminal analysis row. No summary service/table/workflow engine. | T04,T08 | Duplicate POSTs/clicks/tabs share job, same period with unchanged rows returns saved result, reanalysis nonce creates one revision, reboot pauses without calls, completed work is not repeated, summary is cached without model inference. | Done in B2: `preview`/`preview_token_for` (no call), `start` verifies the token with `compare_digest`, `reanalyze` needs an explicit nonce, `resume` reopens only deferred items and clears a stale summary, batch-limit exhaustion pauses instead of losing progress. |
| T10 | Implement cohesive `inventory` normalization, observed presence/gaps, local manual name/category revisions and conservative binding resolution. Do not create separate device/attribution services or a guessed binding feed. | T01–T02 | ProtoJSON omitted defaults, stale listings, wired omissions, failed polls, controller role, randomized MAC, IP reuse/conflicts and current-lease-only attribution rejection; no invented history/uptime or provider imports. | Done in B3: `inventory.py` normalizes ProtoJSON polls (omitted booleans stay unknown), splits controllers/repeaters from household endpoints, reports the four exact presence states with gaps, keeps append-only manual revisions, and resolves attribution only from explicit time-valid IP bindings, so MAC-only or absent bindings match nothing. |
| T11 | Implement thin authenticated `web` read/command endpoints, private diagnostics/downloads and safe output handling; `app` wires dependencies, not domain policies. | T02,T09–T10 | Auth/CSRF/Origin/Host/CORS/path traversal/escaping/body caps; no SQL/provider/MCP clients in web; no credentials/headers/traceback/device data in external payloads; no import/startup remote calls. | Done in B3: `web.py` implements owner scrypt auth, signed SameSite=Strict session cookies, CSRF, Origin/Host/Sec-Fetch-Site checks, body caps, escaping, CSP and private JSON downloads; `app.py` wires protocol-typed services and a single-worker runner. Boundary tests keep `web` free of SQL/provider/MCP imports and startup network calls. |
| T12 | Implement mobile-first reports, local-time period controls, search/category filters, timelines, service-vs-infrastructure sections, expandable evidence and both coverage denominators. | T01,T11 | 390px/keyboard/contrast/browser tests, preserved row totals, local-only filters, zero external calls/assets on view or refresh; AI-disabled report remains usable. | Done in B3: mobile-first report at 390 px with period controls in local time, snapshot selection, filters, 5-minute timeline, coverage denominators, data gaps, service/provider-only/unresolved sections and expandable evidence. Browser check showed AA contrast in both schemes, visible focus rings, no page overflow and zero external requests or assets. |
| T13 | Add Analyze preview/progress/provenance/usage/unknown states plus separate inventory and gated device DNS filters/manual edits. | T09–T12 | Button only triggers after confirmation; polling/filtering does not trigger jobs; attributed/unattributed totals reconcile; router rows always Household — device unknown; inventory still shown with zero attribution. | Done in B3: Analyze preview/progress/provenance/usage/unknown states, resume/reanalyze gating and the separate inventory view with gated DNS filters and manual edits. Confirmation is the only start path, polling/filtering never queue work, router rows stay Household — device unknown, and inventory renders with zero attribution. |
| T14 | Build one non-root loopback-only TLS app image from the existing uv lock with no dev tools or startup sync; add explicit host snapshot/poll commands that use shared import contracts, not generic source plugins. | T11–T13 | `uv sync --locked --no-dev --no-editable`, pinned base/uv images, private files excluded from build context; no Docker socket/live resolver volume/admin credentials/host networking; source/resource/rollback isolation. | Implemented 2026-10-23; image build, offline invariants and explicit container check pass |
| T15 | Operator selects provider/model, supplies provider credential privately and authorizes a capped synthetic runtime test from the actual application/container. Validate Exa separately. | T14 + operator inputs/runtime authorization | MCP handshake + schema discovery + at most one approved public synthetic search; selected-model metadata/probe/classification; counters/redaction/no paid fallback verified. Report partial/unavailable truthfully. | Completed synthetic packaged job 2026-10-23: one Exa search, Groq catalog and 120B completion succeeded; invalid model quotation was safely marked unknown, not promoted. Ledger, saved summary, zero-call replay and AI-off reads verified; T16 was subsequently authorized and run separately. |
| T16 | Demonstrate one approved actual-domain analysis, unchanged-repeat zero-call replay and independent ordinary reports with AI/Exa unavailable; optionally start authorized prospective exports/polls. | T15 + disclosure/budget/start confirmation | Highest-volume safe unknowns only, local raw-data preservation, saved summary/cache/provenance/usage, no resolver restarts or topology changes; collector gaps labeled. | Completed 2026-10-23: one approved observed hostname (identity redacted) analyzed with exactly one catalog request, one Exa search and one 120B completion (1,989 tokens, 2,048 cap; no retry). Strict grounding rejected the model quotation, so the saved item is `unknown` and no rule was cached; retrieved public sources support downloads/updates (installer/content delivery), not gameplay. Network-disabled zero-call replay and AI-off reads passed; raw rows/times preserved privately. |

## Execution batches and stop points

### B1 — Tooling and a working local data/policy foundation (T00–T04)

Outcome: one working vertical slice from preserved snapshot to local report/cache
resolution and testable job/budget reservation, with uv quality tooling. Do not
build empty layers/adapters for later batches. Completion: A1, A6, A18–A19 and local
A10–A11 foundations verified; old proof-of-concept CLI still works. Checks: red/green
offline fixtures, new `make quality`, separate existing `make check`/`make dns-check`,
clean-environment package/CLI compatibility, architecture boundaries and available
actual-window reconciliation without claiming a full 48h dataset exists.
State: **complete, awaiting human review** (authorized by the owner after the r3
approval). T00–T04 are implemented and verified; no provider, Exa, web, Docker or
live-resolver work was part of this batch.
Next action: review the B1 diff and evidence below, then explicitly authorize B2
(T05–T09). Do not start B2 from this batch's green checks.

### B2 — Provider/MCP adapters and durable analysis workflow (T05–T09)

Outcome: bounded configurable provider/MCP ports and replay-safe resumable jobs,
with all calls going through the same analysis-owned gate rather than adapter policies.
Completion: A5–A12 pass with fake network endpoints, including free-only safeguards,
retry accounting and partial results. Actual provider/MCP access remains unconfirmed
until T15; mock success is not a runtime claim. State: **implemented offline
2026-10-23, awaiting human review** (authorized 2026-10-23). T05–T09 are implemented
and all calls were exercised through fake HTTP/MCP transports only; no live request,
credential read or default model ID was used.
Next action: review the B2 diff and evidence below, then explicitly authorize B3
(T10–T13). Do not start B3 from this batch's green checks.

### B3 — Local inventory and mobile dashboard (T10–T13)

Outcome: usable authenticated dashboard with Analyze controls, provenance/coverage
and separate inventory without false DNS attribution. Completion: A2–A4/A13–A15
and protected action boundaries pass local browser/security tests. State:
**implemented offline 2026-10-23, awaiting human review** (authorized 2026-10-23).
T10–T13 are implemented and exercised against synthetic and private-format imports in
an isolated loopback instance; every provider/MCP call remains behind the T15 gate.
Next action: review the B3 diff and evidence below, then explicitly authorize B4
(T14–T16). Do not start B4 from this batch's green checks.

### B4 — Packaging and gated runtime validation (T14–T16)

Outcome: isolated loopback app with separately proven provider/MCP access and a
bounded approved analysis. Completion: A7–A9/A16–A17 demonstrated in the actual
runtime where authorized; unavailable credentials/services leave an explicit gate,
not fabricated success. Checks: isolation/rollback, redaction, capped synthetic and
approved-domain analysis, exact replay zero-call test, AI-off ordinary reporting.
State: **authorized 2026-10-23 (owner message "proceed to b4"); T14–T16 complete
pending owner review/commit**. T14 packaging is implemented and verified, T15’s
synthetic packaged job succeeded, and T16’s single approved actual-domain job ran
under its explicit one-search/one-completion budget. The household Compose service
remains AI-off; the T16 job used an isolated private database and container.

T14 evidence (2026-10-23):

- `Dockerfile` builds both stages from digest-pinned images
  (`python:3.13-slim@sha256:57b29a7c…`, `ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e4…`)
  with `uv sync --locked --no-dev --no-editable`, installs the project non-editable,
  runs as `10001:10001`, and leaves no ruff, lefthook or uv binary in the runtime.
- `compose.yaml` publishes only `127.0.0.1:${HR_PORT}:8787`, runs read-only with
  `cap_drop: ALL`, `no-new-privileges`, 512 MB/1 CPU/128 pids, capped json logs, a
  16 MB `/tmp` tmpfs, read-only config/input binds and one writable private state
  directory. It sets no `AI_*`/`EXA_*` variable, no Docker socket, no resolver
  volume and no host networking. The container bind is the explicit
  `HR_ALLOW_CONTAINER_BIND=1` opt-in required by Docker port publishing; `resolve_bind`
  refuses every other non-loopback address.
- Host commands `export_snapshot.py` (same `query_only` extraction, closed ≤1 h
  window, 0600, no overwrite), `poll_presence.py` (pinned grpcurl, bounded samples,
  explicit failure/timeout records, no client output) and `import_inputs.py`
  (idempotent snapshot/presence import) are wired as Make targets; the import path is
  shared with the application store, not a plugin.
- Built image verified: user 10001 by default (1000 via Compose), no dev tools,
  TLS health 200 and unauthenticated `/` 303 through `https://127.0.0.1`, plain HTTP
  refused, `/app` read-only, no `/var/run/docker.sock`, import returns imported 1
  then unchanged 1. `make runtime-check` reproduces this with synthetic data only.
- `make quality` passes with 237 offline tests (packaging text invariants, fake
  Docker-runner tool tests, listener/TLS settings tests added).

Next action: review T14 evidence, then supply the T15 inputs explicitly (provider,
exact model ID, `0600` credential location, explicit runtime/API-spend authorization,
and separate Exa validation).

T15 operational checkpoint (2026-10-23): owner selected “gptoss 120”, approved the
`~/.groq.key` permission change and the bounded synthetic Groq/Exa checks. Groq's
published identifier is `openai/gpt-oss-120b` (Groq Supported Models,
https://console.groq.com/docs/models); the published model is metered, not a
free-only route. `~/.groq.key` was changed from 0664 to 0600 as authorized.
The packaged application image, run without the web service with a read-only key
mount, made **one** Groq model-catalog request; it returned 401 (credentials
rejected). No completion was attempted, no model capabilities were validated live,
and no retry was made. Groq remains blocked pending a valid owner-provided key.

Separately, the packaged image used the staged owner-only Exa key with a *narrowed*
HTTPS MCP endpoint (`web_search_exa,web_fetch_exa` only, not the staged URL's
broader tool list). MCP initialization/discovery found exactly those two tools,
and **one** synthetic public `example.com` search returned one bounded HTTPS
source. No fetch, agent run, advanced search, household destination or model
completion occurred. The one Exa search may count against the shared Exa account;
the application cannot assert an account-wide monetary cap. This validates the
standalone adapter transport and allowlist, not the full analysis job/ledger path.
T15 remains partial; T16 is not authorized by this runtime check.

20B correction/check (owner messages “openai/gpt-oss-20b, is the model, test it” and
“test it”): Groq documents strict structured output for this model too; the
adapter's exact documented-model allowlist and an offline contract test now cover
20B. In the packaged image, a single catalog request for `openai/gpt-oss-20b`
succeeded (131,072 context, 65,536 maximum completion tokens). One synthetic
`example.com` completion with a 512-output-token cap was sent, but a temporary
diagnostic response hook raised the local `httpx.ResponseNotRead` exception before
the response was inspected. **Provider outcome and charge are unknown**; this is
not evidence of success or a provider 400. No second completion or Exa call was
made. `make quality` passes (243 offline tests). Await explicit permission for one
hook-free retry; T16 remains gated.

Hook-free retry (owner message “try”): exactly one further synthetic
`example.com` completion to `openai/gpt-oss-20b` with a 512-output-token cap was
sent from the packaged adapter; Groq returned HTTP **400**. No response-body
diagnostic, additional retry, Exa call or household data was sent. The error may
concern this application's strict response schema or request parameters, but its
precise cause remains UNKNOWN. Model catalog success alone does not establish a
usable classification endpoint. T15 remains blocked on bounded diagnosis and a
successful synthetic completion; T16 remains unstarted.

Groq rejection diagnostic (owner message “run the diagnostic”): exactly one
additional synthetic `example.com` request with the same app-generated body and
512-output-token cap returned HTTP 400, `invalid_request_error`, parameter
`response_format`. The private 0600 response in `/tmp/opencode/groq-diagnostic/`
identified the specific schema path
`/properties/results/items/properties/evidence_quotes`: Groq rejects `required`
when that no-evidence object has no usable `properties`. No key, prompt or raw
response was printed. The prior 400 was a request-schema failure, not a model
availability or authentication failure. The no-evidence request schema now uses
the required field `evidence_quotes: null` rather than an empty object; a test
failed on the old form and passes on the fix. `make quality` passes (243 offline
tests). This repair has **not** received a live completion check: T15 remains
partial and T16 remains gated. The owner's working plain-chat example confirms
the model can answer plain chat, not that our strict classification request works.

Repaired-request verification (owner message “try and test”): rebuilt the packaged
image with the no-evidence schema fix and sent **one** further synthetic
`example.com` completion to `openai/gpt-oss-20b`, capped at 512 output tokens.
The adapter returned a `stop` finish, the requested model and measured **875 total
tokens** (prompt plus completion). `parse_batch_content` and `validate_grounded`
accepted one result as **unknown**, with no invented service or household device
claim. Thus the selected-model adapter and strict no-evidence response path are
confirmed in the packaged image; the standalone Exa allowlisted transport was
confirmed earlier. No Exa retry, household domain, full analysis job or budget
ledger call occurred in this check. T16 still requires separately approved domain
disclosure and explicit start, and no prospective collection is authorized.

Model selection correction (owner message “then use gpt oss 120”): selected Groq
`openai/gpt-oss-120b` for subsequent work, superseding 20B as the intended model.
With the repaired schema, one synthetic `example.com` completion through the same
packaged adapter also succeeded for 120B (`stop`, requested model returned,
**929 total tokens**, one locally validated **unknown** with no service invented).
No provider fallback, Exa call, household domain or full analysis job was involved.
The isolated Compose service remains AI-disabled; model selection is not permission
to start actual-domain analysis or persistent collection.

Full synthetic application-job check (owner message “run the synthetic app job. and
test all curretn functionality”, 2026-10-23): `make quality` passed (243 offline
tests) and `make runtime-check` passed (3 packaged Compose tests: TLS, non-root,
read-only root, idempotent synthetic import). In a separate private database and
container, with **only** one synthetic `example.com` DNS row, AI was enabled for
this job alone. Authenticated dashboard/inventory/analysis/preview/diagnostic
reads succeeded without call attempts; preview confirmation created one job.
Ledger: one successful Groq model-catalog probe (zero reserved tokens), one
successful Exa search, and one **failed** Groq completion (HTTP 400, error class
`ExternalError`). No retries occurred. Conservative reserved/charged tokens were
131,584, with three total attempts and one Exa attempt. The terminal job was
`partial`, its only item `failed`, and its saved local summary correctly reports
one unresolved failure; this is **not** a successful grounded classification.
Authenticated HTML/JSON status reads, duplicate confirmation and terminal replay
made no additional calls. Reopening the same synthetic DB with AI disabled kept
ordinary dashboard, inventory, preview, history and status reads working.
Private state and logs are under `/tmp/opencode/household-synthetic-job/`; no raw
provider response was captured by the adapter, so HTTP 400's exact upstream reason
is unknown. Do not spend on a repeat until the cause can be safely diagnosed and
the owner authorizes any additional external attempt. The owner's later “i approve
T16” does not specify the domains/budget; “switch ai on” was applied only to this
isolated synthetic job, not to the household-facing Compose deployment. No live
FTL read, Starlink poll, ongoing AI access or topology change occurred.

Separate diagnostic (owner message “add logs and try as a seperate module and write
tests with min tokens”): added `integrations/groq_diagnostic.py` with a standalone
`tools/diagnose_groq.py` entry point; the application adapter and job runner remain
unchanged. One explicit request used only `example.com`, one fixed public synthetic
evidence excerpt, `openai/gpt-oss-120b` and a **256 completion-token cap**. No Exa
call or household data was used, and there was no retry. Groq returned HTTP 400,
`invalid_request_error`, code `json_validate_failed`, message “Failed to validate
JSON. Please adjust your prompt. See 'failed_generation' for more details.” This
is **not** the previously diagnosed `invalid JSON schema for response_format`
error. A small cap may have contributed, but is not proven to be the cause;
the earlier app job failed with a 512 cap. The owner-only 0600 diagnostic record is
`/tmp/opencode/groq-evidence-diagnostic/result.json`; it omits generated text and
redacts the key and URLs. The test-first diagnostic suite covers single dispatch,
private/redacted logs, existing-log refusal and non-success responses. `make quality`
passed: 246 offline tests plus lock/format/lint checks. The tested diagnostic
subsequently records only the length of any `failed_generation`; that field was
not captured in this already-completed live attempt. No further provider attempt
was made. T15's full successful job is still unverified and T16 actual-domain
dispatch remains gated.

Follow-up proposed GPT-OSS settings (owner-supplied guidance): the *existing*
private diagnostic record does **not** contain `failed_generation_length` because
the field was added after that request; no offline inference of empty or truncated
generation is possible. Groq's published reasoning/API docs support GPT-OSS
`reasoning_effort=low`, `include_reasoning=false`, and recommend temperature 0.5–0.7;
they do not establish the claimed 256/512-token failure rates or prove that
excluding reasoning from the response saves generation tokens. Offline-only
changes set low effort, exclude reasoning from returned content and use temperature
0.6 for documented Groq GPT-OSS models in the adapter and diagnostic; the
diagnostic cap becomes 1024 and the **default** Groq job cap 2048 (an explicit
`AI_COMPLETION_CAP` remains configurable). Strict schema stays on. These changes
have not been live-tested and do not authorize a repeat or household disclosure.
`make quality` passes: 248 offline tests plus lock/format/lint checks.

One separately requested follow-up diagnostic (“print complete logs and capture
and give”): ran the explicit synthetic `example.com`/fixed public evidence
diagnostic once with low reasoning effort, temperature 0.6, reasoning omitted
from the response, strict schema and a 1,024 completion-token cap. It returned
**HTTP 200**. The entire captured sanitized 0600 record is
`{"model": "openai/gpt-oss-120b", "status": 200}` at
`/tmp/opencode/groq-evidence-diagnostic/low-effort-1024.json`; the diagnostic
does not capture response body, token usage or finish reason on success. This
verifies acceptance of the changed synthetic request but cannot isolate which
parameter resolved the previous 400 or prove the full Exa-evidence job succeeds.
No household data, Exa call, retry or deployment AI setting change occurred.

Owner requested both explicit `.env.local` integration and a full synthetic retry
(“so fix”, clarified “Both”): added `read_provider_secret` for **only** a named,
explicitly configured owner-only `.env.local` containing one literal
`GROQ_API_KEY` assignment. No shell evaluation, automatic dotenv loading,
environment export or repository secret copying; other providers keep the
existing plain-file path. The owner’s root `.env.local` is ignored, mode 0600,
and its key parsed without printing. The isolated, rebuilt container received
it as a read-only file mount; the household Compose deployment was not changed.

In a fresh synthetic-only SQLite DB, with one `example.com` row and at most one
Exa search, one Groq catalog request and one completion, the full authenticated
preview/confirmation job **completed**. The three ledger attempts all returned
`ok`; the completion measured 1,276 prompt + 269 completion = 1,545 tokens,
against a conservative 133,120-token reservation. The result was correctly
`unknown` because its proposed quote was not verbatim in evidence source s1;
no service was invented or cached. The local summary was saved. The first
post-job HTML status render exposed a sparse-unknown-result template bug;
an offline red/green regression fixed missing optional `service`, `provider`,
`confidence` and `evidence` fields. Rebuilt packaged replay against the same
private DB with Docker networking **disabled** showed authenticated report,
inventory, preview, HTML/JSON status, duplicate confirmation and terminal replay
all succeed with no new attempts; reopening AI-off likewise preserved ordinary
reads. `make quality` passes (253 offline tests) and `make runtime-check` passes
(3 isolated container tests). Private synthetic state is under
`/tmp/opencode/household-synthetic-job-2/`. This proves the bounded synthetic
path, not a validated service classification or an actual-domain analysis.

T16 actual-domain run (owner message authorizing one gaming-related domain,
2026-10-23): inspected the full retained Pi-hole database read-only (3,103
distinct names), not only the saved one-hour exports, and selected the
highest-volume unresolved game-branded endpoint that passed the application’s
public-candidate rules. The approved hostname, all 282 retained rows, the exact
observed times and the 82-row closed 15:00–16:00Z analysis snapshot are preserved
under the private `0700` directory
`PRIVATE_DESTINATION_REPORT_VALIDATION/t16-2026-10-23/`. The apparent client is
the router; no device attribution or play duration is inferred.

One packaged, isolated job made exactly one Groq catalog request, one Exa
`web_search_exa` (5 results) and one GPT-OSS 120B completion (1,717 prompt + 272
completion = **1,989 tokens**; 2,048 cap; conservative 133,120 reservation). No
retry or additional fetch occurred. The model’s answer was rejected because its
quotation was not verbatim in source s2; the saved item is `unknown` and no cache
rule was added. A separate human/agent review of public sources supports
**downloads/updates** (installer and game-content delivery), not
gameplay/matchmaking, authentication or telemetry. The observed destination and
identifying source details are redacted from this version. That review is not an app-grounded classification;
the app’s automated result remains `unknown` by design.

Duplicate confirmation and terminal replay made no new calls. A separate
network-disabled container reopened the saved database without provider or Exa,
returned 200 for dashboard, inventory, analysis, preview, HTML and JSON status,
reported the AI-off notice, and replayed the terminal job with attempts 3 → 3 and
rules 0 → 0. No resolver, topology, household Compose AI setting or prospective
collection changed. Detailed citations and caveats are in the private
`T16-REPORT.md`; exact timestamps are deliberately not copied into this tracked
file.

T15 correction after owner clarified the file format: `~/.groq.key` is a one-line
`GROQ_API_KEY="..."` assignment rather than a bare token. The first 401 was caused
by sending the entire assignment as the credential; it was not evidence that the
token was invalid. The original file remains 0600 and unchanged in content. A
plain-token derivative was written once to the existing 0700 owner-only application
configuration directory as `groq-api-key` (0600); neither token was printed or
committed. The packaged image mounted only that derivative read-only and successfully
retrieved the `openai/gpt-oss-120b` catalog entry (131,072 context, 65,536 maximum
completion tokens). Its catalog omitted `supports_json_schema`; Groq's current
https://console.groq.com/docs/structured-outputs explicitly documents strict JSON
Schema for this exact model. The adapter now narrowly recognizes that documented
model when the flag is absent (explicit false still wins), and model requests bind
quotation keys to the actually supplied evidence for strict-schema compatibility.
Both changes have offline tests. **One** synthetic `example.com` completion with no
household evidence and a 512-output-token cap was attempted through the packaged
adapter; Groq returned HTTP 400. The adapter redacts response details, so the
specific rejection reason is UNKNOWN. No second completion or provider retry was
made. The full classification schema and analysis ledger remain unvalidated live;
do not turn on provider access for household-domain analysis or start T16 on this
evidence. `make quality` passes (242 offline tests). Next action: review the schema
compatibility and investigate the 400 with a bounded, explicitly authorized
diagnostic before any further provider attempt.

## Continuation / approval checkpoint

State: **r3 approved 2026-10-23; B1, B2 and B3 complete, reviewed and pushed
(`a17a0cd..4829696`); B4 authorized 2026-10-23; T14 verified, T15’s synthetic
packaged job succeeded, and T16’s single approved actual-domain job completed
under its explicit budget. B4 remains pending owner review/commit; the
household Compose service is still AI-off and no prospective collection is
running**.
Single approval location: `spec.md#combined-approval` (decision, actor, date,
evidence and exact scope). Earlier one-hour report was delivered. The application,
its offline tests and a loopback-only container now exist; the container has been
built and run locally with synthetic data only. No provider/MCP call, resolver or
sampler change, LAN/WAN exposure or live FTL migration has happened. Preexisting
proof-of-concept work remains preserved and was published in commits `9e1cd92`,
`ed02713` and `f63b4d2`.

Separate explicit user-authorized preparation completed: copied only OpenCode's
Exa remote entry and referenced Exa API key into the owner-only application config
directory outside this repository. Equality and 0700/0600 permissions verified;
OpenCode source unchanged, no external calls made by copying. No Groq/OpenRouter
credential/model was selected. Runtime MCP handshake/search remains **not tested**.

At r2 intake: relevant environment variables unset and host application Python
modules absent. Resolver healthy, zero restarts; PID 37817 remains the single DNS
observation loop. Official docs researched during design, not household-domain
classification. No app tool calls occur until the explicit future runtime action.
Next action: review the B3 diff and evidence below, then explicitly authorize B4
(T14–T16). Do not start packaging or any runtime provider/MCP call from this batch's
green checks.
Runtime provider/MCP access remains T15 and needs the owner's selected provider/model,
a `0600` credential file (the supplied `~/.groq.key` is still `0664`, so `read_secret`
correctly refuses it) and explicit spend authorization. The owner named GPT-OSS on Groq
as the intended model; the exact catalogue ID (`openai/gpt-oss-120b` vs
`openai/gpt-oss-20b`) stays unverified and is never defaulted.

### R3 engineering refinement — documentation only

- Four feature modules (`reporting`, `classification`, `analysis`, `inventory`),
  one concrete SQLite store, two small external ports and thin web/bootstrap
  boundaries; explicit dependency direction and adapter conformance tests.
- Ten initial tables instead of fifteen: bounded nested evidence/client records,
  one attempt ledger for accounting and the summary on its analysis row. No plugin,
  generic repository, workflow/DI framework, event bus or new service.
- uv project/lock/interpreter pin; Ruff/Lefthook in locked dev dependencies;
  offline, non-mutating pre-push quality targets; runtime tests remain opt-in.
- This revision changes documents/index only. No pyproject/lock, hooks, environment,
  credentials, collector or container has been installed/changed by this revision.
  Historical checks below are evidence for prior code, not tests of proposed tools.
- Verification: `make check` passed. Documentation checks reconciled r3 headers,
  A1–A19, unique T00–T16, dependency direction and the single approval record;
  confirmed no pyproject or Lefthook configuration was installed. New Ruff/Lefthook
  execution and adapter conformance checks remain T00/B1 work, not claimed results.

### R2 drafting/preparation verification — 2026-10-23

- `make check` passed; `make dns-check` passed all 24 **existing** tests. These
  verify the unchanged pilot/proof of concept, not unimplemented r2 behavior.
- Rechecked staged Exa key equality without printing its value, endpoint equality,
  0700 directory / 0600 file modes and location outside the repository. No external
  calls made by copying or that verification. Only the explicitly authorized Exa
  connection/key were copied; source OpenCode setup unchanged.
- Resolver remains healthy, zero restarts; PID 37817 remains the sole DNS loop.
- Main-agent architecture assessment: **Ready for combined design review** with
  explicit runtime, credential/model selection and collector/publication gates.
  It is not a human approval or proof of runtime model/MCP availability. The plan
  distinguishes local idempotency from impossible remote exactly-once guarantees,
  conservative token reservations from estimates, and app budgets from shared-key
  Exa account usage. No additional review artifact or approval record created.

### Historical r1 proof-of-concept verification — 2026-10-23

- `make check`: passed (nine Python files parsed; whitespace/private-ignore gates).
- `make dns-check`: **24 tests passed** (3 configuration, 2 guard, 2 relay,
  7 observation, 10 destination-report). New behavioral tests were observed failing
  before implementation, then passed. Runtime aggregate test output uses only a
  temporary directory, not the real observation series.
- Actual final report: snapshot/export/group/outcome totals all equal 5,991; raw
  row-ID multiset matches presentation references; all 13 query-view columns and
  raw/cache SHA-256 hashes verified. Top 20 non-reverse domains have sourced
  classifications, including provider-only/CDN ambiguity. Unknowns remain visible.
  The reviewed example-domain probe suspicion retains all 57 rows, without asserting
  origin or purpose; it is separate from the stricter current-hour timing heuristic.
- Browser: final local HTML, 589 domain cards, 390px viewport, no horizontal overflow,
  no external assets, local raw evidence links. Private mobile screenshot saved.
- Safety: resolver healthy, restart count zero, original start 2026-10-22 18:02:32 UTC;
  sampler PID 37817 started 18:33:48 UTC and is the only loop instance. No live
  configuration or historical-series rewrite. Corrected matcher independently
  found zero messages in currently available rotated container logs.
- Technical verdict: **Ready for human review of the evidence proof of concept**,
  not approval of future implementation/deployment. Deferred checks remain as
  listed in plan.md; no reboot, restart, DNS-query tests or 24/48h dashboard run.

### B1 implementation record (2026-10-23)

Changed paths: `destination-report/` (`pyproject.toml`, `uv.lock`, `.python-version`,
`README.md`, `src/household_report/{__init__,contracts,storage,reporting,classification,analysis}.py`,
`tools/import_snapshot.py`, `tests/offline/*`), `.githooks/pre-push`, `lefthook.yml`,
`Makefile`, and `dns-pilot/destination_report.py` (now a thin CLI over the shared
implementation). `dns-pilot/test_destination_report.py` moved into the application's
offline suite so one implementation is tested in one place; `make dns-check` keeps its
resolver-only checks.

Checks run against this code state:

| Command | Result |
|---|---|
| `make quality` | lock check, format check, lint and 64 offline tests pass |
| `make check` / `make dns-check` | pass; pilot tests unchanged (7 observation + 7 configuration/firewall/relay) |
| `.githooks/pre-push --force` | all four jobs pass; a deliberately unformatted file blocks with exit 1 and is left unchanged |
| fresh shell without global Lefthook | hook passes using only the locked `.venv` binary and `uv` |
| `uv run --project destination-report` from `/tmp` | `household_report` imports as an installed package |
| real one-hour snapshot import + report | 5,991 rows / 589 domains / 49 reverse rows reconcile; 5,987 router-forwarded rows stay device-unknown; digest stable on re-import |

Deviations and gaps, stated honestly:

- The Exa **search-only** sub-cap (8/analysis, 40/day) is not enforced yet because
  B1 has no Exa calls. The gate enforces total Exa attempts (12/analysis, 60/day);
  T07/T08 must split search from fetch when the adapter exists.
- Provider catalogue/probe counting, batch prompt construction and the actual
  `ModelProvider`/`EvidenceClient` implementations are T05–T07. Only their shared
  contracts exist. *(Superseded by the B2 record below.)*
- Web, inventory and packaging are untouched. No `settings.py`/`app.py` module was
  created just to fill the planned layout; composition arrives with the web batch.
  *(B2 later added `settings.py`/`app.py` because provider wiring needed them; web
  composition is still absent.)*
- The offline snapshot used for reconciliation came from the existing private
  proof-of-concept export and was written to a temporary database outside the repo,
  then deleted. No household rows were copied into the repository.

### B2 implementation record (2026-10-23)

Changed paths: `destination-report/src/household_report/{settings.py, app.py,
analysis.py, classification.py, contracts.py, storage.py}`,
`destination-report/src/household_report/integrations/{__init__,common,groq,
openrouter,exa_mcp}.py`, `destination-report/tests/offline/{test_settings,test_groq,
test_openrouter,test_exa_mcp,test_analysis_run,test_boundaries}.py`,
`destination-report/pyproject.toml` (adds `mcp>=1.8,<2`) and `uv.lock`.

Behaviour added, all behind fake transports:

- Two ports only: `ModelProvider` (`describe_model`, `complete`) and
  `EvidenceClient` (`discover`, `search`, `fetch`). Adapters make one attempt per
  operation and never retry, cache or choose a tool; the retry policy lives in
  `AnalysisService` and each retry is a separately reserved ledger row.
- `settings.py` has no default model ID, requires an explicit `AI_MODEL_ID` and
  credential path, and `read_secret` refuses group/world-readable or foreign files
  before any adapter is built. `Application.open` performs no network access.
- OpenRouter free-only mode needs a zero price *and* an explicit allowlist, refuses
  `openrouter/auto`, sends `allow_fallbacks: false`/`require_parameters: true`,
  and rejects a substituted model or a non-zero reported cost.
- Exa allowlists only `web_search_exa`/`web_fetch_exa`, rejects `agent_run` and
  `web_search_advanced_exa` at construction, fails closed on missing tools, schema
  drift or unrecognized payloads, accepts only public HTTPS hosts, dedupes URLs and
  drops whole sources beyond the payload cap.
- The runner resolves the reviewed cache first, searches only for unresolved names,
  sends one bounded batch request, validates every result against that candidate's
  own retrieved evidence, checkpoints each item, and promotes only grounded or
  provider-only results to expiring rules. Budget refusal marks the rest deferred and
  finishes `partial`; an exhausted batch allowance finishes `paused` with no summary.
- Confirmation is token-bound: `preview` makes no call, `start` requires the matching
  token via `hmac.compare_digest`, `reanalyze` needs an explicit nonce, and `resume`
  reopens deferred items only and clears a stale summary.

Checks run against this code state:

| Command | Result |
|---|---|
| `make quality` | lock check, format check, lint and 133 offline tests pass |
| `make check` / `make dns-check` | pass; resolver tests unchanged |
| clean-interpreter boundary probe | `household_report.reporting`/`classification` import without `httpx`, `fastapi`, `mcp`, `pydantic`, `starlette` or `uvicorn` |
| real one-hour snapshot re-import | 5,991 rows, same period `[1792728000, 1792731600)`, digest `3231e9bb…f07e`, written to `/tmp` and not committed |
| composition-root smoke test | AI unset → `ai_enabled: false`, no evidence client, provider refused; AI set but key `0664` → `SettingsError` before any call |

Deviations and gaps, stated honestly:

- **No live call was made.** Every provider and MCP test uses `httpx.MockTransport`
  or a fake MCP session, so model availability, catalogue limits, real MCP schemas
  and account-level Exa usage remain **UNKNOWN** until T15.
- The Exa **search-only** sub-cap (8/analysis, 40/day) is still deferred: the gate
  enforces total Exa attempts (12/analysis, 60/day) and `SEARCH_LIMITS` bounds one
  search, but search and fetch are not counted separately yet.
- A model that reports no citable evidence can still yield a provider-only rule; the
  ledger keeps such attempts fully charged when usage is unconfirmed.
- Requirement "resumable partial progress" is interpreted as: budget-deferred items
  reopen on an explicit resume, failed items stay failed for visibility, and a
  batch-limit stop pauses rather than completing. There is no automatic retry.
- Web, inventory, packaging and the collector are untouched; nothing was restarted,
  installed into the pilot or exposed on a socket.

---
### B3 implementation record (2026-10-23)

Changed paths: `destination-report/src/household_report/{inventory.py, web.py,
reporting.py, storage.py, app.py, settings.py}`,
`destination-report/src/household_report/templates/{base,login,report,inventory,
analysis,analysis_preview,analysis_status}.html`,
`destination-report/src/household_report/static/{app.css,app.js}`,
`destination-report/tools/set_password.py`,
`destination-report/tests/offline/{test_inventory,test_web,test_app,test_reporting,
test_boundaries}.py` and (patch bump only) `destination-report/pyproject.toml`.

Behaviour added:

- `inventory.py` normalizes Wi-Fi client polls, keeps controllers/repeaters separate
  from household endpoints, reports the four exact presence states
  (`listed` / `not_listed_in_successful_poll` / `monitoring_gap` / `unobserved`),
  never turns a missing poll or lease into an absence, and records manual revisions
  append-only. Attribution happens only through explicit time-valid IP bindings; the
  current lease, timing, domains and AI never attribute a row.
- `storage.py` schema v2 adds `inventory_polls` (`poll_digest` + unique index) with a
  guarded `migrate()` that upgrades a v1 file in place, plus inventory, read-model and
  recent-analysis accessors.
- `reporting.py` gains `timeline`, `classification_coverage`, `merge_period_digest`,
  `filter_report` and `ReportService`, which resolves `24h`/`48h`/`snapshot`/`custom`
  to UTC half-open windows, merges overlapping snapshots, qualifies row ids as
  `"{snapshot_id}:{row_id}"`, and reports per-source provenance plus `data_gaps`.
  Provider-only rules now fill `provider` (never a service, never a category claim).
- `web.py` adds an authenticated mobile dashboard: local owner password (stdlib scrypt
  record), HMAC-signed `hr_session` cookie (HttpOnly, SameSite=Strict, Secure under
  https), CSRF derived from the session, 5-failure/300 s throttle, Origin/Host/
  Sec-Fetch-Site checks, body caps, escaping, `CSP default-src 'none'`, no external
  assets, loopback-only listener. `web` imports no package module, SQL, `httpx` or
  credential code; services are passed in as protocols and jobs go through a
  single-worker executor.
- Analyze stays explicit: `/analysis` and `/analysis/preview` are pure local
  computation (candidates, local exclusions and a preview token), provider/MCP work
  starts only on the confirmation POST, and Reanalyze needs a per-render nonce.

Checks run against this code state:

| Command | Result |
|---|---|
| `make quality` | lock check, format check, lint and 198 offline tests pass |
| `make test-offline` | 198 tests: inventory 29, web 27, app 4, reporting 16, boundaries updated |
| browser check (390×844, Chrome for Testing, loopback only) | login, dashboard (2 merged snapshots, 198 rows, 18 domains), timeline, coverage, `data_gaps`, filters, inventory states/gaps/infrastructure, manual edit + clear, preview, status page and JSON export all render without horizontal page overflow |
| network panel after page loads | only `127.0.0.1:8787` document/CSS/JS plus one browser-native `data:image/svg+xml` picker icon; zero external requests, zero runner invocations |
| contrast (light / dark) | muted 5.96 / 8.62, accent 6.84 / 7.18, status pairs 6.24–9.71: AA for normal text |
| keyboard | `:focus-visible` 3 px accent outline, 2 px offset on links, selects, buttons and summaries |
| AI-off path | preview stays available; confirmation form is absent and the page explains why; no call made |

Defects found by the browser check and fixed here:

- `Referrer-Policy: no-referrer` made Chrome send `Origin: null` on the login POST, so
  the Origin guard refused a legitimate sign-in. Policy is now `same-origin`; a test
  pins it and asserts a same-origin `Origin` is accepted while `null` stays refused.
- Provider-only classification rules were invisible in the report because only the
  service field was resolved; they now fill `provider`/`category` and are counted as
  `provider_only` in coverage, with a regression test.
- The merged snapshot dropped `retained_rows`/`oldest_epoch`/`newest_epoch`, so
  coverage rendered `None`; sources now carry them and the report shows the newest
  value or "not reported".
- The Analyze page disabled the *local* preview button when AI was unconfigured; it is
  now always available (the confirm form remains gated) and both halves are tested.
- Preview accounting omitted reverse lookups (they live in `reverse_lookups`), so
  "Excluded locally" under-counted; the preview now lists them with their reason.
- Saving `category=unknown` recorded an explicit manual category that left a stale
  `(manual)` marker after clearing; the form sentinel is now normalized to "no label".
- A `/favicon.ico` redirect to `/login` polluted the session log; it now returns 204.

Deviations and gaps, stated honestly:

- **No live provider/MCP call was made in B3.** Analysis pages were verified with a
  synthetic analysis row and fake services; real catalogues, Exa schemas and spend
  remain T15.
- The Exa search-only sub-cap (8/analysis, 40/day) is still deferred from B2.
- Browser checks used a throwaway SQLite file and synthetic poll/snapshot fixtures
  under `/tmp/opencode`; nothing was imported into the pilot, no listener was left
  running, and the collector PID 37817 was untouched.
- `/favicon.ico` returns an empty 204 rather than an icon; harmless, unauthenticated
  and local.
