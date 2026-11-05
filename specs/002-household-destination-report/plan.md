# Household destination dashboard and on-demand analysis — plan r3

Input: `spec.md` r3. Single approval record: `spec.md#combined-approval`.
R3 refines r2 into a **modular monolith**: four feature modules, thin web/integration
boundaries, one SQLite implementation and one composition root. It adds no product
scope, services or runtime permissions. Preserve the delivered one-hour evidence and
existing uncommitted work; no runtime application code has been added. The module
map and persistence choices below supersede r2's flat list of many technical modules
and fifteen proposed tables; the evidence/privacy/budget requirements still apply.

## Validated evidence and decision

Pi-hole image remains pinned at 2026.10.0 / FTL 6.8. Its `queries` view joins
integer-backed `query_storage` to domain/client/forward/additional-info tables.
Read the view rather than treating stored domain IDs as names. Timestamps contain
fractional Unix seconds despite the declared INTEGER affinity.

The read-only evidence exercise selected **2026-10-23 04:00–05:00 UTC**
(09:30–10:30 UTC). One SELECT exported **5,991 rows / 589 domains**;
SQL window count, raw array length, distinct row IDs and presentation totals agree.
All available query-view columns are in the final private snapshot. Of these,
49 rows are reverse lookups, 5,987 are router-forwarded (origin unknown), and four
have other apparent clients. These categories overlap; they must not be summed.
36 non-reverse domains have tentative service labels, 174 provider-only labels,
367 remain unmapped, and 12 reverse domains are separate. Provider-only labels
are deliberately not merged into a single application service.

Peak measured inclusive 60-second span for router-forwarded persisted rows:
**976 rows, 04:47:30.516375–04:48:30.516375 UTC**. This is not remaining headroom
against FTL's configured 1000/60-second limiter. Rows can lag writes and do not
reconstruct the limiter's live input/state. No configuration change is proposed.

Private evidence directory (not committed):
`PRIVATE_DESTINATION_REPORTS/2026-10-23_0400-0500Z-report/`, containing
`observations.json`, `classifications.json`, `report.json`, `report.html` and a
mobile preview. Report metadata hashes the exact raw export and cache used.
The standalone report opened in the headed browser at 390px width with no
horizontal overflow and no external asset requests. This tests file presentation,
not household-mobile reachability or an interactive dashboard.

### Historical extraction probe

The documented `/api/queries?disk=true` endpoint was tested with two six-row
pages on the actual deployment. Following the returned cursor repeated the first
page. A separate SQL/API total comparison also differed, but those reads occurred
across later database flushes, so it was **not** a consistent-snapshot comparison
and does not prove an API counting defect. Private probe artifacts are under
`PRIVATE_DESTINATION_REPORT_VALIDATION/`. Do not generalize this bounded test into
universal API impossibility. For this feature, the existing SQLite CLI provides a
tested, single-statement extraction without API credentials or cursor dependence.

### Classification validation

Reviewed Exa search/fetch results against the 20 most frequently observed
non-reverse names in the selected hour, following an initial 12-domain sample.
The assistant performed the research and checked claims, then populated an
owner-only cache. **There is no autonomous runtime classifier yet.** The script
uses cache-only classification and leaves hundreds of domains unknown. Evidence
supports generic provider namespaces separately from services. Official Apple,
Google, OpenAI, Microsoft, Mozilla, Cloudflare, IANA and Akamai documents were
consulted; a Meta network-requirements page was unavailable, so the relevant
secondary-source-only association is marked medium confidence and ambiguous.
No observed tenant/CDN full hostname, query time or client data was sent to Exa.

## Existing proof-of-concept components to reuse

Existing Python standard library + host's Docker CLI + running FTL SQLite CLI:

1. `dns-pilot/destination_report.py` accepts an explicit closed hour or saved JSON.
2. `observe_queries.sql` executes `PRAGMA query_only=ON` and one SELECT with a
   30-second timeout. One statement freezes totals and exported rows together;
   preceding-minute timing context supports per-client peak measurements.
3. Pure Python validates counts, keeps every original row and produces exact-name
   presentation groups. No DNS lookups, arbitrary HTTP calls or retry subtraction.
4. The local private classification cache supplies scoped, expiring mappings.
   Exact rules override suffix rules; suffix matches require a dot boundary.
   No eTLD+1 or CDN-based service grouping. Expired/uncited entries fail closed.
5. New 0700 output directories and 0600 files hold immutable raw/cache copies and
   derived JSON/HTML. Existing output directories are refused. HTML escapes all
   observed content, contains no scripts/remote assets and applies restrictive CSP.

The sampler's on-disk reporting fix now uses one SQL snapshot, bounded counts and
measured 60-second rates. Legacy keys are annotated accurately. **PID 37817 keeps
its old loaded code** and is not restarted; old samples remain untouched. Its actual
48-hour deadline is 2026-10-24 18:33:48 UTC. It still has
no reboot-survival mechanism. This feature does not silently add one.

The old sampler searched for a literal `rate.limit`, not a regular expression,
and could miss normal hyphenated `Rate-limiting` messages. The on-disk fix uses
explicit message matching with tests. An independent check of available container
logs found zero matching rate-limit messages; old per-sample zeros alone are not
proof of absence. Log rotation and other log sinks remain coverage limits.

