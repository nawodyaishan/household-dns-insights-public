# Starlink capability investigation

## Authorized DNS pilot

The user approved revision 2 of `specs/001-dns-monitoring-pilot/` and authorized implementation in the conversation with “proceed” on 2026-10-22. Those documents govern the monitoring-only Pi-hole pilot and supersede the investigation-only/no-configuration-change instructions below **only within that scope**. Use standard Cloudflare upstreams, keep blocking off and raw evidence private. Loopback preparation is authorized; user-run root protection, Mac tests and manual Starlink cutover remain intervention points. Never change household routing/topology automatically. No AI/custom application yet.

Investigate this stock Starlink Gen 3 router using read-only diagnostics and evidence. Do not build an application or recommend a technology stack until collection capabilities are established.

## Revised goal

- Network-wide remote IP, domain, or service activity with timing; individual-device attribution is optional.
- Per-device observed connected/disconnected periods, first/last seen, and monitoring gaps. Network presence is not OS uptime or human activity.
- Eventually collect continuously in Docker on this Ubuntu VM and display the previous 24/48 hours through a LAN-accessible dashboard.
- AI/search may later classify observed destinations, never invent destinations from bandwidth patterns.

## Documentation lookup

Use Context7 to fetch current documentation whenever the task depends on a library, framework, SDK, API, CLI tool, or cloud service — even well-known ones. This includes API syntax, configuration, version migration, and library-specific setup or debugging. Prefer it over web search for library docs. Do not use it for refactoring, debugging business logic, or general programming concepts that do not hinge on a library or platform API.

## Documentation layout

- Put sanitized investigation reports in `docs/investigations/`, reusable references in `docs/reference/`, and operating procedures in `docs/operations/` (existing historical locations may remain).
- Feature requirements, decisions and execution state belong in `specs/<feature>/`; project-wide intent belongs in `docs/project-scope/`. Keep raw evidence and credentials private and outside Git.
- When moving documentation, update repository links and preserve historical evidence and approval records.

## Environment and existing evidence

- Proxmox Ubuntu VM: `10.10.10.20/24`, gateway `10.10.10.1`.
- Router: `192.168.1.1:9000`; dish: `192.168.100.1:9200`. Both reachable; gRPC reflection works.
- Docker and `fullstorydev/grpcurl:v1.9.3` already worked.
- Read `REPORT.md` and inspect `PRIVATE_RAW.json` locally first. The original probe is `../starlink_capabilities.py`. Locate files before assuming paths.
- Prior findings supplied by the user: 11 records (10 clients and one controller); selected Windows client `192.168.1.23`, interface `ETH`, `uploadMb: 50`, `downloadMb: 1503` with unknown accounting period; empty detailed rx/tx stats and two all-zero 900-sample throughput arrays. Eight Wi-Fi clients had populated byte counters.
- Previous schema traversal stopped at 70 types. No household destination feed was established. Treat prior findings as context to verify, not new observations.

## Task A: destination capabilities

Inspect existing evidence, then relevant live request/response schemas. Make only narrowly scoped calls whose request structure and read-only behavior are understood.

Look for remote IPs/ports, DNS queries/history, connection or flow records, counters, timestamps, and existing exports/log sources accessible without setting changes.

Specifically examine `get_connections` and `wifi_get_firewall`. The reflected `GetConnectionsResponse` service-address map and seconds-since-success fields do not establish household traffic. Firewall rules do not establish connection history.

Distinguish forwarded household traffic from router/dish management connections, static DNS/firewall configuration, connectivity tests, and aggregate health metrics. For every candidate feed, establish provenance, snapshot versus historical coverage, and timestamp semantics. Mark unverified provenance UNKNOWN. Use and cite primary documentation or implementation sources when necessary. Record denied/unsupported calls; never bypass restrictions.

## Task B: device presence

Poll `wifi_get_clients` approximately every 15 seconds for two minutes. Retain timestamps and compare stable identifiers locally.

Assess association/active fields, persistence of disconnected records, DHCP leases versus actual connectivity, wired/wireless differences, controller/repeater exclusion, polling precision, and uncertainty.

Never infer offline from a single missing response, API failure, or stale/unexpired lease. Represent failures as monitoring gaps. If no transition occurs, explicitly state that transition detection remains unvalidated.

## Safety and privacy

- Do not change router, DNS, firewall, DHCP, routing, or device configuration.
- No endpoint agents, interception, debug modes, speed tests, reboots, or deliberate disconnections.
- No arbitrary discovered methods, broad log dumps, memory dumps, or configuration-changing requests.
- Keep raw responses local in private files. Never print credentials, Wi-Fi passwords, account identifiers, serial numbers, or unredacted configuration in conversation.
- Schema presence is not confirmation of usable data. A failed or bounded probe is not proof of universal impossibility.

## Deliverable

Create `docs/investigations/STARLINK-DESTINATIONS-AND-PRESENCE-REPORT.md` with:

- A verdict for each capability: CONFIRMED, NOT OBSERVED, ACCESS DENIED, or UNKNOWN.
- Exact supporting methods/fields, evidence, citations where applicable, and sanitized examples.
- Observations clearly separated from interpretation.
- Whether the revised goal is achievable with the unchanged setup.
- Remaining narrowly defined tests, if any.

Return the sanitized report path and a concise conclusion.
