# Monitoring-only DNS pilot — spec r2

## Outcome and sources

Provide a restricted, persistent Pi-hole Docker resolver for timestamped household DNS query history. Source of requirements: user's deployment request and correction to standard Cloudflare, 2026-10-22; `../../docs/investigations/STARLINK-BLOCKERS-RESEARCH-REPORT.md`, sections 2A and 4. No SRS, global roadmap or technical-spec documents exist in this project. This approved-by-user change in project intent supersedes the earlier investigation-only scope for this pilot, but not the prohibition on automatic household topology changes.

## Scope

- Deploy a pinned stable Pi-hole release using Compose, persistent `/etc/pihole`, UTC and automatic restart.
- Only upstreams `1.1.1.1` and `1.0.0.1`; no Families upstreams, router forwarding or conditional router forwarding.
- Monitoring only: disable blocking persistently, disable default lists and special-domain suppression, keep caching/resolution, timestamped query logging and seven-day database retention. DHCP remains off.
- Protect admin credentials outside version control, restrict DNS/admin sources using Docker-aware enforcement, and avoid public/IPv6 wildcard exposure.
- Validate UDP/TCP DNS, logging, authenticated administration, restart persistence and consistent backup/restore.
- User alone makes Starlink app changes after readiness. No Proxmox bridge, route, household topology or device DNS changes automatically.

## Acceptance criteria

1. Existing services, loopback resolver and host DNS configuration remain intact; deployment records image tag/digest and only intended port bindings.
2. Untrusted sources cannot reach published DNS/admin; rule ordering and persistence are verified against actual Docker backend, including userland-proxy and direct-container paths.
3. Local explicit UDP and TCP queries return valid answers. Query domain/timestamp records exist on disk and survive a container restart; effective blocking remains false and no default adlists are enabled.
4. Admin authentication succeeds with a private credential; unauthenticated protected endpoints are denied. Seven-day retention is configured and independently checked, not represented as seven days already observed.
5. An existing Mac on `192.168.1.x` successfully queries the resolver using explicit `dig @address` over UDP and TCP without changing Mac DNS. Correlate these queries in Pi-hole before declaring LAN readiness.
6. Proposed app Primary/Backup/IPv6 values are based on verified paths. Public backup DNS must not be silently selected; duplicate same-server fields do not add resilience. No IPv6 address is advertised without validation.
7. Provide cutover, rollback, outage behavior, backup/restore and post-cutover verification instructions. After the user applies settings, verify ordinary queries, apparent source identity and IPv6 bypass separately.
8. After confirmed cutover, observe for 24–48 hours: ordinary queries, rate-limit events, database growth, collection gaps and a few user-reported service-use examples. Report measured coverage and uncertainty, never completeness. Default recovery is standard Cloudflare with filtering off; restoring the previous filtered setup requires separate user selection.

## Follow-on scope (not implemented by this pilot)

| Stage | Deliverable |
|---|---|
| This pilot | Persistent timestamped household DNS query observations |
| Next | Starlink device observations, first/last observed times and collection gaps |
| Application | Mobile-friendly on-demand reports covering the preceding 24/48 hours |
| Classification | AI + Exa service labels with supporting sources and uncertainty |

If requester identity is only the router or a NAT gateway, retain household-level attribution. Never assign those queries to individual devices by guesswork or temporal coincidence with presence observations.

## Exclusions and limits

No AI, custom dashboard, extra filtering lists, DHCP, packet interception, forced disconnects or unapproved firewall/routing changes. DNS queries are not confirmed connections, application usage, human activity or browsing duration. DoH/DoT/VPN and alternate IPv6 DNS may bypass logging. Public backups trade coverage for availability.

## Open gates

- User supplied root-authorized firewall inspection output (17:31:42 UTC): UFW inactive, DOCKER-USER empty, permissive host INPUT. Agent sudo still requires authentication, so the user ran the reviewed installer: scoped guard installed 18:02 UTC, wired through a Docker `ExecStartPre` hook with `ignore_errors=no`, and `--check` passed.
- No Mac execution channel exists for the agent. The user ran the Mac tests: UDP, TCP, AAAA and HTTPS against `192.168.1.10` passed at 18:24:19 UTC, and client `192.168.1.20` was recorded.
- LAN-to-VM routing is resolved: the Proxmox host reaches the household LAN only on Wi-Fi `wlo1` (`192.168.1.10`), while the VM sits on an unbridged private network behind `vmbr0` (`10.10.10.1`). A user-approved scoped relay now forwards household TCP/UDP 53 and TCP 8443 to `10.10.10.20`; household DNS/admin address is `192.168.1.10`, verified from a Mac at 18:24:19 UTC with preserved client source addresses.
- Starlink app accepted custom DNS with **empty Backup and empty IPv6 fields** and content filtering off (user confirmed 2026-10-22); the router forwards to `192.168.1.10`. Queries began at 18:27:48 UTC and household browsing was reported normal afterwards.

## Combined approval

Decision: **approved** for spec r2, plan r2 and tasks r2. Human actor: project owner (GitHub identity supplied as `nawodyaishan`). Evidence: user's “proceed” on 2026-10-22 in response to the explicit question authorizing implementation of revision 2, starting with safe loopback-only preparation. This authorizes deployment and routine verification in this VM within the reviewed scope. One implementation batch covers the pilot including the post-cutover observation window. No additional routine phase approvals; pause for the user's root command, Mac results, manual app change, or a newly proposed material topology/access-control change. Household app cutover remains reserved to the user.

Amendment (2026-10-22): user approved a scoped Proxmox host change after the reachability diagnosis — destination NAT on `wlo1` from `192.168.1.0/24` for `192.168.1.10` TCP/UDP 53 and TCP 8443 to `10.10.10.20`, plus a dedicated persistent unit and rollback. Household DNS address becomes `192.168.1.10`. No bridge, route, masquerade, management-port or other-VM change is authorized. Installation remains a user-run root step with preflight, validation and rollback.