## Existing preflight and operational gates

Local inspection on 2026-10-23 found the resolver healthy with zero restarts and
PID 37817 the only DNS observation loop. The application does not yet exist;
`mcp`, `httpx`, `fastapi` and `pydantic` are not installed in the current host Python.
Relevant Groq/OpenRouter/Exa environment variables are unset; this is not a claim
that credentials cannot exist elsewhere. Do not install or scrape unrelated secrets
as part of drafting. No selected provider/model has been supplied or validated.

The user subsequently explicitly requested reusing OpenCode's Exa key/config.
Only the existing Exa remote entry and its referenced key were copied to
`~/.config/starlink-monitoring/destination-report/exa-mcp.json` and `exa-api-key`.
The directory is 0700, files 0600, key bytes and endpoint/settings equality were
checked locally without printing values. Source OpenCode configuration and all
other credentials were untouched. Copying made no external calls. This is private
credential staging, not application deployment or proof of runtime MCP access.
The staged configuration preserves the original file-reference form; the backend
will resolve its key via a read-only secret mount, not return it to the browser.
The backend tool allowlist still excludes agent tools even if the copied server
configuration exposes them. Do not forward an OpenCode session identifier.

Required later: combined r3 approval, one batch authorization, operator-selected
provider/model and its private key, explicit runtime test/start authorization and
runtime MCP discovery. Read-only host exporters/pollers are separate starts. The
existing AGENTS.md says no AI/custom application yet; update only that scoped
authorization pointer after genuine combined approval, retaining all network/privacy
prohibitions. No publication, collector startup or live API spend is implied here.

## Architecture — a small modular monolith

Keep Python, SQLite, Docker, unittest and the existing FTL extraction/Starlink
diagnostics. Add one Python service under `destination-report/` using FastAPI,
Pydantic, Jinja2, Uvicorn, HTTPX and the official Python MCP client. Resolve compatible
versions and lock them with uv in B1; pin the Docker base/uv image digests during
the authorized packaging batch. Do not
assume SDK v1/v2 symbols from a moving README. HTTPX implements the two thin
OpenAI-compatible provider adapters; separate provider SDKs, Node/React, Redis,
Celery and a database server are unnecessary. One process owns a durable SQLite
job queue and bounded async worker; reads remain available during slow AI calls.

Data path:

`existing FTL -> host read-only snapshot helper -> private immutable input files
-> application SQLite/read models -> mobile HTML + local JSON endpoints`.

The host helper reuses one-statement `query_only` extraction. Initial refresh is an
explicit Make/CLI command; if prospective periodic refresh is approved, a separate
bounded host job can publish at five-minute intervals. No Docker socket, live
Pi-hole volume, resolver API password, host network or new privileged path reaches
the application. The UI discloses input freshness; Analyze never secretly runs a
host shell or refreshes the live resolver. An outdated snapshot remains viewable.

Inventory imports existing private `presence-*.json` envelopes after validating
timestamps, return codes and `wifiGetClients` content. Optional new 15-second polls
reuse only the established read-only RPC and pinned grpcurl image, write new
timestamped files and explicit error records, and never overwrite old probes or
reuse the live DNS sampler PID. Start prospectively only at its operational gate.

Use separate 0700 application/input directories and 0600 files. All existing raw
files and every included observation remain intact. No automatic cleanup policy
is introduced for old reports. Bound new imports/disk usage and stop new jobs
gracefully on exhaustion rather than alter DNS retention or delete evidence.

### Module map and ownership

Use **four cohesive feature modules**, not a service/class/file for every noun.
Start each feature as one Python module. Split a module into a package only when
actual independent behavior or a testing boundary warrants it; file/line quotas
are not architecture. This proposed layout makes dependency direction concrete:

```text
destination-report/
  pyproject.toml
  uv.lock                  # committed dependency resolution, not a hand-edited file
  .python-version          # tested interpreter pin
  src/household_report/
    app.py                 # composition/lifecycle; creates and wires dependencies
    settings.py            # local operator config, secret references, safe defaults
    contracts.py           # small shared typed records + two external ports
    storage.py             # the single SQLite implementation and transactions
    reporting.py           # snapshots, periods, DNS outcomes, coverage, read models
    classification.py      # cache policy, public-candidate privacy, grounding
    analysis.py            # explicit jobs, budgets, retries, checkpoints, summary
    inventory.py           # observed devices, manual overrides, presence, bindings
    web.py                 # HTTP/auth/CSRF, input/output adaptation, templates
    integrations/
      groq.py              # provider wire format -> shared model contract
      openrouter.py        # provider wire format/free-route metadata -> contract
      exa_mcp.py           # real MCP discovery/search/fetch -> evidence contract
    templates/
    static/
  tools/                   # explicit host export/poll entry points, not web shell jobs
  tests/offline/           # policies, real SQLite, fake adapters and in-process web
  tests/runtime/           # explicitly invoked container/provider/collector checks
  Dockerfile
  compose.yaml
```

`household_report` deliberately differs from the existing standalone
`dns-pilot/destination_report.py` name. Promote/reuse its tested pure extraction and
interpretation functions behind one implementation, retaining its CLI behavior via
a thin compatibility entry point. Do not maintain two independently evolving query
builders or add `sys.path` tricks. Verify the installed package and old CLI from a
clean test environment, not only the repository working directory.

