# Starlink monitoring: latest blocker research

Date: 2026-10-22

## Executive conclusion

Exa search, page fetching, and Advanced Search found documented alternative collection mechanisms, but **no verified stock-router API workaround** for the destination-monitoring blockers. Presence inventory is available; reliable connected/disconnected semantics remain unvalidated.

The unchanged setup can support timestamped router-inventory observations. It has not demonstrated household destination activity with timing, nor authoritative connection/disconnection history. No application was built, network configuration changed, traffic intercepted, or endpoint agent installed during this research. Private evidence was not submitted to search services.

## Evidence categories

- **Locally observed:** the earlier API diagnostics and nine-poll presence test, documented in `STARLINK-DESTINATIONS-AND-PRESENCE-REPORT.md`.
- **Documented elsewhere:** capabilities described by the cited primary product documentation or source repositories. These are not validated deployments on this network.
- **Interpretation/proposal:** possible next steps and topology implications; not confirmed capabilities of the current Starlink setup.

## Updated verdicts

| Capability | Verdict | Basis |
|---|---|---|
| Household destination feed from tested stock APIs | NOT OBSERVED | Local probes established no usable feed; research found no verified replacement stock method. |
| `get_connections` on tested router and dish | NOT OBSERVED | Both returned UNIMPLEMENTED; reflected service-status structure does not establish household flows. |
| Router `wifi_get_firewall` access | ACCESS DENIED | Local call returned PERMISSION_DENIED; no bypass attempted or verified. |
| Stock-router inventory polling | CONFIRMED | Nine successful polls over 120 seconds returned 10 clients plus a controller. |
| `active` as a reliable connectivity indicator | UNKNOWN | Flags changed while records remained listed and association counters increased; no authoritative semantic definition found. |
| Reliable disconnect/reconnect detection | UNKNOWN | No verified connection transition occurred in the local sample. |
| Domain-query collection using a logging resolver | UNKNOWN on this setup | Product documentation confirms the mechanism elsewhere; DNS path and reachability have not been tested here. |
| IP/port activity using gateway flows or an approved sensor | UNKNOWN on this setup | Documented mechanisms exist, but no suitable traffic collection point has been established here. |

## 1. Why additional API retries are not a demonstrated solution

Starlink's officially supported local Device API repository documents diagnostics. Its published protobuf includes network-level client counts and dish/router diagnostics, not a household DNS-query or forwarded-flow ledger [1]. This published subset does not prove the absence of all undocumented firmware features.

The local `get_connections` failures and denied firewall call remain stronger evidence about this particular firmware than examples from other installations. Research did not establish a supported credential, configuration-free export, or alternate read-only call that resolves these failures. Firewall rules would not themselves constitute a historical connection ledger even if access were granted.

**Conclusion:** do not bypass permissions, assume a firmware upgrade fixes the issue, or treat the router's own management endpoints as household destinations.

## 2. Alternative destination collection mechanisms

These are collection options, not a selected application stack. Each requires separate approval before configuration changes, installation, or traffic observation.

### A. Logging DNS resolver: partial domain visibility

Pi-hole's primary documentation defines query records with `timestamp` (query arrival time), `domain`, `client`, query type, and handling status [2]. This establishes a source of observed **name-resolution requests**, not proof that a connection to a requested service occurred.

Starlink's help documentation lists custom DNS servers among app-configurable router settings [3]. That makes a logging resolver a candidate, but this research did not verify whether this firmware accepts a private resolver address, whether the router forwards or advertises it, or what source identity reaches it.

Required validation before household rollout:

- Confirm that clients/router can reach the proposed resolver from the household LAN. The VM's ability to reach the router does not prove reverse reachability from `192.168.1.x` to `10.10.10.x`.
- Establish actual query forwarding behavior and IPv4/IPv6 coverage.
- Verify timestamped test queries appear, then distinguish queries from connection evidence.
- Determine whether attribution appears as individual clients or only the router; household-level attribution may be sufficient for the revised goal.

Limitations: client/router caching can hide repeated activity; direct IP connections need no lookup; alternative DoH/DoT resolvers or VPN tunnels can bypass this resolver. A lookup may arise from background work or prefetching and is not evidence of human browsing. A secondary resolver can create coverage gaps if clients use it instead.

**Changes needed:** resolver deployment and approved DNS/client/router configuration. This is not achievable through the tested read-only API alone.

### B. Flow-capable gateway: remote IP/port activity

OPNsense's primary Insight documentation describes current and historical flow analysis, IP/port filtering, interface selection, date ranges, and exports [4]. This demonstrates an alternative collection mechanism, not a requirement to choose that product.

For household-wide coverage, the gateway must actually carry household internet traffic. Attaching a new router or collector to a spare LAN port does not place existing Starlink Wi-Fi traffic through it. A downstream gateway would initially see only devices moved behind it. A future whole-house topology may require moving clients and providing replacement Wi-Fi; bypass-mode compatibility and migration effects must be checked against the exact hardware before any change.

A flow record supports observed endpoint activity, not automatically an exact domain, application, successful session, or user action. Shared/CDN addresses, NAT, IPv6, sampled exports, and tunnel endpoints complicate interpretation. Timestamp resolution and retention depend on the chosen collection/export settings and must be verified.

