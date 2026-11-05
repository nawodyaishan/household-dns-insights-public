# Household destination dashboard and on-demand analysis — spec r3

## Outcome, sources and revision boundary

Provide a mobile-first, locally hosted view of existing DNS observations, a separate
evidence-based device inventory, and explicitly triggered, budget-limited destination
classification. Normal reporting must not depend on AI or external research.

Sources: the user's successive 2026-10-23 destination-report, proof-of-concept and
Groq/OpenRouter/Exa/dashboard/device requirements; `../../README.md`;
`../001-dns-monitoring-pilot/spec.md#follow-on-scope-not-implemented-by-this-pilot`;
`../../dns-pilot/OPERATIONS.md`; `../../docs/investigations/STARLINK-DESTINATIONS-AND-PRESENCE-REPORT.md`
sections Device presence assessment and Polling observations. No separate SRS,
high-level technical specification or global roadmap exists; retain those existing
source paths. The one-hour proof of concept remains private evidence, not a deployed
application. R2 materially replaces r1's job-only/no-runtime-AI design.
R3 responds to the owner's request for a more modular, expandable design without
overengineering. Product scope and privacy/cost/attribution guarantees are unchanged;
the revised module boundaries, contracts and lean persistence design are in plan.md.
The owner's follow-up tooling requirements add uv dependency/environment management
and Lefthook pre-push formatting/lint checks, without changing deployment authority.

## Actors and privacy boundary

One authenticated local owner views reports, edits local device names/categories and
authorizes Analyze/Reanalyze. Provider/model/MCP configuration and credentials are
server-side operator settings, never browser-supplied keys or arbitrary URLs.
Full DNS rows/subdomains, observed IP/MAC/name/IDs, detailed activity timestamps and
presence data remain local. External requests may contain only approved public
namespace candidates and bounded source evidence, not counts or private raw arrays.
Sensitive/tokenized/local/reverse/opaque tenant components are removed or excluded;
if reduction loses service specificity, preserve an infrastructure-only or unknown
outcome instead of assigning that service to every subdomain.

## Acceptance criteria

### Local observations and reporting

- **A1 — Immutable evidence:** consistent SQLite export, fixed `[start,end)` UTC
  bounds and content-addressed source snapshot; totals/IDs reconcile. Preserve every
  row, full available query-view columns and fractional timestamps. Keep raw evidence
  out of the main reading flow, but accessible in authenticated local diagnostics.
- **A2 — Presentation:** mobile-first local-time dates (default UTC, explicit
  offset/zone shown), 24h/48h/custom windows, local search/category filters,
  query-count timelines and expandable exact-domain evidence/outcomes. First/last
  refer only to observed query times. Reverse lookups/protocol names and suspected
  probes stay separate/visible, never subtracted or falsely deduplicated.
- **A3 — Honest coverage:** show retained bounds, source freshness, persistence lag,
  collection errors/gaps and bypasses. Quiet bins are not outages or inactivity.
  Classification coverage reports distinct-domain and DNS-row denominators, with
  service-specific, provider/infrastructure-only, ambiguous, unknown and excluded
  buckets distinguished. Device-attributed/unattributed row counts reconcile to all
  included observations, with router-forwarded rows explicitly device-unknown.
- **A4 — DNS semantics:** keep status, reply type and unknown numeric values;
  statuses 14/17 are not automatically failures. Retain timestamp-based 60-second
  rates where displayed, not average-derived limiter headroom. Never claim unique
  connections/sessions, successful transport, user actions or usage duration.

### Bounded external classification

- **A5 — Explicit trigger only:** no inference, search, model discovery/probes or
  runtime-MCP connections on page load, refresh, filters, DNS collection or inventory
  polling. Analyze first shows a local-only preview: fixed snapshot/period, uncached
  candidates, proposed public disclosure, provider/model and available limits. Only
  authenticated confirmation starts external work. Reanalyze is separate and explicit.
- **A6 — Cache and identity:** current verified mappings first, exact-match precedence
  and dot-boundary-safe scoped suffixes; expired/unsupported mappings stay explicitly
  unresolved. Reuse classifications across reports. Analyze new or explicitly selected
  unresolved candidates by descending local DNS-row count. The same snapshot/period/
  selection/configuration returns its saved analysis without calls. Duplicate clicks,
  simultaneous tabs and concurrent jobs cannot duplicate the same local analysis or
  candidate work. Changed global cache must not rewrite a saved analysis.