| Owner | Public responsibility | Does not own |
|---|---|---|
| `reporting` | Freeze/import period, reconcile rows, build report/timeline/coverage and assemble cached classifications; accept optional verified attribution results | AI scheduling, HTTP/provider calls, source polling or deriving identities from inventory |
| `classification` | Resolve exact/scoped suffix rules, prepare safe public candidates, build classification request, validate grounding/unknown outcomes | Secrets, network calls, retries, budgets, device categorization |
| `analysis` | Prepare/claim/execute/resume explicit jobs; call gate; budget accounting; checkpoints; single local summary | Vendor wire formats, template rendering, router/DNS collection |
| `inventory` | Normalize collected device observations, local categories/overrides, gap/presence views and strict time-valid binding resolution | Destination guesses, AI/research, raw DNS writes |
| `storage` | All application SQL, schema upgrades, immutable versions, atomic claims/reservations/checkpoints | Privacy/business decisions, retries, network, HTTP errors |
| `integrations` | Normalize provider/MCP capabilities, results, usage and errors; one declared external attempt per operation | Ranking, disclosure approval, cache verification, accounting policy, silent retries |
| `web` | Authenticate, validate local commands, call feature entry points, render/read status | Direct SQL, provider/MCP clients, worker orchestration or raw secret configuration |
| `app` / `settings` | Construct dependencies once, load local operator settings and control lifecycle | Business rules or external work during import/startup |

`privacy`, cache matching and grounding belong together inside `classification`;
jobs and budgets belong together inside `analysis`; presence and attribution belong
together inside `inventory`. Extract a helper later for a demonstrated reason,
not as a generic framework. `contracts.py` holds only truly shared value contracts,
not a catch-all utility module or copies of every database/HTTP entity.

### Dependency direction and read/write separation

```text
app/settings -> assemble web, features, SQLite store, lazy external adapters
web          -> reporting | inventory | analysis (public feature functions only)
analysis     -> reporting | classification | storage | injected external ports
reporting    -> classification | storage
inventory    -> storage
classification -> shared contracts / pure policies
storage and integration adapters -> shared contracts (not feature orchestration)
```

No reverse import from a feature into `web` or `app`; no dependency from reporting,
inventory or storage into analysis/provider/MCP code. Feature policies do not import
FastAPI, HTTPX or the MCP SDK. Adapter imports/client construction are lazy enough
that a missing/disabled AI integration does not break ordinary reports. Constructors,
module imports and application startup do not perform remote capability discovery.
There is no service locator, mutable module-level client or import-time job creation.

Keep reading and explicit actions separate **functions in the same application**,
not a CQRS framework. Reporting/status/filter endpoints receive only read-oriented
feature functions; only protected Analyze/Reanalyze/Resume commands can reach
`analysis` dispatch. This is a capability boundary, not just a UI convention.
Inventory is an independent local feature: its binding resolver can supply an
explicit verified attribution value when composing a report. Reporting does not
import inventory or query devices itself; absent/failed inventory means unknown
attribution, not a failed report. Do not accept that trusted value directly from
browser input. This also keeps the B1 reporting slice independent of B3 inventory.

### Small contracts at real extension points

Use typed immutable/value-style records for shared inputs/results, with explicit
validation at import, HTTP and external-response boundaries. Keep HTTP/database
representations local to their boundaries; do not invent a parallel DTO/entity
hierarchy for each object. The shared concepts are:

- `Period` / `SnapshotRef`: fixed UTC bounds, datasource/data hash and provenance;
  external integrations never receive the raw snapshot handle or paths.
- `PublicCandidate`: opaque local item ID, approved public name, permissible claim
  scope and disclosure-policy revision; no client, raw-log row or activity timestamp.
- `EvidenceBundle`: candidate-scoped source IDs, URLs, bounded excerpts, hashes and
  capture metadata. Build a smaller external payload, not serialize the whole record.
- `ClassificationResult`: nullable service/provider, role/category, evidence IDs,
  confidence, ambiguity, verification state and unresolved reason.
- `AttributionResolution`: locally verified per-row binding references/unknown
  reasons, never an inferred device identity or a browser-authored identity map.
- `ModelCapabilities`, `ModelRequest`, `ModelReply` / `Usage`: normalized capability,
  bounded request, structured response/actual model, and measured-or-unknown usage.
  A request contains approved public candidates/evidence only, never whole reports.

Only **two small substitutable ports** are justified initially:

| Port | Operations | Contract |
|---|---|---|
| `ModelProvider` | `describe_model(model_id)`, `complete(request)` | One declared HTTP attempt per operation; return normalized capabilities or reply/usage; no hidden model switch, retry, cache or research |
| `EvidenceClient` | `discover(limits)`, `search(public_query, limits)`, `fetch(public_urls, limits)` | Explicit bounded protocol/tool discovery; search/fetch each make one declared tool attempt and return normalized evidence; no agent loop or arbitrary tools |

Implement these as small Python protocols with injected concrete adapters, not
inheritance-heavy base classes. Provider-specific wire parsing/price metadata stays
inside its adapter; free-only eligibility, budget limits and retry decisions stay
central so a new adapter cannot redefine them. Reject unsupported capability/usage
fields explicitly rather than leaking a vendor SDK object or passing an untyped
`**options` bag through the core. Do not build interfaces for each feature function
or a generic repository interface when there is only one persistence implementation.