**Changes needed:** approved routing/topology changes and flow collection/export. No gateway was configured or recommended as a final stack.

### C. Traffic sensor: requires an observable link

Zeek's primary connection-log documentation includes `ts`, `id.orig_h`, `id.resp_h`, `id.resp_p`, protocol, duration, connection state, and byte counts [5]. Its DNS-log documentation includes query names and timestamps and explicitly notes that encrypted DNS is not available as ordinary plaintext query records [6]. These demonstrate what a sensor can derive from traffic it actually sees.

A correctly positioned mirror/TAP could supply traffic to a sensor. An ordinary VM network interface, host networking in Docker, or a different VM subnet does not automatically expose other household clients' switched traffic. A mirror of only the Proxmox/VM uplink may cover only that host's traffic. Stock-router Wi-Fi traffic may never cross a LAN switch mirror at all.

**Changes needed:** validated physical/virtual observation point and explicit permission for traffic observation. This option is outside the current no-interception diagnostic constraints and was researched only, not executed.

## 3. Presence: remaining blocker and safe resolution

### Local facts remain unchanged

- Nine polls over 120 seconds returned the same 11 identifiers: 10 CLIENT and one CONTROLLER.
- Eight Wi-Fi clients had monotonic association durations; the two wired clients omitted association duration.
- `active: true` appeared intermittently for two Wi-Fi clients without inventory disappearance or association reset.
- DHCP lease flags differed from inventory/association signals.
- No verified disconnect/reconnect transition occurred.

Therefore neither the `active` flag, an unexpired lease, nor simple inventory membership has been established as a definitive connected/disconnected signal for this firmware.

### What Advanced Search added

Generated bindings corroborate the existence of lease/idle/association fields, not their operational semantics [7]. A community presence implementation explicitly calls out sleeping-device errors, unstable identifiers, missing fields, and the need for attended reconnect/identity validation [8]. It is useful evidence about implementation risks, **not manufacturer documentation or proof that its thresholds work here**.

No authoritative firmware definition of `active`, disconnected-record retention, or wired presence transitions was established by this search. More search results alone cannot resolve behavior that requires local transition evidence.

### Proposed next test, without intentional disruption

1. Arrange an observation window during naturally occurring wired and Wi-Fi departures/returns; do not disconnect anyone or change device configuration.
2. Record independent operator-observed transition times, then compare successful API snapshots before and after each event.
3. Compare stable local identifiers, role, interface, association duration/reset, idle time, and DHCP state. Treat all as evidence candidates until their behavior is validated.
4. Determine whether disconnected records disappear, persist, or change fields; measure retention delay rather than assuming it.
5. Include ordinary idle/sleep periods to distinguish quiet devices from disconnected devices. Preserve identity uncertainty if addresses rotate.
6. Keep failures and missing observations as UNKNOWN/monitoring gaps. Multiple missing snapshots may support a policy later, but do not prove actual disconnection without validation.

Until then, use labels such as **first observed in inventory**, **last observed in inventory**, and **connectivity unknown**. Do not relabel those as first arrival, exact departure, OS uptime, or human presence.

## 4. Decision summary

| Allowed scope | What can reasonably be pursued next |
|---|---|
| No settings/topology changes | Validate inventory semantics during natural transitions. Household destination monitoring remains unestablished. |
| DNS changes approved | Test a logging resolver for timestamped domain queries with explicit coverage limitations. |
| Routing/topology changes approved | Establish a gateway collection point for remote IP/port traffic actually traversing it. |
| Traffic observation separately approved | Assess whether a mirror/TAP can cover the required household paths. |

For the exact revised goal of **which remote endpoints the household contacted and when**, DNS alone is partial evidence. Verified flow/connection observations are a closer match for IP/port activity; domain enrichment must retain provenance and uncertainty. AI/search can classify observed endpoints but cannot reconstruct unseen destinations from bandwidth patterns.

## Sources

Research used Exa search/fetch and Advanced Search with Starlink, GitHub and generated-binding domain filters. Some Starlink support URLs returned only application shells; no substantive claims rely on those shell-only responses. Sources differ in firmware/version coverage.

1. Starlink official local Device API: https://github.com/SpaceExplorationTechnologies/enterprise-api/tree/master/device-api ; published protobuf: https://raw.githubusercontent.com/SpaceExplorationTechnologies/enterprise-api/master/device-api/device.proto
2. Pi-hole query database: https://docs.pi-hole.net/database/query-database/
3. Starlink app-configurable router settings: https://starlink.com/as/support/article/f9a1d602-9204-e70c-a780-f2619d99f9c7
4. OPNsense Insight flow analysis: https://docs.opnsense.org/manual/how-tos/insight.html
5. Zeek connection log fields and semantics: https://docs.zeek.org/en/current/reference/logs/conn.html
6. Zeek DNS log and encryption limitations: https://docs.zeek.org/en/current/reference/logs/dns.html
7. Community generated WifiClient binding (version-dependent): https://docs.rs/starlink-grpc-client/latest/starlink_grpc_client/space_x/api/device/struct.WifiClient.html
8. Community presence validation plan (not a firmware contract): https://github.com/Dbochman/dotfiles/blob/main/openclaw/plans/cabin-starlink-presence-enrollment.md

This report is sanitized. Keep all raw local diagnostics private.
