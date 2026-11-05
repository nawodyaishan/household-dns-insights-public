# Monitoring-only DNS pilot — plan r2

Input: `spec.md` r2. Approval record: `spec.md#combined-approval`.

## Preflight evidence (2026-10-22)

- No running containers. Existing stopped Coder container is preserved, including its storage/configuration.
- `ens18` is `10.10.10.20/24`; route to the household LAN uses `10.10.10.1`. No household-routable IPv6 address/default IPv6 route exists. Tailscale IPv6 is not a household DNS address.
- TCP/UDP 53 are bound only to systemd-resolved loopback addresses `127.0.0.53`/`127.0.0.54`. Do not disable resolved or edit `/etc/resolv.conf`.
- Docker Compose v5.6.0; Docker firewall backend `iptables`, userland proxy enabled. Only standard bridge/host/none networks exist.
- User supplied root-authorized iptables/ip6tables/nftables/UFW output at 17:31:42 UTC. UFW is inactive. IPv4 INPUT/OUTPUT accept; FORWARD drops with DOCKER-USER first, then DOCKER-FORWARD and Tailscale. DOCKER-USER is empty. IPv6 INPUT/FORWARD/OUTPUT accept, with Docker/Tailscale chains. The displayed nftables rules corroborate the iptables-nft backend, not an independent replacement ruleset. No current published-port DNAT rules are shown. Preserve all Docker/Tailscale chains. New published ports would not be source-restricted by these rules. Direct root application remains unavailable to the agent; user-run reviewed installation will be required. Refresh evidence before exposure.
- No Compose or feature source files existed. Current official stable Docker release is `2026.10.0` (published 2026-10-17), FTL 6.8/Core 6.5/Web 6.6.1. Pin that tag and record/pin the registry digest after pull; never silently use latest/nightly.

## Design

### Isolation and access

Use a dedicated Compose project and bridge, not host networking, no privileged mode, no NET_ADMIN/SYS_TIME additions. Initial bootstrap exposes DNS/admin only on loopback test ports; it is not a LAN service. Use a fresh dedicated persistent `/etc/pihole` volume and bounded Docker log rotation. Compose preparation, static checks and loopback-only validation proceeded after combined approval; the reviewed guard was installed by the user at 18:02 UTC, after which the LAN override was published. Confirm Docker's actual loopback publication behavior before startup; a root gate on LAN publication must not become an unnecessary dependency for safe local preparation.

Before LAN publication, a root-authorized firewall inspection must establish the actual rules/order. Add only scoped pilot rules, preserving unrelated chains and SSH/Tailscale access. For this iptables backend, use a dedicated chain reached from DOCKER-USER to constrain forwarded traffic to the pilot container, plus scoped host INPUT protection for userland-proxy paths. Cover original published destination, direct container access and connection state; do not flush Docker/UFW rules. Persist/reapply protections before container autostart after reboot and after Docker restarts. If fail-closed startup ordering cannot be verified, do not enable automatic LAN publication.

Intended remote trusted network is `192.168.1.0/24`, plus host-local testing. No blanket trust of the whole `10.10.10.0/24` or Tailscale network. If gateway NAT obscures source addresses, stop and assess the smallest explicit source/address allowance with the user. Allow DNS UDP/TCP 53 and administration TCP 8443 only. No IPv6 port publication. Bind specifically to `10.10.10.20`, not `0.0.0.0`. A private bind address alone is not a source ACL or proof of no public exposure.

Candidate final DNS: `10.10.10.20:53`. Candidate dashboard: `https://10.10.10.20:8443/admin/`, using Pi-hole's self-signed TLS initially; verify certificate identity locally before transmitting a password. Neither address is currently deployed or verified.

### Monitoring-only configuration

Use documented FTL environment settings so constraints survive restarts:

| Setting | Value |
|---|---|
| `TZ` | `UTC` |
| `FTLCONF_dns_upstreams` | `1.1.1.1;1.0.0.1` |
| `FTLCONF_dns_blocking_active` | `false` |
| `FTLCONF_dns_blockESNI` | `false` |
| `FTLCONF_dns_specialDomains_mozillaCanary` | `false` |
| `FTLCONF_dns_specialDomains_iCloudPrivateRelay` | `false` |
| `FTLCONF_dns_specialDomains_designatedResolver` | `false` |
| `FTLCONF_dns_queryLogging` | `true` |
| `FTLCONF_database_maxDBdays` | `7` |
| `FTLCONF_database_DBimport` | `true` |
| `FTLCONF_misc_privacylevel` | `0` |
| `FTLCONF_dhcp_active` | `false` |
| `FTLCONF_dns_listeningMode` | `ALL` inside isolated bridge, only after external ACLs verified |
| `FTLCONF_dns_revServers` | empty array/no router forwarding |