Every external operation, including catalog/probe/retry, goes through the concrete
`analysis` call gate: reserve/record in a short storage transaction, invoke exactly
one adapter attempt outside that transaction, normalize and checkpoint/reconcile.
MCP initialization/discovery has its own bounded attempt accounting and cannot be
hidden inside each retry. `discover` reserves a bounded handshake/catalog allowance
before connecting and records its protocol outcome separately from search/fetch
charges; it makes no search calls. Probes reuse `complete` with synthetic data. Adapters do
not own retry loops or direct budget writes. This makes accounting enforceable and
keeps test doubles small, without creating another abstract transport framework.

### Expansion rules — add behavior without creating infrastructure

| Future need | Small change | Not required |
|---|---|---|
| Another model provider | One adapter, explicit config selection entry and the shared adapter conformance suite | Reporting/UI changes, a new accounting policy or dynamic plugin loader |
| Another research backend | One evidence-port adapter with the same disclosure/attempt/grounding rules | Agent framework or changes to report identity |
| Another observation export | One explicit format importer that emits the existing validated snapshot/device contracts | A generic source-plugin platform, source-specific UI or live DB access in the web app |
| A new report format | Render the existing local read model, with its provenance/unknown semantics | Another service, database copy or re-running AI |
| Reliable device binding evidence becomes available | A reviewed local binding importer and its provenance/time-conflict tests | Changes to AI or relaxed attribution rules |

Keep Groq/OpenRouter selected through a small explicit constructor map in the
composition root; do not dynamically load code named by browser/operator strings.
Version persisted input/classification formats and job-policy fingerprints where
compatibility actually matters, not every helper or HTTP endpoint. Unknown fields/
codes fail safely or remain explicit unknowns; migrations never reinterpret old
analysis evidence silently. Generalize only when a second concrete use requires it.

Non-goals for the initial design: microservices, event bus, event sourcing, generic
workflow DSL, dependency-injection container, plugin registry, generic CRUD/repository
framework, separate queue server, per-feature database or an always-on scheduler.
Durable raw evidence and a small explicit job state machine are not event sourcing.

### uv, Ruff and Lefthook — one lightweight quality path

Use uv for the new project's environment, dependency resolution and execution.
`destination-report/pyproject.toml` and `uv.lock` are the source of truth; do not
maintain parallel hand-managed requirements/Poetry/pip environments. Select and
record the tested Python patch and uv version in B1, lock runtime dependencies and
a `dev` group containing Ruff and the official Python-distributed Lefthook. Use one
root `lefthook.yml`, not another Node toolchain or both pre-commit and Lefthook.
This is tooling around the modular monolith, not another architecture layer.

Developer setup is explicit: `uv sync --project destination-report --locked --group
dev`, then install the configured hook using the locked Lefthook executable through
uv. Do not overwrite existing custom Git hooks; inspect/integrate them deliberately
and verify the installed hook works from a fresh shell without a global Lefthook
dependency. No hook is installed during drafting or app startup. A missing/stale
environment fails with a useful setup instruction, not an on-push package download.

Use Ruff for both Python formatting and linting; no Black/Flake8/isort duplication.
Start with stable defaults plus import-order checks, without broad stylistic rule
sets that conflict with formatting. Put configuration in the same `pyproject.toml`.
The owned check scope is application source, tools, offline/runtime test **source**
and deliberately migrated legacy wrappers/helpers; do not discover files in
`PRIVATE*`, secrets, virtual environments, generated reports or build output.
Unrelated legacy scripts are outside initial Ruff coverage; existing checks remain.
Record that scope in Make/config and expand it only when those files are adopted.

Proposed root Make targets (implemented in T00, not commands that exist today):

| Target | Behavior |
|---|---|
| `dev-setup` | Explicit locked uv environment setup; installation/downloads allowed only here or another deliberate dependency update |
| `lock-check` | `uv lock --project destination-report --check --offline`; fails on missing/stale lock without rewriting it |
| `format-check` | uv `run --no-sync` invokes `ruff format --check --no-cache` over the declared owned scope |
| `lint` | uv `run --no-sync` invokes `ruff check --no-cache` over the same scope; no `--fix` |
| `test-offline` | uv `run --no-sync` invokes unittest discovery under `destination-report/tests/offline`, including architecture contracts and selected offline legacy tests |
| `quality` | Run lock check, format check, lint and offline tests, propagating failure |
| `format` / `lint-fix` | Separate explicit developer actions; never run by the hook or stage changes automatically |

For pre-push/manual offline quality checks, set `UV_OFFLINE=1` and
`UV_PYTHON_DOWNLOADS=0`; use the pre-provisioned environment rather than auto-sync.
Verify lock consistency separately; `--frozen` by itself does not check freshness.
Tests may write only their temporary fixture directories, not the live series or
raw exports. Ruff cache is disabled for check commands. Pin tool versions via the
lock and verify flags against those versions rather than fetching tools on demand.

The small root hook delegates to Make rather than copying its commands:

```yaml
pre-push:
  parallel: true
  jobs:
    - name: lock
      run: make lock-check
    - name: format
      run: make format-check
    - name: lint
      run: make lint
    - name: offline-tests
      run: make test-offline
```