- **A7 — Provider selection:** one configured provider (Groq or OpenRouter) per job;
  model IDs and optional same-provider fallback list are configurable. Validate model
  existence, text input/output, context/output limits and structured-response behavior
  using current provider metadata and a bounded synthetic probe when needed. No
  hardcoded availability claims or automatic cross-provider switch. No valid model
  means AI disabled, not failed ordinary reporting.
- **A8 — Free-only:** OpenRouter free mode accepts only explicitly selected free
  catalog entries with verified zero relevant prices and compatible endpoints; every
  fallback must pass the same checks. Unknown pricing/route support fails closed.
  Never route to paid models, generic paid-capable auto routers, paid plugins or
  silently substitute a paid endpoint. Show actual selected/returned model provenance.
- **A9 — Application Exa MCP:** the backend owns a separately configured MCP client
  and explicitly tests its transport/auth/tool schemas in its runtime environment.
  OpenCode's MCP connection is not proof. Only bounded search/fetch tools are used;
  no autonomous agent loop, arbitrary tools or model-directed fetches. Exa has separate
  call/cost constraints independent of free inference. Unsupported runtime access
  leaves unknowns and usable reports, with a clear status.
- **A10 — Structured grounding:** service/provider, application-vs-infrastructure
  role, category, evidence references, confidence and ambiguity are schema-validated.
  Evidence IDs must belong to that candidate's retrieved source set; URLs cannot be
  invented by the model. Grounding quotations must match the retrieved bounded text.
  Source existence/schema validity does not alone make a mapping verified. Unsupported
  claims, shared-CDN service guesses, extra domains, device/activity claims, refusals
  and invalid/truncated output remain unresolved, with a reason. Retrieved text is
  untrusted data, never instructions; the model gets no tools, credentials or shell.
- **A11 — Hard budgets:** persist per-analysis and UTC-day request/token reservations
  before dispatch, atomically across concurrent work. Retries, capability probes,
  timeouts and uncertain outcomes consume limits; Exa search/fetch budgets are separate.
  Bound input/output, evidence bytes, domains, batch size, timeouts, attempts and job
  duration. No call occurs without a sufficient conservative reservation. Missing
  usage keeps the reservation charged; distinguish measured from reserved usage.
  Stop gracefully with partial results and explicit budget-deferred unknowns.
- **A12 — Recovery/summary:** persist each evidence/classification result before the
  next item. Interrupted jobs pause for explicit Resume/Analyze; no startup/network
  replay. Resume does not repeat checkpointed completed work. Remote exactly-once
  execution is not promised after ambiguous network failures. At most one saved,
  plain-language summary per finished analysis, generated locally from validated
  results and local aggregates, with no extra model call or raw-period disclosure.
  Show partial/unresolved status, classification provenance and separate provider/
  Exa usage, including cache hits, retries and conservative reservations.

### Inventory and attribution

- **A13 — Local inventory:** import existing Starlink polls and optionally collect
  new bounded read-only `wifi_get_clients` observations, separately from the live DNS
  sampler. Show observed device name/IP/MAC, role/interface and supported metadata,
  collector first/last observation times and only actually collected history. Manual
  name/category overrides are local, auditable, reversible and distinct from raw data.
  Hardware/router identity or reviewed metadata may support a category; a hostname
  guess or OUI alone cannot prove an operating system or product class. Uncertain
  devices remain unclassified; controllers/repeaters are not household endpoints.
- **A14 — Presence uncertainty:** listed/not listed, association/activity/lease
  observations and failed/missing polls are separate states. No single missed row,
  API failure or live lease establishes offline/online state. No backfilled history,
  confirmed connect/disconnect ledger or OS uptime claim from currently unvalidated
  Starlink flags. Gaps are explicit, with polling precision and source uncertainty.
- **A15 — DNS attribution gate:** offer a device DNS filter only for observations
  backed by reliable, non-overlapping, time-valid requester-to-device binding evidence.
  A current inventory IP, lease flag, timing overlap, repeated sightings, domain name,
  manual naming/category or AI output alone is insufficient. Router-forwarded queries
  remain **Household — device unknown**, even when an inventory entry identifies the
  router. Other direct requester IPs without such evidence remain unattributed. Show
  the inventory independently when no destination attribution is available.