Disable unused NTP server/synchronization functions. Preserve normal cache behavior. Assess per-client rate limiting before cutover: router-forwarded household queries may be aggregated into one apparent client, making default limits unsuitable. Do not silently interpret rate limiting as content blocking or disable abuse controls without reviewing the scoped trust boundary.

During loopback-only bootstrap, disable every default adlist using the supported management API; verify effective list state and zero pilot block decisions before LAN exposure. Do not add lists. Permanent global blocking=false is the primary guarantee, with default lists additionally disabled. Test special-domain responses against standard upstreams; do not deliberately fetch adult or malware content.

Use documented `WEBPASSWORD_FILE` via a Compose secret sourced from an owner-only file outside version control (for example `~/.config/starlink-dns-pilot/admin-password`, parent 0700/file 0600). Do not embed or print secrets or expose unredacted inspect/log output. Persistent databases/backups are also private. Secret mounts avoid plaintext Compose environment values but are not encryption against host/Docker administrators.

### Verification

Before deployment, add static configuration checks for pinning, exact upstreams, no wildcard/IPv6 publication, blocking=false, retention, disabled DHCP, no privileged/capability escalation, secret references and persistent storage. Run `docker compose config --quiet` without displaying rendered secret content.

Then check local UDP and TCP A/AAAA queries, effective config, authenticated admin access and denied unauthenticated protected API access, database domain/timestamp records, and the same records after a controlled container restart. Keep test queries separate from household evidence. Verify disk capacity/clock and record the retention mechanism's cleanup granularity rather than promising exact-to-the-second deletion. Review rotated text logs and backups separately: seven-day DB retention does not expire external backups automatically.

Do not change Mac DNS. After local tests and ACLs pass, ask the user to run these on the existing Mac; they are **future tests**, not useful until the resolver is deployed:

```sh
date -u
route -n get 10.10.10.20
dig @10.10.10.20 example.com A +notcp +ignore +time=3 +tries=1
dig @10.10.10.20 example.org A +tcp +time=3 +tries=1
dig @10.10.10.20 example.net AAAA +notcp +ignore +time=3 +tries=1
curl -kI --connect-timeout 5 https://10.10.10.20:8443/admin/
scutil --dns
```

`-k` is only for an unauthenticated reachability check, not a substitute for certificate verification when logging in. The UDP `+ignore` option prevents truncation-triggered TCP fallback from being mistaken for a UDP success. Correlate Mac tests with private query logs and observed source addresses; preserve DNS error statuses instead of counting every packet response as successful resolution.

If tests fail, distinguish no route, silent firewall loss, refusal and application failure. The blocker was identified on 2026-10-22: the VM sits on an unbridged `vmbr0`, and the Proxmox host reaches the household LAN only over Wi-Fi `wlo1`. Since Proxmox already forwards IPv4 and ports 53/8443 were free, the smallest fix was a user-approved scoped DNAT relay on `wlo1`, installed at 18:23 UTC with rollback and a boot-time unit; no bridge, route or masquerade change was needed. Request Proxmox/gateway interface/route/firewall evidence without changing it. Conditional smallest fixes: if traffic is blocked by a firewall, permit only the necessary path/ports; if no inbound route exists, propose an explicit household-to-VM route on the appropriate router if supported. If that is unavailable, propose a user-approved household bridge attachment/address only after verifying the physical bridge/VLAN and address availability. Do not claim any of these fixes is needed until evidence identifies the fault.

### Backup and restore

Initial consistent full backup: during the pilot, stop only the Pi-hole service gracefully, archive the entire dedicated `/etc/pihole` volume plus Compose/non-secret configuration and image digest into a private backup, then restart the service and verify DNS. Do not copy a live SQLite file ignoring its WAL. Test restore into a fresh isolated volume with no LAN publication, same pinned image, independently supplied secret, integrity checks and known query-domain/timestamp verification. Do not overwrite the working volume to test restore. A service stop creates a DNS outage after cutover; document and schedule it explicitly. An eventual online database-only backup can use SQLite's backup API, but is not a full configuration backup.

### Conditional cutover (user only)

1. Save the current app content-filter selection and displayed DNS values privately. Verify rollback app access before proceeding.
2. Require local, restart, admin, firewall and Mac UDP/TCP tests to pass. Mac success alone does not prove the router will forward to that address; perform immediate router/household verification after app cutover.
3. In Starlink app, disable its content filter, then enable Custom DNS.
4. Proposed Primary: `10.10.10.20` **only if verified**. Backup: leave empty if app permits; if mandatory, assess whether duplicate `10.10.10.20` is accepted (no redundancy). Do not apply unverified/invalid values. A second independent validated logging resolver would offer resilience but is outside this pilot.
5. IPv6 fields: no validated resolver address exists. Leave empty only if the app accepts this, then inspect actual client DNS advertisements. Do not retain Families IPv6 entries or substitute public IPv6 DNS silently. If required fields or automatic IPv6 fallback prevent the intended configuration, stop and return the limitation to the user.
6. Save, then immediately verify ordinary DNS queries arrive without explicit `@` overrides, classify apparent source as client/router/NAT gateway, and compare Mac `scutil --dns` and explicit IPv4/IPv6-path tests. Public ordinary domains only; no household query dump in chat.

