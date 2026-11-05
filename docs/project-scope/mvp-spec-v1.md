# MVP specification v1 — Targeted household gaming observation

Updated: 2026-10-24. Status: **draft v1 for future planning**, informed by source-code review and targeted research. Documentation is requested; implementation, participant recruitment and deployment are not authorized by this document. Canonical location: `docs/project-scope/mvp-spec-v1.md`. This is project-wide future scope, separate from the numbered spec-driven implementation flow.

> **Superseded baseline (2026-11-02).** This MVP draft predates the implemented
> campaign/reporting system: campaigns, frozen reports, coverage states and the
> stack lifecycle now exist under features 005/006. For the implemented system
> use [`docs/reference/current-architecture.md`](../reference/current-architecture.md)
> and [`docs/operations/`](../operations/); treat this document as future scope
> only, not a description of current behavior.

**Approved initial-stage direction (2026-10-25):** for this household deployment, the owner approved the entire existing web interface and its actions without login at a simple local HTTP IP:port, avoiding domains, per-device certificates and new authentication. This supersedes the protected-owner/TLS assumptions in §§4, 7 and 9 below **only for the opt-in 005 shared-control profile**. See the [005 r3 access amendment](../../specs/005-continuous-household-reporting/spec.md#r3-access-amendment--approved-for-offline-b5a) for exact scope, exclusions and risks. The owner authorized offline B5A implementation, **not** live deployment or campaign start. No clinical/participant use is authorized by this initial-stage relaxation.

The intended use is a **targeted 3–5-day observation campaign** when a family is concerned about possible unreported gaming or problematic gaming by a household member. A prior diagnosis is not assumed. During the campaign, the project captures available household DNS observations and provides **a button that generates a report of gaming-related signals, readable by everyone on the intended local network**. It is not intended to run indefinitely or require weeks of monitoring. Household-level visibility is sufficient for this MVP; the data cannot establish who played, whether a game ran, playing duration or addiction.

This replaces the earlier future-work document and speculative discussion, preserved privately. Its deployment commands, clinical/compliance assertions, customer metrics and advertised capabilities are not verified facts.

Owner-supplied infrastructure assumption: **backup DNS is provided through the Starlink router**. DNS continuity, backup configuration, failover correctness and DNS-service shutdown behavior are outside this MVP. They were not verified in this review. When queries use another resolver, the report must reflect limited observation coverage rather than infer no gaming.

### Direction verdict

| Question | Assessment | Planning consequence |
| --- | --- | --- |
| Can the existing stack deliver the proposed report? | **Practical, with bounded implementation work.** Extraction, storage and a gaming view already exist; campaign jobs, multi-window reporting and LAN publication remain. | Reuse the current application, validate one closed chunk first, then deliver the complete 3–5-day campaign with AI off. |
| Can it reliably detect all gaming or identify who played? | **Not established and not supported by DNS alone.** Household forwarding removes requester identity, and some gameplay has no corresponding lookup. | Describe recorded signals and their missing coverage. Do not promise complete activity detection. |
| Does it have mental-health research value? | **Plausible as an adjunct for voluntary reflection and discussion; benefit is unproven.** | Study measurement validity, acceptability and added value beyond a diary before testing health outcomes. |
| Is it ready to diagnose gaming disorder, flag relapse or demonstrate recovery? | **No.** Those outcomes require clinical information and validation that this project does not have. | Keep diagnoses, risk scores and relapse alerts outside the MVP. |

The proposed research question is: **Does a consent-based 3–5-day household DNS report add useful, correctly interpreted context to a participant's diary and clinician-led discussion, without increasing misunderstanding, monitoring burden or family conflict?** This is a testable hypothesis, not a demonstrated benefit. Section 8 provides the evidence and study design; section 9 covers VM operations and the dashboard; section 10 records collaboration decisions.

## 1. Evidence and freshness

This revision inspected the checked-out export/import tools, query extraction, report assembly, gaming projection, web routes and Compose configuration, alongside dated reports and task ledgers. Exa MCP located primary Pi-hole documentation and Mozilla's encrypted-DNS documentation. Searches used generic technical topics; no household domains, timestamps, identities or records were disclosed.

The subsequent mental-health review used Exa MCP for six targeted searches (28 returned result slots, including duplicates) and retrieved seven selected primary guidance/research sources. It covered diagnostic meaning, objective gaming measures, DNS/network detection, family care, direct DNS clinical validation and digital-tool evaluation. This is a targeted feasibility review, not a systematic review or proof of novelty. No direct validation of this household DNS approach for diagnosis or relapse detection was identified in those results; absence in this search is not proof that none exists.

No live resolver extraction, presence poll, classification run, deployment or network change was performed for this revision. Current health, retained bounds and production rules must be checked before implementation. The 284 offline tests and three container checks are results recorded in the [004 task ledger](../../specs/004-gaming-web-view/tasks.md), not tests rerun here.

The existing [005 draft](../../specs/005-continuous-household-reporting/spec.md) reports a healthy resolver, a saved one-hour/82-row example, no installed household reporting state, no production namespace file and no grounded gameplay/matchmaking result. Those are the draft author's observations, not reverified here. Its assertion that the app was never packaged conflicts with documented synthetic packaging checks: distinguish **tested packaging** from **household installation and deployment**.

## 2. What the sources actually provide

| Source | Obtainable information | How and when | Evidence and limits |
| --- | --- | --- | --- |
| Pi-hole FTL query database | Timestamped domain lookups and DNS handling metadata | Existing host-side read-only extraction of persisted history | CONFIRMED in earlier saved evidence. This is the MVP destination source; current retained coverage needs checking. |
| Saved snapshot JSON and application SQLite | Exported observations, metadata, saved classifications and local usage ledger | Offline import/read after export | CONFIRMED in code and prior evidence. Existing files do not establish continuous 24/48-hour coverage. |
| Aggregate observation sampler | Counts, distinct-domain totals, retained bounds and health/error samples | Existing sampler was configured for 15-minute samples over 48 hours | Cannot reconstruct the underlying domain names or individual query timestamps. A bounded sampler is not a permanent reporting collector. |
| Starlink `wifi_get_clients` | Inventory, interfaces, roles, lease and association fields | Explicit read-only polling; existing tool defaults to nine samples 15 seconds apart | Inventory historically CONFIRMED; connection/disconnection transitions remain UNKNOWN. Unnecessary for this gaming MVP. |
| Starlink `get_connections` | No usable household flow history demonstrated | Previous bounded router/dish calls returned UNIMPLEMENTED | NOT OBSERVED. Reflected service addresses are not established household destinations. |
| Starlink `wifi_get_firewall` | No accessible readout in the previous test | Previous call returned PERMISSION_DENIED | ACCESS DENIED. Even readable firewall rules would not establish historical contacts. |

See [the investigation report](../investigations/STARLINK-DESTINATIONS-AND-PRESENCE-REPORT.md) and [resolver operations](../../dns-pilot/OPERATIONS.md). The original investigation predates the authorized DNS pilot; the absence of a router destination feed does not contradict later Pi-hole observations.

### Exact DNS fields and usable meanings

The current [`extraction_query()`](../../destination-report/src/household_report/reporting.py) selects these fields from FTL's `queries` view. Selected optional columns may be null; presence in code does not establish population in every installed version.

| Field(s) | Useful interpretation | Unsupported interpretation |
| --- | --- | --- |
| `id` | Query identity within a source database generation | Globally unique event across database resets |
| `timestamp` | Query arrival at FTL; first/last observed query and timeline bins | App launch, session start/end or play time |
| `domain` | Requested name, normalized for grouping with original rows preserved | Visited URL, page content or successful contact |
| `type` | DNS record type, including forward/reverse queries | Transport protocol or game action |
| `status`, `reply_type` | Resolver handling and response category, kept separately | Successful application connection or login |
| `client` | Requester visible to Pi-hole | Original household device on the current forwarded path |
| `forward` | Upstream DNS resolver used, when populated | Remote game server contacted by a household device |
| `reply_time` | DNS response timing | Game latency, session length or playing duration |
| `additional_info`, `list_id`, `ede`, `dnssec` | Optional DNS diagnostic/context fields preserved privately | A general destination IP/port, packet or byte history |

The documented path makes the router the apparent requester. Report scope must remain **household / device unknown**. Correlating inventory by time does not recover the missing original requester. A reply category meaning “IP record” is not the actual returned address; these rows do not provide complete answer-address or network-flow history.

Pi-hole's [query-database reference](https://docs.pi-hole.net/database/query-database/) documents arrival timestamps, the query view, DNS metadata, periodic persistence and age-based retention. The exporter includes additional version-specific fields, so check the installed schema before relying on them.

### How and when extraction works

The checked-in [pilot configuration](../../dns-pilot/compose.yaml) sets a 60-second persistence interval, seven-day query retention, privacy level 0 and blocking off. These are configured values, not fresh runtime measurements. Hidden or expired history cannot be recovered later; see [Pi-hole privacy levels](https://docs.pi-hole.net/ftldns/privacylevels/).

The existing [export tool](../../destination-report/tools/export_snapshot.py):

1. Accepts explicit `[start, end)` bounds, at most one hour wide, ending at least 60 seconds ago.
2. Executes a bounded `PRAGMA query_only=ON` read through `docker exec`, without restarting or modifying FTL.
3. Preserves rows, capture time, retained bounds, window count and preceding-minute rate context.
4. Writes a new private JSON file and refuses to overwrite earlier evidence.
5. Leaves loading into the application to the separate, idempotent [import tool](../../destination-report/tools/import_inputs.py).

Example proposed flow: at 14:07 UTC, request the complete 13:00–14:00 hour. An unsettled interval should show “waiting for persisted data.” The current 60-second minimum is not a guarantee that every row has persisted. Validate a conservative capture grace, such as 120 seconds, against actual FTL behavior before choosing it. Reconcile late rows explicitly; do not overwrite preserved evidence silently.

Two important gaps exist today: the exporter rejects zero-row windows, and report assembly returns no report when there are no rows. Add separate states for a successful empty read, failed read, expired/unavailable history and partial coverage. An oldest/newest row or quiet minute does not prove uninterrupted logging. Successful extraction establishes what the database contained at capture, not that every household lookup reached it.

Backfill is possible only while source rows remain retained. Campaign reports must combine closed chunks across up to five days; seven-day resolver retention is not seven days of imported coverage. The present general reporting limit is 48 hours, so a five-day campaign needs an explicit extension or correctly combined daily views. Exported files and imported rows need their own retention policy: resolver expiry does not delete those copies.

### What remains invisible or ambiguous

Only queries reaching Pi-hole are observable. Device/router caches and already-established connections can allow gaming without a new visible lookup. Alternate DNS, external DoH/DoT, VPN DNS, cellular paths and some privacy services can bypass this resolver; the exact effect depends on device settings. Mozilla explains that [DoH can use a remote resolver instead of local DNS infrastructure](https://firefox-admin-docs.mozilla.org/reference/policies/dnsoverhttps/).

Pi-hole's own cache is different: a query reaching Pi-hole and answered from its cache can still be recorded. Repeated queries and retries also mean row counts are not measures of gaming intensity, players, matches or connections.

“Monitor any gaming-related activity” is the aspiration. The supportable MVP promise is **report observed gaming-related DNS signals, with explicit coverage limits**. Complete gameplay detection is not achievable from the current source alone.

## 3. What the application already does with the data

```text
Queries reaching Pi-hole -> persisted FTL rows
  -> explicit host export -> private snapshot JSON
  -> explicit application import -> SQLite
  -> counts, grouping, timeline and saved evidence
  -> authenticated loopback report / CSV / JSON
```

| Component | Implemented behavior | Remaining limitation |
| --- | --- | --- |
| Export/import | Read-only source extraction, preserved files, idempotent import | Manual; opening or generating a web report does not currently collect fresh source data |
| General report `/` | Snapshot, 24h, 48h and custom windows over stored imports | Selecting a period does not collect missing history; overlapping captures need explicit duplicate handling |
| `/gaming` | Newest closed saved snapshot, at most one hour; filters, counts, timeline and exports | No rolling multi-hour gaming view; useful matches require rules or qualifying saved model results |
| Reviewed namespace predicate K | Exact/longest-boundary suffix matches of observed names to reviewed game/platform groups | No bundled production list; a publisher/CDN namespace does not establish endpoint purpose |
| Saved-model predicate M | A current eligible v2 grounded `gameplay_matchmaking` proposal can independently select an observed name | Downloads/updates and other roles cannot independently select M; proposals remain labelled as proposals |
| Analysis workflow | Local preview, explicit confirmation, bounded Exa/model calls, strict grounding, saved results and ledger | Can return unknown; does not discover household traffic or prove gameplay |
| Packaged app | Existing Python/Jinja app, isolated Compose service; synthetic runtime checks recorded | Host publication is `127.0.0.1:8787`, with TLS and authentication; other LAN devices cannot use it as configured |

K and M remain independent evidence bases; count their union once. A reviewed namespace may surface launcher, update, authentication or telemetry signals without implying gameplay. Missing/invalid rules, valid-empty rules, no qualifying results and no matching observations are different states.

Use the existing private `HR_INPUT_DIR/gaming-namespaces.json` schema documented in [004's plan](../../specs/004-gaming-web-view/plan.md) and implemented in [gaming.py](../../destination-report/src/household_report/gaming.py). No new “gaming table” is needed. Retain unknown/shared-infrastructure counts and distinguish namespace association from endpoint role.

## 4. Campaign and trigger-to-report requirements

There are two explicit actions: the owner **starts a 3–5-day campaign**, and a LAN visitor clicks **Generate report** during or after it. Automatic suspicion detection and notifications are outside v1. Concern about private gaming motivates the request; it is not a diagnosis or a reference label for validation. Clinical/research participation requires the consent arrangements in section 8.

1. **Start:** the owner chooses 3, 4 or 5 days, with 3 days as the proposed default. Save a campaign ID, UTC start/end, displayed local timezone, rule revision and status. Default collection is prospective and restricted to these bounds; importing earlier history is a separately explicit selection, never automatic.
2. **Capture:** preserve/import closed chunks on a schedule while the campaign is active, including if nobody opens the page. Use one-hour chunks with a validated settling grace. Keep last successful progress and missing intervals durably. Clip first/final chunks to campaign bounds; never include earlier household rows merely to fill a clock hour.
3. **Open:** anyone on the intended LAN opens the local page without a viewer login. Show campaign dates, remaining time, capture/import freshness, available bounds and gaps. State “Household DNS observations; device and player unknown.”
4. **Generate:** offer campaign-to-date and completed-day reports; optional last-24/48-hour views remain within campaign bounds. A bounded job finishes eligible local capture/import work and pins the report's actual covered end. Repeated requests reuse the same result. Show queued/running/ready/failed status; do not pretend the settling interval is already captured.
5. **Inspect/export:** group observed names by reviewed game/platform association, with query counts, first/last query, a timeline, DNS outcomes, evidence basis and unknown coverage. A download-related lookup does not prove a download. CSV/JSON follows the same frozen projection. No matches means “No gaming-related DNS signals matched the current rules in the observed data,” not a finding about a resident's behavior.
6. **Finish:** stop extending observation at the recorded deadline, complete a bounded final capture after the settling grace, then mark the campaign complete or complete-with-gaps. Reports remain available for the agreed retention period. Booting after the deadline must not silently create a new campaign or extend the old one. Early finish and explicit extensions within the five-day cap update the recorded bounds.
7. **Optional research:** unresolved public names may be reviewed through a protected owner flow with exact candidates, disclosure and budget. Local report generation must work with AI off.

The whole campaign, including all five days when selected, is the MVP delivery target. A one-hour report is an implementation milestone only. Persistent scheduled capture for a few days is required; permanent monitoring, continuous device-presence polling and weeks-long collection are not.

Distinguish **campaign duration**, **retention of saved reports**, and **whether the web service is running**. Ending capture can leave the frozen report readable. The owner separately stops the reporting service after review; retention/deletion policy must be agreed before deployment. Existing resolver logging outside the campaign is infrastructure behavior and is not reconfigured by this specification.

### Open LAN viewing and protected owner controls

Open household viewing is a deliberate change to the current authentication boundary. Add a household report surface; do not make inventory, diagnostics, settings or provider controls anonymous.

| Audience | Proposed access |
| --- | --- |
| Everyone on the intended household LAN | Read household gaming reports, request bounded local generation, download that same report projection, without login |
| Owner | Configure rules/providers, inspect raw evidence/device inventory, and confirm external research through protected controls |

This shares displayed domain observations with those LAN users; make that sharing scope explicit. No multi-user account system is required for the MVP.

Use campaign-bounded periods, a bounded queue, one active collection job, idempotent repeated clicks and request throttling. Local generation must use same-origin POST protections and accept no SQL, shell commands, arbitrary paths or arbitrary fetch URLs. Anonymous viewing must not permit provider spending or campaign start/extension.

Establish the address reachable from household Wi-Fi: the documented household and VM subnets differ. Publishing a VM port alone may be insufficient, and the existing DNS/admin relay does not automatically publish the report app. Verify an allowed path and define any narrow report-port publication separately. Keep TLS, allowed hosts/origins and LAN restrictions consistent. No internet exposure or automatic household routing change is required.

Keep the browser-facing container isolated: no Docker socket, resolver mount or admin credential. A host-side collector with existing necessary Docker access should handle a narrow job contract. Docker access is a privileged boundary even when the process runs under a normal user account. Test startup, restart, stop and rollback from the actual deployment, including a second LAN device. Linux VM is the first target; macOS operation remains unverified.

## 5. Groq and Exa: current implementation versus MVP

This is a review of the code on disk, not a new provider connectivity or accuracy test. Neither integration is needed to collect DNS rows, count them, render a report or apply reviewed namespace rules.

| Component | Current role verified in code | MVP decision |
| --- | --- | --- |
| [Exa MCP adapter](../../destination-report/src/household_report/integrations/exa_mcp.py) | Application-owned MCP client; searches a public candidate name; keeps up to five source excerpts, each capped at 2,048 characters. Supports bounded fetch and tool discovery, but the normal analysis runner invokes search. Agent/advanced-search tools are excluded. | Keep as optional owner research for unresolved public names. No search on report generation, refresh or export. |
| [Groq adapter — now `openai_compatible.py` (renamed during 006 B6)](../../destination-report/src/household_report/integrations/openai_compatible.py) | Direct HTTP client using `httpx`, not the Groq SDK. Reads model metadata, optionally participates in a structured-output probe, then proposes structured destination classifications from supplied public evidence. | Keep optional. Do not use it for clinical interpretation, identifying a player, predicting relapse or writing the normal report. |
| [Analysis service](../../destination-report/src/household_report/analysis.py) | Checks cached mappings, searches unresolved candidates, batches model requests, validates results and records attempts/usage. Its final summary is composed deterministically without another model call. | Reuse ledger, immutable results, replay and unknown handling. Keep the local report job separate from the external-analysis job. |
| [Grounding policy](../../destination-report/src/household_report/classification.py) | Filters candidate names, checks source spans and supported roles, rejects certain activity claims and stores accepted mappings with provenance. | Preserve strict validation. Rule-based relevance checks and exact citations are not independent proof of endpoint function or observed gameplay. Human review remains necessary for research labels. |
| [Gaming projection](../../destination-report/src/household_report/gaming.py) | K selects reviewed namespace matches; M independently selects eligible saved gameplay/matchmaking proposals. A downloads/updates model result alone does not select a domain. | Seed a reviewed private K list for useful initial coverage. Do not broaden M to all provider or CDN results merely to fill the page. |
| Coding-agent MCP configuration | Exa, Context7 and CodeGraph are available/configured for development; Chrome DevTools was imported disabled. | Development tools are separate from application integration, configuration and usage accounting. Adding an MCP to Codex does not wire it into the household app. |

The [003 B5 record](../../specs/003/tasks.md) documents one accepted live `downloads_updates` classification after a grounding-contract fix, with two supporting spans and zero-call replay. This supports narrow operational feasibility. It does not establish broad classifier accuracy, a successful gameplay detector or clinical value.

### Changes needed before exposing optional research in the MVP

1. **Make the two actions unmistakable:** “Generate report” performs local collection/rendering; “Research selected destinations” is a protected external operation. Move provider controls and detailed usage into the owner area; household viewers need evidence labels and report freshness.
2. **Add explicit candidate selection if that is the intended scope.** The current `web.py::preview_context()` builds a snapshot-wide candidate list, ranked through `plan_public_candidates()` with a limit of 20. The confirmation form submits that preview; it has no per-candidate selection. It is not restricted to the visible gaming filter. Either implement a selected-candidate preview with matching identity/stale checks or clearly retain the broader scope; do not describe the present UI as selected-only.
3. **Wire an approved run policy through the actual web job before enabling it.** `Application.open()` creates an `AnalysisService` with service-level budgets. The default allows up to two attempts for transient failures and supplies no run-wide deadline. `live_run_manifest_template()` is informational; `start_analysis()` does not parse and persist an owner-chosen manifest containing per-operation caps, retry allowance and duration. The stricter historical validation harness does not prove this web path enforces the same envelope. Add immutable per-job policy, confirmation and dispatch enforcement, or leave AI disabled for the MVP.
4. **Keep enrichment independent of report availability.** Current `_run_analysis()` requires both a configured model provider and Exa; there is no owner-facing Exa-only review workflow. The basic report should always work from local rules/saved results. A search-and-human-review alternative is possible later but is additional product work, not a feature already shipped.
5. **Evaluate enrichment separately.** Compare reviewed rules alone with rules plus Exa-assisted human review and, optionally, Groq proposals. Measure supported mapping yield, incorrect roles, unresolved rate, reviewer time, latency and actual attempts/tokens. Use held-out names; a source the model retrieved is evidence for a proposal, not an independent accuracy label.

Owner research may disclose only explicitly approved public candidates and bounded public evidence. Privacy filters are heuristics, not a guarantee that every apparently public hostname is safe to disclose. Never send DNS counts/times, client identifiers, diagnoses, diaries or household reports to these services. Preserve source URLs, retrieval dates, mapping scope and revisions locally. Do not automatically promote model output into the reviewed namespace list or add more providers to compensate for uncertain evidence.

**MVP recommendation:** ship the local reporting path with reviewed rules and AI off. Retain the existing integrations for later, protected evidence maintenance once their actual web authorization path is verified. This reduces operating dependencies without discarding completed work.

## 6. Missing work, in delivery order

| Priority | Work | Completion evidence |
| --- | --- | --- |
| P0 | Check current resolver health, schema, settings, actual retained bounds and forwarding path with narrow read-only checks | Dated sanitized source inventory; actual coverage and attribution limits |
| P0 | Review a small private namespace list using saved observations and public primary evidence | Known associations display; shared-provider/update/launcher cases remain qualified; no successful AI call required |
| P0 | Add persistent 3–5-day campaign lifecycle and scheduled closed-chunk capture/import | Capture runs without a browser/login, respects bounds and deadline, resumes after restart, and records gaps |
| P0 | Add Generate report job and full campaign/day views up to 120 hours | One click yields a frozen report across the chosen campaign; repeated clicks/imports do not duplicate rows or jobs |
| P0 | Separate successful-empty, failed, partial, delayed and expired source states | Synthetic cases plus a bounded real-source check demonstrate honest results |
| P0 | Agree the shared report contents, then add open LAN report/view/export routes while preserving protected owner controls | Second household device works without viewer login; sharing scope is understood; owner controls remain protected; no provider calls |
| P0 | Install and validate the existing packaged app for the chosen LAN address and VM recovery plan | Actual deployment, resource measurements and restart/recovery evidence, distinct from synthetic packaging checks |
| P1 | Add optional 24/48-hour convenience filters within campaign bounds | Correct bounds and fingerprints, with the full campaign still available |
| P1 | Measure usefulness with an informed volunteer's labelled ordinary activities | Compare idle launcher, update, gameplay and unrelated browsing; report misses and false positives without disruptive network tests |
| P1, optional | Enable protected owner research only after the section 5 web-policy and candidate-selection gaps are resolved | Exact confirmed candidates and per-job limits are enforced; a failed research job leaves local reports usable |
| Later | Optional automatic signal events and notifications | Explicit DNS predicates, suppression and uncertainty; no diagnosis or person-specific gameplay claims |

The existing [005 draft](../../specs/005-continuous-household-reporting/spec.md) overlaps collection/window work but targets ongoing 24/48-hour reporting, keeps loopback authentication and excludes LAN exposure. Its continuous presence work is unnecessary here. This v1 records the owner's later targeted-campaign direction; reconcile implementation planning with 005 rather than running both plans independently. The 005 documents were not edited or approved by this revision.

## 7. MVP acceptance checks

- Owner-selected 3-, 4- and 5-day campaigns persist their UTC bounds and stop capture at the deadline after bounded finalization. Anonymous visitors cannot start or extend campaigns.
- Capture continues without an open browser or login. Restart preserves the original deadline, catches up only retained in-bound history and records unrecoverable gaps; restarting after expiry does not restart monitoring.
- The complete selected campaign, up to 120 hours, is reportable with correct partial first/final chunks. A one-hour demonstration alone does not pass.
- Campaign state, reports and progress survive a controlled service/VM restart; backup restoration is checked in isolation. Record resource measurements on the target VM. No deliberate household power outage is required.

- A second LAN device opens the report page without an account and triggers one bounded local report.
- The report states requested bounds, capture/import times, source coverage, rule revision and unknowns. Reopening preserves its frozen data.
- Reviewed matches, no matches, missing/invalid rules, successful-empty reads, extraction failures and expired history produce distinct results.
- Repeated real queries remain counted, but repeated imports/overlapping captures do not duplicate a source query. Query first/last times never become durations.
- Downloads and shared infrastructure do not become proof of gameplay. No device/player, addiction score, relapse claim or “no gaming occurred” conclusion is produced.
- Refresh, local generation, filters and exports make zero Exa/provider calls. Only protected explicit owner confirmation dispatches external research.
- Anonymous visitors see only the intended report projection. Secrets, raw client records, diagnostics and owner controls remain protected; hostile labels, CSV formulas and stale exports are handled.
- Focused offline and packaged runtime checks pass, followed by a bounded real-source check and second-device browser check. Record actual results and remaining gaps.

## 8. Mental-health research value and validation path

### What the evidence supports

| Evidence | Finding relevant to this project | What it does not establish |
| --- | --- | --- |
| [WHO gaming-disorder definition](https://www.who.int/news-room/questions-and-answers/item/addictive-behaviours-gaming-disorder) | Diagnosis concerns impaired control, gaming taking priority, continuation despite harm and significant functional impairment, ordinarily over at least 12 months. DNS does not measure those constructs. | A lookup, high query count or resumed gaming is not sufficient to diagnose disorder or relapse. |
| [Oka et al., 2024](https://doi.org/10.1556/2006.2023.00076), original observational studies | In the second study, involving 3,163 Japanese adults, objectively logged gaming time for most game genres was not associated with probable gaming disorder. Associations differed from self-reported time. | This does not prove that time is never relevant; it cautions against substituting even actual playtime, much less DNS counts, for clinical impairment. Generalization beyond this sample is limited. |
| [Nielsen et al., 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8996793/), family-therapy RCT | In 42 adolescents, both family therapies reduced disorder prevalence/symptoms; MDFT performed better on symptom criteria. Gaming time did not change significantly. The intervention aimed for healthier gaming rather than universal abstinence. | A small treatment trial does not validate household monitoring. It does show why “fewer queries” or “no gaming” would be unsuitable universal recovery endpoints. |
| [Madanapalli et al., 2022, Know Thy Lag](https://www2.ee.unsw.edu.au/~vijay/pubs/conf/22pam.pdf), network measurement study | The authors used packet/flow attributes for game detection. In an examined game, the gameplay server address was not obtained through a DNS lookup; matchmaking appeared to deliver it through an encrypted connection. | Accuracy of their richer traffic method cannot be transferred to this DNS-only system, nor to mental-health outcomes. |
| [Afonso et al., 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11342864/), exploratory telemetry work | Demonstrated gaming-behavior metrics with two amateur and two professional Counter-Strike players. The paper acknowledges lack of comprehensive clinical validation. | This is related prior work, not proof that automated behavioral reports diagnose disorder. It also means novelty cannot be claimed merely for visualizing gaming telemetry. |
| [Chan et al., 2024, GADIT](https://pmc.ncbi.nlm.nih.gov/articles/PMC11457026/), screening-tool development | Developed an eight-item ICD-11-oriented instrument using adult panel/university samples. It measures reported symptoms and impairment; its proposed screening threshold is tentative. | A screening score is not a diagnosis, and adult validation does not automatically transfer to minors, another language or another setting. Select measures with the clinical collaborator. |
| [APA App Evaluation Model](https://www.psychiatry.org/psychiatrists/practice/mental-health-apps/the-app-evaluation-model), professional guidance | Evaluates privacy, clinical foundation, usability and fit with patient goals; asks about consent-related choices, opting out, deletion and evidence in intended users. | Local hosting alone does not establish a suitable mental-health tool. This framework is guidance, not endorsement of this project. |

**Interpretation:** there is a defensible research opportunity in testing whether a low-burden, local report helps people review patterns and communicate uncertainty. There is currently no evidence here that it improves health, predicts relapse, reduces family conflict or detects gaming disorder. The contribution would be a validated measurement/interaction method and an honest account of its limits, not the mere addition of Groq or Exa.

### Keep three kinds of measurements distinct

| Measurement layer | Candidate measures | Source and use |
| --- | --- | --- |
| Technical observation | Successful captures, missing intervals, matched domains, observed-query times, classification basis | Resolver and application. Establish what was observed and whether reporting is reliable. |
| Participant context | Voluntary activity diary; what an observed period means; optional brief reports of sleep, urges or daily functioning | Participant input, collected separately with consent. These are reports, not facts inferred from DNS. |
| Clinical/research outcome | Suitable validated symptom/impairment measures, agreed goals, clinician assessment, acceptability and adverse effects | Clinical/research team. Keep identifiable or health-related data out of the open LAN report. |

The unit of DNS observation is the **household**. A resident's symptom score belongs to a **person**. Do not attach the household's signals to that resident, even if they have a previous diagnosis. Other residents, visitors and unattended updates are plausible sources. Any future person-level hypothesis needs separately justified and consented measurement; the MVP does not provide it.

### Staged study proposal

These are planning recommendations, not a recruitment protocol or authorization to collect new participant data.

1. **Co-design the intended use.** A clinician experienced in gaming disorder, a person with lived experience and a household representative review synthetic reports. Agree what useful conversation the report could support, what readers might misinterpret, and who should see details. Prefer an adult volunteer feasibility study first; work involving minors needs a separately designed assent/guardian-consent and ethics process.
2. **Validate the signal before health claims.** Use voluntarily labelled periods of idle launcher, update, actual gameplay, unrelated browsing, simultaneous household use and no recorded activity. Where independently available and consented, participant-accessible game/session history can supplement a diary; neither is assumed perfect. No endpoint agents, traffic interception or network reconfiguration are added by this plan. Freeze the namespace rules before evaluation and include held-out games/households.
3. **Measure agreement at a declared unit.** Predefine a fixed interval, for example 15 minutes, and label the reference activity independently of the DNS result. For exploratory gameplay agreement, report sensitivity, positive predictive value, false positives and missed periods, separating update-only and launcher-only periods. Also report unavailable/unknown intervals and uncertainty; do not count them as negatives or treat repeated intervals from one household as independent participants. Good agreement would still validate a signal proxy, not a diagnosis.
4. **Test usability and added value.** Compare a diary/context review with the same review plus the DNS report, using a preplanned design and accounting for order effects. Record correct interpretation, useful new information, review time, burden, perceived control, privacy concerns and conflict. Ask participants and clinicians separately. Stop or redesign if misunderstandings or distress outweigh useful information.
5. **Only then study clinical benefit.** A clinician/statistician should define the population, usual-care comparator, appropriate outcomes, follow-up and sample-size rationale. A larger comparative study would be required to claim improved functioning or treatment outcomes. A small feasibility sample cannot establish efficacy; any relapse endpoint must be defined clinically in advance, not as any return of gaming-related DNS.

The intended 3–5-day campaign can test collection reliability, signal agreement, interpretation and acceptability. It cannot establish sustained symptom improvement, recovery or relapse prediction. Suspicion-triggered recruitment creates selection bias: document why a campaign began, predefine review times and account for unobserved periods. Do not shorten a validated questionnaire’s recall period to fit the campaign or interpret a three-day score change as validated improvement. Longer clinical studies, if justified later, are separate research scope.

Freeze rule versions and classify evidence basis consistently. Evaluate Groq-assisted labels against independent expert review, not against the same model's own output. Separate tuning data from evaluation data by household/game/time as appropriate. Publish aggregate results and failure modes; do not publish raw household domains or participant narratives by default.

### LAN openness needs a clinical-use decision

The requested engineering MVP remains open to everyone on the intended LAN. For clinical collaboration, LAN membership is not equivalent to consent or a therapeutic relationship. Guests and unrelated residents might see sensitive patterns, and inaccurate interpretations could affect trust. These are design risks to evaluate, not proven harms from this untested tool.

My recommendation for a participant study is to keep identifiable health/context data private and agree exactly which household signal summaries may be shared. Consider restricting detailed history to agreed viewers if participants need that control. This is a proposed change for clinical use, not a silent replacement of the requested open-view MVP. Resolve it with participants and the clinical lead before enrollment. Agree pause/withdrawal, retention and deletion behavior. DNS continuity and failover remain outside this specification under the owner-supplied backup-DNS assumption.

## 9. Ubuntu VM, Proxmox and dashboard operation

The service must run unattended for the selected **3–5 days**, survive ordinary restarts and finish on time. This requires durable scheduling, not a permanent monitoring platform. The following is a deployment proposal, not a claim that boot recovery or resource requirements have been tested.

### Existing packaging and remaining work

The current [Compose service](../../destination-report/compose.yaml) already uses `restart: unless-stopped`, persistent state, read-only input/config mounts, a read-only container root, dropped capabilities and bounded logs. Its limits are 512 MiB RAM, one CPU and 128 processes. Its health check establishes HTTP responsiveness, not fresh source data or a working campaign scheduler. The aggregate sampler's `nohup` process is not a reboot-resilient campaign collector.

Keep application work in the existing Docker image. Supervise the narrow host-side export bridge with a service/timer or equivalent durable scheduler; do not give the anonymous web application unrestricted Docker-socket access merely to simplify extraction. Persist campaign bounds, successful chunk identities, import progress and job outcomes. Serialize collection/report jobs and make retries idempotent.

| Recovery layer | Proposed behavior / verification |
| --- | --- |
| Physical Proxmox host | Infrastructure owner checks firmware power-restoration behavior. An optional UPS can permit orderly shutdown; neither host auto-power-on nor UPS availability is established here. |
| Ubuntu VM | Enable/check Proxmox VM start-at-boot and appropriate startup order. Install/enable QEMU guest agent where appropriate for orderly shutdown and backup integration. Verify against the installed Proxmox version. |
| Docker and services | Check Docker starts with Ubuntu and the reporting container resumes. `unless-stopped` preserves an intentional stop; a removed container needs explicit recreation. A failed health check alone does not restart it. |
| Campaign recovery | Resume using the original UTC deadline after the clock is valid. Recover retained missing chunks within campaign bounds, mark unavailable intervals as gaps, and finalize if the deadline has passed. Never extend a campaign automatically. |
| Interrupted optional AI job | Preserve its ledger and uncertain outcome; do not automatically repeat a potentially billable call after reboot. Local reports remain available. |

Proxmox documents [VM boot/shutdown ordering and guest-agent operation](https://pve.proxmox.com/pve-docs-8/chapter-qm.html); this reference is version 8, not confirmation of the installed version. Docker documents [restart-policy semantics](https://docs.docker.com/engine/containers/start-containers-automatically/). Test controlled application and VM restarts during agreed maintenance, without deliberately cutting household power. DNS continuity and failover testing remain outside scope; missing observations still need explicit coverage labels.

### Resource budget and durable storage

For a dedicated, lightly loaded VM, **1 vCPU, 2 GiB RAM and 20 GiB disk** is a proposed initial budget to measure, not a validated minimum. Building images may benefit from a temporary second vCPU. Do not shrink the existing VM without checking its other workloads. Retain current container limits initially, measure peak memory/CPU and five-day disk growth, then adjust; overly tight limits can cause failed jobs or OOM kills. Docker's [resource guidance](https://docs.docker.com/engine/containers/resource_constraints/) explains these tradeoffs.

Use one collection worker, bounded query windows, bounded logs and no local LLM/GPU, Redis or separate queue server for v1. Account for images/build cache, exported snapshots, SQLite state, reports and backups separately. Agree disk-headroom alerts and saved-data retention before deployment. Campaign completion stops capture, but does not by itself delete reports or exported evidence.

Keep SQLite and its WAL on persistent local storage. Use SQLite's [online backup API](https://sqlite.org/backup.html) or another verified consistent backup procedure; copying only a live database file can omit WAL state. See [WAL requirements](https://sqlite.org/wal.html). Back up campaign state, reviewed rules and required report evidence privately, and test restoration in an isolated directory/service. A backup on the same VM disk does not protect against loss of that disk. Proxmox [VM backups](https://pve.proxmox.com/pve-docs-8/chapter-vzdump.html) can supplement application backups, with consistency and guest-agent behavior checked. Do not promise zero data loss from abrupt power failure.

### Make-driven operation

Existing build targets — now collected in the [Taskfile](../../Taskfile.yml) — already cover image build, local setup, import, service start/stop and logs. They do not yet implement the campaign lifecycle or LAN deployment. `app-certs` currently prepares loopback certificates; LAN naming, certificate trust and publication need explicit configuration and a second-device check.

| Flow | Existing or proposed |
| --- | --- |
| Build/setup | Existing `app-image`, `app-dirs`, `app-password`, `app-certs`; currently loopback-oriented |
| Run/inspect | Existing `app-up`, `app-ps`, `app-logs`; `app-down` removes the reporting container while preserving mounted state |
| Manual data path | Existing `snapshot-export START=… END=…` and `app-import`; not a complete unattended scheduler |
| Check readiness | Proposed `campaign-preflight`: schema, source freshness, state writability, clock, disk and LAN configuration |
| Start | Proposed `campaign-start DAYS=3`: persist bounds, activate supervised collection; also support 4 or 5 days |
| Inspect/report | Proposed `campaign-status` and `campaign-report`: deadline, progress, gaps and frozen report location |
| Finish/back up | Proposed `campaign-stop` and `campaign-backup`: finalize within recorded bounds and preserve a consistent private backup |

Proposed target names are planning interfaces, **not runnable commands today**. Keep service shutdown separate from campaign completion so the final report can remain readable. These project operations do not manage the backup DNS infrastructure.

### Does the dashboard need React?

**No React rewrite is needed for v1.** Reuse Python/Jinja with small JavaScript additions for campaign status, job progress, date filters and a simple timeline. Poll only as needed, back off in hidden tabs and stop job polling when complete. Interactivity does not require a separate frontend framework or an always-running Node service.

Consider React only if later usability work demonstrates a need for complex linked charts or substantial client-side state. React supports [incremental integration into an existing application](https://react.dev/learn/add-react-to-an-existing-project); static built assets can still be served by the Python application. Choose that work from observed user needs, not as a prerequisite for validating the data or clinical usefulness. Infrastructure and React references in this section were retrieved using Exa MCP; Context7 was unavailable in this session.

## 10. Collaboration decisions and next planning package

No collaborators have been contacted. Suggested responsibilities below are roles to recruit or assign, not existing commitments.

| Decision | Suggested lead | Required planning artifact |
| --- | --- | --- |
| Intended user and purpose: household reflection, clinical adjunct, or later relapse research | Owner + clinical lead + lived-experience collaborator | One-page use-case statement, permitted claims and excluded claims |
| Open LAN report content and participant control | Participants/household representatives + clinical lead | Agreed audience, shared fields, consent/withdrawal and retention policy |
| Source coverage and complete 3–5-day campaign | Developer | Dated source inventory, persistent deadline, chunk/recovery design, full-campaign report, gap semantics and actual LAN access path |
| VM operation and resource budget | Infrastructure owner + developer | Measured resource use, supervised capture, restart/restore checks and agreed retention |
| Reviewed namespace baseline and optional enrichment | Domain reviewer + developer | Versioned private rules, primary evidence, review dates and held-out evaluation set |
| Clinical constructs and evaluation | Clinical lead + research methodologist | Chosen instruments, reference labels, study endpoints, sample-size rationale and applicable ethics review |
| AI research scope and spending | Owner + developer | Explicit selection UI and immutable per-run budget/deadline policy, or a recorded decision to keep AI off |

Prepare the next feature spec/plan/tasks around **start a 3–5-day campaign → scheduled capture → local report trigger → frozen LAN report → finish**, incorporating the section 5 findings. Keep continuous presence and clinical data collection outside that engineering batch. Reconcile the existing 005 draft instead of creating contradictory plans. A separate research protocol should follow co-design; do not put unvalidated clinical features into a development spec merely because the data pipeline works.

Progression decisions:

- **Proceed to engineering MVP:** when the source and LAN path are checked and report semantics are agreed. No Groq success is required.
- **Proceed to participant feasibility:** when independent signal validation, agreed sharing/consent and a reviewed study protocol are ready. Set quantitative thresholds with the research team before evaluating data; this document invents no clinical cutoff.
- **Proceed to clinical-effectiveness claims:** only after an appropriate comparative study demonstrates benefit and acceptable harms.
- **Narrow or stop the clinical direction:** if signals mainly reflect unattended updates, major gaming modes are invisible, attribution ambiguity prevents the intended use, or participants find the report harmful/unhelpful. A negative result is still useful feasibility research and can leave a valid general network-observation tool.

## 11. Deferred scope and final planning position

Keep household DNS continuity/failover outside scope. Defer permanent monitoring, device attribution/presence expansion, clinical PDFs, EHR integration, multi-user accounts, parental blocking, schedule enforcement, mobile apps, router auto-configuration and a frontend rewrite. The first research contribution should be whether the measurements and presentation are useful and interpretable, not how many health-product features can be added.

Still unknown: current source health/coverage, useful production rules, signal miss/false-match rates, allowed LAN publication, capture settling time, report latency, participant acceptance and incremental clinical usefulness. Implementation tests cannot settle those research questions.

Truthful product description: **“A local household dashboard that reports observed gaming-related DNS signals on demand, with evidence and coverage limits.”** Research description: **“A feasibility study of consent-based household DNS reports as an adjunct to participant reflection and clinician-led discussion about problematic gaming.”** Both are practical directions to investigate; diagnosis, recovery and relapse claims remain unsupported.

## Sources and resume points

- [004 task ledger](../../specs/004-gaming-web-view/tasks.md), [003 task evidence](../../specs/003/tasks.md), [004 spec](../../specs/004-gaming-web-view/spec.md) and [plan](../../specs/004-gaming-web-view/plan.md): dated completion, grounding and view boundaries.
- [Application README](../../destination-report/README.md), [Compose](../../destination-report/compose.yaml), [web routes](../../destination-report/src/household_report/web.py), [reporting](../../destination-report/src/household_report/reporting.py) and [gaming projection](../../destination-report/src/household_report/gaming.py): inspected code/configuration.
- [Export](../../destination-report/tools/export_snapshot.py), [import](../../destination-report/tools/import_inputs.py), [aggregate sampler](../../dns-pilot/observe_queries.py) and [pilot configuration](../../dns-pilot/compose.yaml): extraction, persistence and collection constraints.
- [Pi-hole query database](https://docs.pi-hole.net/database/query-database/), [privacy levels](https://docs.pi-hole.net/ftldns/privacylevels/), [configuration](https://docs.pi-hole.net/ftldns/configfile/): primary references located/read through Exa on 2026-10-24; installed behavior still needs verification.
- [Mozilla DoH administrator reference](https://firefox-admin-docs.mozilla.org/reference/policies/dnsoverhttps/): primary description of remote DNS bypass, located through Exa on 2026-10-24.
- Section 8 links the seven selected clinical/measurement guidance and research sources retrieved through Exa MCP on 2026-10-24. Their populations, methods and limits are stated alongside each finding; no external study directly validates this implementation.
- [Application wiring](../../destination-report/src/household_report/app.py), [settings](../../destination-report/src/household_report/settings.py), [analysis](../../destination-report/src/household_report/analysis.py), [confirmation template](../../destination-report/src/household_report/templates/analysis_preview.html), [classification](../../destination-report/src/household_report/classification.py), [Exa adapter](../../destination-report/src/household_report/integrations/exa_mcp.py) and [Groq adapter — now `openai_compatible.py` (renamed during 006 B6)](../../destination-report/src/household_report/integrations/openai_compatible.py): inspected for the section 5 implementation review; no live provider run was made.