All jobs run the full declared owned scope, not only unstaged or last-commit files;
checks are read-only, so parallel execution does not race environment mutation.
Confirm actual nonzero exits block the hook, a clean run passes and neither changes
tracked files. Run `lefthook validate` / `lefthook run pre-push` via the prepared uv
environment for verification, not a real push. Local hooks are bypassable and are
not a deployment/security guarantee. The same `make quality` can be used by future
CI without introducing a second set of checks or a new CI pipeline in this feature.

Do **not** wire existing `make dns-check` wholesale into pre-push: it includes a
running-resolver aggregate sample and Docker-dependent checks. Keep opt-in runtime
tests and manual browser/provider/container validation separate from offline tests.
Unit/adapter contracts use fakes/in-memory transports, not real model/Exa calls.

Docker builds use the same lock: pinned uv builder binary/image plus
`uv sync --locked --no-dev --no-editable`, then run the installed application
directly from the built environment. Do not sync/download on container startup or
ship Ruff/Lefthook in the production environment. Exclude host `.venv`, caches,
private snapshots/reports and secrets from the build context. No change to the
resolver image, service interpreter or existing DNS sampler environment.

## Durable data and snapshot identity

Use one SQLite database and an initial **ten-table model**, owned by `storage`:

| Tables | Contents / owning policy |
|---|---|
| `snapshots`, `dns_rows`, `reports` | Source manifests, preserved indexed raw observations and frozen period/report references (`reporting`) |
| `classifications` | Immutable versioned exact/suffix rules including bounded evidence JSON, scope, verification/expiry and provider/model provenance (`classification`) |
| `analyses`, `analysis_items` | Job identity/state/config snapshot, fixed candidate progress/results and one nullable summary field on the analysis (`analysis`) |
| `call_attempts` | Reservations, dispatch day, measured usage/uncertainty and retry/error outcomes; the accounting source of truth (`analysis`) |
| `inventory_polls`, `device_settings`, `device_bindings` | Timestamped raw device lists/poll errors, append-only manual display/category revisions and trustworthy temporal binding evidence (`inventory`) |

Bounded evidence/result objects and small per-poll client lists can be validated
JSON columns; index only fields needed for scope/time/status/identity queries.
Do not split these into separate rule/version/evidence/summary/device-observation
tables until a real independent query/lifecycle requires it. The binding table may
remain empty: lack of a reliable source must not cause invented attribution.

Compute daily/per-analysis charges from indexed `call_attempts` within the same
`BEGIN IMMEDIATE` transaction that inserts a reservation; no separately mutable
`budget_days` counter to drift. An unconfirmed attempt remains fully reserved.
Store the single final summary on `analyses` using a conditional update only when
its summary is null and state is terminal; no separate summary queue or table.
Keep immutable classification revisions and item result references so later cache
updates cannot rewrite a saved analysis. One explicit SQLite store supplies named
operations, not generic CRUD methods; it owns all SQL and transaction boundaries.
Preserve imported raw JSON files and row identifiers. Qualify source row IDs with
a stable local datasource identity so database restoration/ID reuse cannot conflate
observations. Schema-versioned imports reject mismatched counts/duplicate source IDs.
Application schema migrations never operate on the live FTL database.

24h/48h presets resolve once to explicit bounds; custom dates include a selected
timezone/offset and reject ambiguous/nonexistent local times. Derive a period data
digest from included canonical raw rows, bounds, source identity and interpretation
version, excluding capture time and unrelated rows outside the period. Late persisted
rows produce a new data digest, not a rewrite of an old analysis. Save source
freshness, selected row IDs and source hashes for the period. A page refresh reopens
that fixed report; only explicit period/data refresh chooses a newer snapshot.

An analysis identity includes the period digest, explicit unresolved selection,
analyzer/policy/schema version and non-secret provider/model configuration fingerprint.
Mutable global cache versions and key rotation do not create duplicate analyses.
Copy the classifications/evidence actually used into saved analysis revisions.
Viewing an old analysis must not silently pick up later cache changes.

## Cache, disclosure and grounding

Resolve current reviewed mappings before any external work. Exact rules win over
dot-boundary-safe suffix rules, with most-specific suffix and explicit supported
field scope. Prefer verified/manual rules within the same scope. A provider-only
suffix may fill a provider field but must not invent a service for an unresolved
exact hostname. AI-grounded proposals are distinguishable from human-verified
mappings; source URL presence is not itself verification. Cache successful and
negative/unknown outcomes with checked/expiry dates, evidence/source hashes,
scope, method and model provenance. Default TTLs: 30 days primary reviewed,
seven days secondary/provisional/unknown, configurable. Reanalyze can deliberately
refresh expired/selected unresolved records; no automatic expiry-triggered research.

The local planner ranks unresolved names by DNS rows, without sending those counts.
Use a bundled public-suffix dataset and conservative privacy rules: never send raw
local/reverse names, addresses, UUIDs, long opaque labels, tenant/CDN token prefixes,
device metadata or period timestamps. A broad public suffix candidate is eligible
only for broad claims. Shared/private suffix cases that cannot be safely reduced
remain local unknowns. A local preview lists exactly which public candidates will
leave the VM, exclusions and scope loss; owner confirmation authorizes that fixed
batch. Default-deny suspicious names; allow local per-candidate exclusions.