### 24–48-hour observation after cutover

Continue routine observation under the single pilot authorization after the user confirms the app change. Sample collector health, database size/free disk and effective config at a documented cadence (initially every 60 seconds) and query counts/rate-limit warnings at least hourly. Use timestamps in UTC for comparison; display UTC where useful. Establish start/end times and actual duration. Do not call sparse checks proof of uninterrupted service: record monitoring gaps, failed checks, VM/container restarts and any collector downtime, with detection uncertainty.

Inspect normal household query arrivals, requester identity (individual clients versus router/NAT), retained timestamps, rate-limit events and growth. Ask the user for a few ordinary known service-use times and compare observed query names around those windows without assigning human behavior or inventing missing domains. Absence of a query may reflect caching, alternate DNS or no lookup, not absence of service use. Review Mac DNS configuration and observed IPv6 resolver paths before/after cutover; do not capture packets or enforce DNS interception. Report measured coverage and remaining encrypted-DNS/IPv6 uncertainty. A 24-hour minimum may complete the pilot; extend to 48 hours if practical, recording which duration actually ran.

Persist sampler state/evidence privately and provide a resumable execution method; do not assume a chat session stays alive for days. At completion, report aggregate findings without publishing household query lists. No AI/custom application is implemented; follow-on scope is in spec.md.

### Availability, rollback and residual gaps

With a single Pi-hole address and no independent fallback, a VM/container/network failure stops new uncached name resolution through it; existing sessions and cached records may continue until expiry. `unless-stopped` restarts crashes/boot but not an intentional stop and does not repair a powered-off VM or broken route. Queries while the service is unavailable are not recoverable later.

A public backup (even standard Cloudflare) may be used while Pi-hole is healthy and create logging gaps. It is an explicit availability-over-coverage choice, never a hidden default. Two identical fields are still one failure domain.

Default recovery: keep Starlink content filtering **off** and replace the pilot Custom DNS entries with standard Cloudflare `1.1.1.1` / `1.0.0.1`, using only app fields and paths verified at handoff. Where the app requires IPv6 entries, standard unfiltered equivalents are `2606:4700:4700::1111` / `2606:4700:4700::1001`; validate the actual client/router path and app behavior before promising these as a working recovery path. Do not disable Custom DNS if that silently restores filtering or unverified defaults. Recovery intentionally restores availability at the cost of pilot query coverage. Verify ordinary resolution and the resulting resolver configuration, then stop/remove only the pilot service and scoped ACLs if desired. Retain private data/backups until explicitly disposed of.

Separate, opt-in exact-previous-state recovery: **only if the user selects it**, disable pilot Custom DNS and restore the saved previous content-filter selection. If manual original entries are needed, the original Families addresses were `1.1.1.3`, `1.0.0.3`, `2606:4700:4700::1113`, `2606:4700:4700::1003`. This explicitly restores filtering and is not the default recovery. No Families address belongs in pilot upstreams or routine fallback.

IPv6 transport is unverified: AAAA queries over IPv4 can be logged, but that does not prove clients use Pi-hole for DNS over IPv6. DoH/DoT, Private Relay, VPNs, cached queries and alternate resolvers can bypass logging; this monitoring-only pilot does not block or redirect them. All data remains labeled DNS queries, not confirmed contacts or browsing duration.

## Specialists, tools and sources

`docker-expert` is installed and loaded for Compose, persistence, secrets and networking. No agents delegated. Tools: local read/glob/shell for discovery and checks; official web documentation for current version/settings; Docker Compose/dig/curl/SQLite for implementation verification; optional browser for authenticated UI without sharing secrets. Root firewall inspection evidence was supplied by the user; application remains a user-run intervention. Docker root-equivalent access will not be used to bypass sudo restrictions.

- https://docs.pi-hole.net/docker/
- https://docs.pi-hole.net/docker/configuration/
- https://docs.pi-hole.net/ftldns/configfile/
- https://docs.pi-hole.net/database/query-database/
- https://github.com/pi-hole/docker-pi-hole/releases/tag/2026.10.0
- https://docs.docker.com/engine/network/packet-filtering-firewalls/

## Planned affected files

New dedicated `dns-pilot/` Compose, static checks, scoped firewall/startup integration and operations instructions after combined approval. Private secret/data/backups outside tracked sources. No existing Starlink probe/evidence or unrelated service configuration is overwritten.