### Availability and deployment boundary

- **A16 — Isolation:** do not change or restart the resolver, observation sampler,
  DHCP, device DNS, blocking, firewall, routing/topology or retention to gain features.
  No report-container Docker socket, live Pi-hole volume/admin credential or host
  networking. Use separate private application storage and bounded read-only exports.
  AI/MCP failures cannot disable ordinary reports or DNS collection.
- **A17 — Access/secrets:** protect private views, mutations and Analyze with local
  owner authentication, CSRF/origin checks, strict schemas, escaping and private logs.
  Secrets live in ignored owner-only operator files/secret mounts, never source,
  browser configuration/responses, URLs, stack traces or prompts. Initial server
  access is loopback-only through an SSH tunnel. LAN publication/TLS/firewall changes
  and starting new collectors require separate explicit execution authorization.
- **A18 — Maintainable boundaries:** reporting and inventory remain usable and
  testable without provider credentials, MCP packages/connections or live services.
  Adding a model provider must not require changes to reporting, device attribution
  or database accounting rules. Provider/research integrations use small explicit
  contracts; all external dispatch shares the same budget/authorization gate.
  Domain policies have deterministic offline tests, and dependency-boundary checks
  prevent read-only views from acquiring external-call capabilities. Do not introduce
  distributed services, plugin/workflow frameworks or duplicate business-rule layers
  merely for possible future expansion. Detailed layout remains a plan decision.
- **A19 — Reproducible, safe developer checks:** manage the new Python project with
  uv, a committed `pyproject.toml`/`uv.lock` and a documented tested interpreter/tool
  version. Lefthook pre-push must block on formatting, lint, lock-consistency or
  offline-test failures using the same Make targets available manually. Checks must
  not auto-fix/stage files, change dependencies/lockfiles, install/download tools,
  contact AI/Exa, require a running resolver/Docker or touch real private evidence.
  Explicit developer setup/fix commands are separate. Scope and legacy coverage
  must be stated; do not silently reformat unrelated scripts or replace custom hooks.

## Exclusions

No DHCP/device DNS/topology changes, endpoint agents, browsing reconstruction,
packet interception, device identification from AI/destinations, presence-as-uptime,
retry subtraction, paid-model fallback in free mode, open-ended agents, autonomous
research on view/refresh, raw-log export to providers, public service exposure,
Redis/database server, frontend build framework or reboot tests. Runtime credentials
and deployment are operational gates, not inferred from an implementation request.

## Combined approval

Decision: **approved** for spec r3, plan r3 and tasks r3.

- Actor: repository owner (human, this session).
- Date: 2026-10-23.
- Evidence: owner message "i approve chanegs" (verbatim, repeated twice) after the
  r3 set was presented; the drafts were already published in commit `f63b4d2`.
- Scope approved: spec r3 A1–A19; plan r3 module map, two external ports, ten-table
  model, uv/Ruff/Lefthook tooling and runtime gates; tasks r3 T00–T16 with batches
  B1–B4.
- Not approved by this decision: any live deployment, resolver/sampler change,
  migration of the live FTL database, prospective device polling, credential
  provision, or actual paid/free provider and Exa calls. Those keep their separate
  operational authorization gates in plan.md and tasks.md.
- Batch state: B1 (T00–T04), B2 (T05–T09), B3 (T10–T13) and B4 (T14–T16) were
  authorized separately by the owner in this session and are recorded with their
  evidence in `tasks.md`. B4 authorization: owner message "proceed to b4" on
  2026-10-23 (this session).
- B4 scope approved: packaging only — one non-root loopback-only image from the
  existing uv lock, Compose isolation, and explicit host snapshot/presence commands
  that use the shared import contracts, plus their offline tests and docs.
- B4 scope **not** approved by that message: any provider/Exa call or spend, a change
  to credential file permissions, prospective device polling, LAN/WAN exposure, or
  migration of the live FTL database. T15 still needs the exact model ID, a `0600`
  credential, and an explicit runtime/spend authorization; T16 still needs the
  owner's approved domains and an explicit start.

An agent verdict is not part of this record, and this section remains the single
approval location; plan.md and tasks.md reference it rather than holding their own
flags.