Workflow is deterministic and bounded, not an agent:

1. Reuse current verified/compatible cached results. Claim the remaining candidate
   tasks atomically; other jobs share completed cache work rather than dispatch twice.
2. Send minimal public namespace/ownership questions to the MCP search tool. Optionally
   fetch only bounded selected public HTTPS source URLs. Never visit an observed
   destination merely because it was queried. No arbitrary URL fetch endpoint.
3. Clip source text/bytes, assign server-generated evidence IDs per candidate and
   record canonical source URL, capture time and content hash. Prefer primary sources;
   lack of evidence stays unknown. The model cannot nominate new tools or fetch URLs.
4. Send small batches containing opaque candidate IDs, approved public names and
   minimal cited excerpts. Treat all excerpts/tool/server instructions as untrusted
   quoted data, separate from the fixed system policy. No raw logs, counts, client
   identifiers, activity dates, secrets or internal storage references go out.
5. Validate strict response schema, exact requested IDs, lengths/enums, evidence IDs
   restricted to that candidate's retrieved set and exact grounding quotations.
   Resolve display URLs from stored evidence, never model-provided links. Reject
   device/activity/duration claims and broad-CDN service guesses. Provider-only,
   application-specific, ambiguous, unknown and excluded outcomes stay distinct.
   Unsupported/free-text semantic claims are not promoted to verified mappings.
6. Commit each result/usage checkpoint before the next dispatch. Render failures or
   budget-deferred candidates explicitly; partial progress remains useful.

## Groq/OpenRouter adapters and model preflight

Use the two-operation `ModelProvider` port above. Adapter-local wire parsing and
usage normalization support it; capability eligibility, prompt/schema construction
and classification grounding stay in their owning feature modules. Configuration
selects exactly one provider per job; optional explicit fallbacks stay within it.
No default model ID or implicit Groq/OpenRouter switching. Snapshot model/config
metadata per job, never secret bytes. Credentials are read server-side from private
secret files, not submitted as browser request fields.

On confirmed Analyze only, consult provider model metadata and bounded capability
cache. Groq documents `GET /openai/v1/models`; OpenRouter exposes catalog/context/
pricing/supported-parameter data. A catalog listing alone is not proof that an
endpoint supports structured classification. Check current text modalities,
context/completion limits and structured-output parameters, then use at most one
budgeted synthetic schema probe per compatible configuration when necessary.
All probes and metadata HTTP attempts are visible in request counters. Do not
mistake one successful probe for a guarantee; validate every real response too.

Prefer supported strict JSON Schema mode. A configured, explicitly supported JSON
object mode can be locally schema-validated; never silently send unsupported
`response_format` parameters or strip grounding requirements. Refusal/truncation/
unavailable capability leaves an unresolved result. The model gets no tool access.

OpenRouter free-only uses explicit free catalog IDs, including every fallback,
and zero relevant pricing verified from current metadata. Disable provider-side
fallbacks by default, require supported parameters, set supported zero price caps,
and disable all optional paid plugins/tools. Do not use `openrouter/auto` or an
opaque router as an implicit replacement. Model IDs ending in `:free` alone are
insufficient proof of present availability/endpoint capabilities/pricing. If no
eligible compatible route exists, stop AI without degrading reports. Recheck
stale capability/price metadata before an attempt and retain actual returned
model/endpoint provenance. No paid fallback, even following 429 or provider outage.

## Exa runtime integration — separate from OpenCode

The user-authorized staged files are an input to the future app configuration, not
a shared OpenCode process/session. Mount only the Exa key read-only; resolve the
staged connection's file reference into a server-side header in memory. Never
copy the whole OpenCode config/auth store, log a key-bearing URL/header, launch
OpenCode in the container or forward its session metadata.

Use the official Python MCP client over the copied Streamable HTTP endpoint.
On explicit Analyze/runtime-test authorization: initialize, discover tools and
validate their actual input/output schemas; select allowlisted search/fetch
capabilities only. Fail closed if schemas or response evidence extraction are
unsupported. The available OpenCode Exa signature is not a deployed-client contract.
Runtime status distinguishes staged credentials, successful handshake/catalog,
successful bounded search and unavailable/degraded. No MCP connection on app boot,
view or DNS/inventory collection. No `agent_run` or model-driven MCP tool loop.

Exa's official docs currently describe keyless limited access and API-key headers;
the copied API-key setup is used here as explicitly requested. Its account usage
and costs remain independent of OpenRouter's free model mode. One application
tool call may include server-side search/content work; app call limits cannot
guarantee a monetary cap on the provider account. Show that distinction and use
provider-account spending controls if a dollar ceiling is required.
Reusing the key shares the Exa account/quota with OpenCode. Application daily
counters cover application dispatches only, not searches made by OpenCode or other
clients; label that scope explicitly and never claim a shared-account spending cap.

## Budgets, concurrency and recovery

Proposed configurable safety defaults (reviewable, not current runtime settings):

| Limit | Per analysis | Per UTC day |
|---|---:|---:|
| Provider HTTP attempts, including catalog/probe/retries | 12 | 60 |
| Total model tokens, conservative reservation + measured reconciliation | 524,288 | 2,097,152 |
| Exa search tool attempts, including retries | 8 | 40 |
| Exa search + fetch tool attempts total | 12 | 60 |
| Public unresolved candidates | 20 | constrained by daily budgets |

