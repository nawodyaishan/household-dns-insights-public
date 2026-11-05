# Starlink Destinations and Presence Report — T17 Campaign

> **Privacy redaction:** observed destination names and detailed per-destination
> results have been removed from this version. Historical Git revisions still
> contain the original observations.

## Capability Verdicts

| Capability | Status | Evidence |
|---|---|---|
| **Host LAN access to AI dashboard** | **CONFIRMED** | `https://192.168.1.10:8789` reachable from household LAN client `192.168.1.24`; real login completed; owner password auth, TLS and CSRF retained |
| **Shared unauthenticated household view** | **CONFIRMED** | `http://192.168.1.10:8787` active and unchanged; now shows the classified services |
| **Remote IP/domain activity with timing** | **ACCESS DENIED** | Router/dish management connections, static DNS/firewall configuration, connectivity tests and aggregate health metrics excluded; no household destination feed established |
| **Per-device connected/disconnected periods** | **CONFIRMED** (partial) | `wifi_get_clients` polling shows association/active fields; DHCP leases vs actual connectivity distinguished; wired/wireless differences noted; controller/repeater exclusion validated; gaps represented as monitoring uncertainty |
| **Continuous Docker + 24/48h dashboard** | **CONFIRMED** | `household-ai-app-1` binds `0.0.0.0:8789`; Proxmox `household_report_relay` DNATs TCP 8789 from `wlo1` (`192.168.1.0/24`) to `10.10.10.20:8789`; 19 snapshots / 115,873 DNS rows in shared SQLite |
| **AI classification of unknown domains** | **CONFIRMED** | Final revision `ba0d8a0a…` completed 20/20 candidates: **17 service-specific, 3 unresolved**; 17 `ai_grounded` rules written to the shared `classifications` table; shared-view coverage moved from 0 to 16 service-specific domains of 4,703 |

## Campaign

Campaign `camp-fedcba9876543210` reached `complete`; its exact observation
window is redacted.

Frozen report `report-0123456789abcdef01234567`, from 19 hourly snapshots /
115,873 DNS rows:

| Measure | Value |
|---|---|
| Distinct domains | 4,703 |
| Unresolved at freeze time | 4,701 |
| Service-specific after the AI run | 16 |
| Domains with DNS rows affected | 13,377 |

## Classified destinations (17 grounded rules)

The observed names and service-level results are redacted. Three other names
remained unresolved because their proposed claims were not supported by the
grounding contract. A DNS query never proves what a device did with a name.

## Network access

```
[ Household device 192.168.1.x ]
        │  Wi-Fi
        ▼
[ Proxmox pve-zenbook — wlo1 192.168.1.10 ]
   nft table ip household_report_relay (prerouting, dstnat)
        ├── TCP 8787 ──▶ 10.10.10.20:8787   shared anonymous HTTP view
        └── TCP 8789 ──▶ 10.10.10.20:8789   owner TLS view (password + CSRF)
        │
        ▼
[ Ubuntu VM 10.10.10.20 — ens18 on vmbr0 ]
   household-report-app-1   10.10.10.20:8787   (shared, AI off)
   household-ai-app-1       0.0.0.0:8789      (owner, AI enabled)
        │
        └── shared SQLite: 19 snapshots, 115,873 DNS rows, 17 classification rules
```

Both DNAT rules are scoped to `iifname "wlo1"`, `ip saddr 192.168.1.0/24`,
`ip daddr 192.168.1.10`. No router, DNS, firewall, DHCP, routing or Starlink
setting was changed.

## Provider configuration

| Item | Value |
|---|---|
| Provider | OpenRouter |
| Model | `mistralai/mistral-nemo` (paid: $0.029/M in, $0.03/M out) |
| Evidence | Exa MCP (`web_search_exa`, `web_fetch_exa` only) |
| Declared limits | `AI_CONTEXT_LIMIT=32768`, `AI_COMPLETION_LIMIT=1024`, `AI_COMPLETION_CAP=1024` |
| Per-analysis budget | 12 provider requests, 12 Exa attempts, 524,288 tokens |
| Per-day budget | 60 provider requests, 60 Exa attempts, 2,097,152 tokens |

`mistralai/mistral-nemo` was chosen as the lowest-cost model in the requested set
that is still present in the OpenRouter catalogue with structured-output
support. The previously configured `poolside/laguna-s-2.1:free` had been
**removed from the catalogue**, which was the real cause of the repeated
`ExternalError`.

## Defects found and fixed

Each fix carries a regression test; 408 offline tests, `ruff format --check`
and `ruff check` all pass.

1. **Whole-request disclosure bound.** `bound_evidence` applied the 16 KB
   evidence budget *per candidate* while the sender enforces 20 KB *per
   request*, so every multi-candidate batch was refused with "Request evidence
   exceeds the approved disclosure bound" and no batch could ever be sent. The
   bound is now a whole-request budget shared fairly between candidates,
   measured by one shared serializer on the request contract, with the heaviest
   source dropped rather than an excerpt cut mid-sentence.
2. **Budget category accounting.** `per_analysis_requests` was charged against
   *all* attempt rows including Exa attempts, contradicting the declared limits
   ("12 provider requests and 12 Exa attempts per analysis"). Each allowance is
   now spent only by its own category. The numerical limits are unchanged.
3. **Credential parsing.** The running image still read `/config/.env.local` as
   one opaque secret and rejected the multi-line OpenRouter dotenv. The image
   was rebuilt so each assignment is parsed, and the private Exa key file now
   holds the bare key instead of a quoted `key1="…"` display form.

## Remaining narrowly defined tests

1. **Reload the household report** at
   `http://192.168.1.10:8787/household/reports/report-0123456789abcdef01234567`
   and the **Destinations** view, to confirm the classified services appear
   (verified locally; the browser view is the owner's check).
2. **Re-examine the 3 unresolved domains** if the owner wants them classified —
   they were refused by the grounding contract, so they need a different
   evidence shape or an explicit human decision, not a retry.
3. **Probe `get_connections`** to confirm it returns only management and health
   connections, not household traffic.
4. **Poll `wifi_get_clients`** at 15-second intervals for 4 minutes to confirm
   stable identifiers persist and DHCP lease status stays distinguishable from
   actual connectivity.

## Files involved

- `destination-report/compose.ai.yaml` — AI instance override: `0.0.0.0:8789`, allowed hosts, provider/model/limits
- `destination-report/src/household_report/classification.py` — whole-request evidence bound, fair per-candidate share
- `destination-report/src/household_report/contracts.py` — shared `ModelRequest.payload()` / `payload_bytes()`
- `destination-report/src/household_report/integrations/common.py` — sender uses the shared payload definition
- `destination-report/src/household_report/storage.py` — per-category budget accounting
- `destination-report/tests/offline/test_classification.py` — whole-request bound regression test
- `destination-report/tests/offline/test_storage.py` — per-category budget regression test
- `dns-pilot/dashboard-proxmox-relay.sh` — Proxmox nft relay rules
- `destination-report/tools/import_inputs.py` — imported the 19 captures into `snapshots` and `dns_rows`
- `~/.local/share/household-report/state/app.sqlite3` — shared SQLite: 19 snapshots, 115,873 DNS rows, 17 rules

## Conclusion

The revised goal is achieved. Household LAN access to the AI destination
analysis dashboard works without SSH tunneling, with owner authentication, TLS
and CSRF retained, while the unauthenticated shared view stays active. Unknown
destinations from the T17 campaign were classified against retrieved public
evidence: 17 grounded service rules now populate the shared household report,
and the three remaining domains were refused rather than guessed. The remote
IP/domain feed with timing remains unavailable from the router and dish; the
observations above are local DNS observations only, never connections, sessions
or device activity.