Batch size at most four; 2 KiB excerpt per source, at most three sources/candidate,
16 KiB model-request evidence payload, completion cap initially 1,024 tokens subject
to validated model support. Bound MCP protocol/metadata attempts independently.
At most two attempts per operation, connect timeout 5s, total call timeout 30s,
job wall-clock 180s; bounded Retry-After/backoff/jitter for retryable 429/5xx/timeouts.
No SDK hidden retries. 401/403, invalid config/schema and incompatible models do not
retry blindly. Every attempt is reserved/accounted before dispatch.

SQLite `BEGIN IMMEDIATE` atomically claims job/candidate work and reserves both
analysis and day budgets, then commits before networking. One active inference
worker by default; unique job/candidate keys and leases protect simultaneous tabs.
No network operation holds a long database write lock. Dispatch-time UTC day owns
the charge across midnight; unfinished reservations do not disappear on restart.
Persist exact metadata/probe/search/fetch/inference counters, prompt/completion/
reasoning-inclusive usage where available, cache hits, retry/error state and
unconfirmed reservations separately. Monetary estimates are not token/call limits.

Hard tokens require an audited upper bound, not `characters/4`. Where a verified
tokenizer/framing bound is unavailable, reserve the validated model context limit
plus the requested completion cap conservatively; a model too large for available
budget is ineligible until the owner changes limits/model. Require provider output
caps to cover billed reasoning tokens; unknown accounting/caps fail capability
validation. On confirmed usage, release unused reservation; missing/ambiguous usage
keeps the full reservation charged and visible. Never continue after an accounting
contradiction. Model IDs/limits remain configurable rather than assumed constants.

`POST /analyses` carries a frozen local preview token and idempotency key; a UNIQUE
analysis identity returns the existing job/result on double-click or repeated POST.
`POST /analyses/{id}/reanalyze` consumes a distinct local confirmation nonce to create
exactly one new revision, not an implicit refresh. Resume reuses the existing job
and durable checkpoints. After restart/interruption, mark paused and require an
explicit Resume/Analyze; do not make external calls on startup or page load.
No local design can promise exactly-once remote execution after a response is lost;
record uncertainty and budget every retry, never claim no upstream duplicate cost.

At completion, conditionally save one deterministic plain-language summary on the
unique analysis row only if its summary is still null and its state is terminal.
Compose it locally from validated classifications and locally computed coverage/counts;
no extra model request and no raw-period or device disclosure. Partial terminal
analyses say partial; interrupted ones show progress, not a fabricated final summary.

## Inventory, presence and strict attribution

Existing evidence confirms nine successful inventory snapshots spanning 120 seconds
with ten CLIENT records and one CONTROLLER; it does **not** validate connect/disconnect
semantics. Wi-Fi association counters, intermittent `active`, DHCP flags and wired
omissions differ. Retain source timestamps/poll errors/default-field uncertainty.
Do not backfill 24/48-hour presence from a current snapshot or lease.

Normalize a local device observation identity from MAC/client ID with collision,
randomized-MAC and stability warnings, not a claim of physical-device uniqueness.
Display observed name/given name/IP/MAC, role/interface and supported metadata.
Manual name/category overrides win for display and are audited with provenance;
they never rewrite raw names, historical IPs or create identity bindings. A local
vendor/OUI hint is vendor-only, not an OS or device category. Categorization requires
reviewed supported device metadata or an explicit manual correction; default unknown.
No AI/external lookup receives device names/MACs or invents categories from domains.

Timeline states are `listed`, `not_listed_in_successful_poll`, `monitoring_gap` and
`unobserved`, with raw activity/association/lease signals as details. Successful
absence is not confirmed disconnection. Show no history outside collected intervals,
poll precision and transition-semantics-unvalidated notice. Filter infrastructure
roles separately, without silently deleting controller/repeater observations.

DNS binding records require explicit trustworthy source evidence with valid-from/
valid-until interval, identity scope, absence of conflicts and source provenance.
Current IP, adjacent polls and leases alone never create historical binding windows.
The current available feed is expected to leave almost all DNS unattributed; do
not manufacture an attribution-capable source. Provide a device DNS filter only
when actual included rows pass that gate. Router requester is always
`Household — device unknown`; loopback/local-resolver and unmapped direct-IP scopes
are distinct. Summed attributed/unattributed counts include every selected row.

## UI, access control and failure behavior

Server-rendered Jinja2 plus small local vanilla JS/CSS: no build tool, CDN assets or
third-party telemetry. Main mobile view shows local period controls, summary,
recognizable services vs infrastructure/provider roles, search/category filters,
query-count timeline and two-denominator classification coverage. Expand a service
to independent domains and evidence; do not merge different services by a shared
parent/CDN. Put raw JSON/status codes/health diagnostics behind local Details.
Inventory is a separate view even when no DNS device filter can be offered.

Analyze previews uncached count, approved public candidate list, provider/model
validation status and exact configured/remaining budgets; priorities reflect local
row counts. Confirm Analyze, Resume and Reanalyze are explicit protected actions.
Disable double-click locally but rely on database idempotency, not the button.
Job polling/status reads make no model/search calls. Display unresolved causes,
actual provider/model, evidence dates, cached/provisional/verified state and separate
model/Exa usage. AI unavailable means usable cached/unclassified reports, not a
spinner blocking the page. Search/filtering/timeline rendering stay local.

Protect all private views with local owner authentication using a server-side
password hash, secure session cookie, SameSite, CSRF token and Origin checks for
mutations, including job creation and manual device edits. Restrict Host/CORS,
request sizes and download paths; escape AI/source/device content and apply CSP.
Allow only approved provider/MCP endpoints server-side with TLS validation and
redacted errors. No arbitrary proxy/URL field. Do not expose prompts/headers,
credential references or raw diagnostic exceptions in browser responses.

Initial Compose bind is loopback-only on an unused port (proposed 127.0.0.1:8787),
not DNS/admin ports. Use application-owned TLS material and SSH forwarding for
remote review; never mount Pi-hole's TLS/config files. A non-root container has
read-only rootfs, dropped capabilities, bounded memory/CPU/logs, read-only snapshot
and secret mounts, and one private state volume. Provider internet egress is needed
but not host networking. WAN/LAN publication and changes to current guards/relay
are out of scope. Stopping only this Compose project rolls back the app; DNS keeps
running and its pilot configuration/observation loop is independent.

## Affected components, specialists and verification

Reuse `dns-pilot/destination_report.py`, observation extraction/tests and
`investigate_readonly.py` behavior without overwriting private evidence. Use the
module map above under `destination-report/src/household_report/`; do not create
the former independent `snapshots`/`attribution`/`privacy`/`budgets`/`jobs` layers by
default. Keep extraction/query interpretation in one shared implementation and
retain the proof-of-concept CLI compatibility tests. Keep current tests passing.

Boundary verification is part of implementation, not merely naming directories:
pure policy tests need no model/MCP/web imports or credentials; feature/storage
tests use real small SQLite fixtures; adapters run the same port conformance tests
against fake endpoints; web tests inject feature entry points rather than vendors.
Add a small stdlib AST/import-boundary check for the allowed dependency direction
and a test that reporting/inventory imports work with AI integrations unavailable.
No new architecture-lint framework. End-to-end network spies verify that viewing,
filtering, polling status and startup perform no model/MCP calls. Batches deliver
working vertical slices through these boundaries, not empty layers or placeholder
interfaces for all possible future integrations.

Principal installed guidance: `backend-security-coder` (loaded for this draft) for
authenticated mutations, secrets, external inputs, budgets and endpoint boundaries.
At authorized implementation, load `test-driven-development`; `mcp-builder` for the
MCP protocol boundary, `ui-ux-designer` for mobile evidence flow, and `docker-expert`
only for packaging. These are main-agent skills, not delegated agents. No React,
Kubernetes, Node backend or paid model specialist is appropriate.

Tools: local read/grep/glob (no CodeGraph index); Python/unittest and existing Make
gates; official provider/MCP docs for concrete compatibility facts; Chrome DevTools
for accessible mobile/local-network assertions; Docker/Compose for isolated tests
after authorization. Runtime tests use a synthetic public domain, not raw household
history, and consume the configured budgets. No automatic dependency installation,
credential discovery outside the specifically authorized Exa copy, provider calls,
new collectors or app starts during drafting.

Required adversarial checks: page loads/filters/polls make zero external calls;
two tabs/double clicks/retries/restarts/midnight cannot evade budget/idempotency;
model and tool metadata drift; paid fallback rejected; unknown token bounds blocked;
schema/source-ID/quote injection, invented domains/actions, shared CDN ambiguity,
SSRF and tokenized-name leakage; stale cache and partial-result persistence;
snapshot/row/outcome reconciliation; device IP reuse/conflicts/current-lease-only
bindings rejected; missing polls distinct from absence; auth/CSRF/secrets isolation.

## References and unverified assumptions

- https://docs.pi-hole.net/database/query-database/
- https://raw.githubusercontent.com/pi-hole/FTL/v6.8/src/enums.h
- https://raw.githubusercontent.com/pi-hole/FTL/v6.8/src/api/docs/content/specs/queries.yaml
- https://console.groq.com/docs/models
- https://console.groq.com/docs/structured-outputs
- https://openrouter.ai/docs/guides/routing/model-variants/free
- https://openrouter.ai/docs/guides/features/structured-outputs
- https://openrouter.ai/docs/guides/routing/provider-selection
- https://docs.exa.ai/reference/exa-mcp
- https://github.com/modelcontextprotocol/python-sdk
- https://opencode.ai/v2/docs/mcp-servers (used only for the requested Exa copy)
- https://docs.astral.sh/uv/concepts/projects/sync/
- https://docs.astral.sh/uv/guides/integration/docker/
- https://docs.astral.sh/ruff/formatter/
- https://lefthook.dev/configuration/jobs/
- https://lefthook.dev/installation/python/

Docs confirm distinct structured-output support and free-mode fallback risks; they
do not validate a currently selected account/model or an application/container MCP
connection. A requested OpenRouter model-catalog reference fetch timed out; use
actual metadata/official API documentation during adapter implementation, not
invented catalog field guarantees. Per-domain evidence stays in the private cache,
not a committed household destination inventory.
