# DNS pilot operations

## State and boundaries

Revision 2 is authorized. **Starlink custom DNS is now `192.168.1.10`; household queries are being logged. Attribution is household-level (router `192.168.1.1`), not per-device.** Ubuntu and Proxmox changes remain inside the reviewed pilot scope. Host resolved, routes, bridges, management ports and other VMs are unchanged. The existing stopped Coder container is preserved.

- Working local test DNS: `127.0.0.1:1053` UDP/TCP, from this VM only.
- Working local administration: `https://127.0.0.1:8443/admin/`, from this VM only.
- Published private-address DNS: `10.10.10.20:53`; admin: `https://10.10.10.20:8443/admin/`. Verified from the VM only. Not reachable from the household LAN: the VM sits behind Proxmox `vmbr0` with no household uplink. Approved household endpoint after the Proxmox relay is installed: `192.168.1.10` (DNS 53 TCP/UDP, admin 8443).
- Image: `pihole/pihole:2026.10.0@sha256:d34134716fc32038b052a8674c7c6879e0ff21f0e6d8af345166fffa2c27c113`.
- Persistent volume: `starlink-dns-pilot_etc-pihole`, mounted at `/etc/pihole`.
- Secret: `~/.config/starlink-dns-pilot/admin-password`, mode 0600 in an owner-only directory. View it locally if needed; never paste it in chat or commit it. Docker/host administrators can access this secret and stored data.
- Database retention: 7 days, imports enabled, disk-write interval 60 seconds. Retention cleanup is periodic, not a hard-to-the-second deletion guarantee. Text logs and private backups have separate lifetimes; do not retain backups beyond the user's chosen retention/privacy requirements.
- Only upstreams: standard unfiltered Cloudflare `1.1.1.1;1.0.0.1`. No forwarding or conditional forwarding to Starlink.
- Blocking disabled permanently via environment; default list disabled via documented API, verified on disk and after restart. Special-domain suppression, DHCP and NTP functions disabled. Normal DNS/cache/history remain enabled.
- Default per-client rate limit remains 1000 queries/60 seconds. After cutover inspect warnings: router/NAT aggregation may require a separately reviewed adjustment. No content filtering is enabled.

## Verified so far (2026-10-22)

`task dns-check` passes seven static checks covering Compose, firewall and Proxmox-relay contracts/syntax. `task dns-test-local` passes four runtime checks covering UDP/TCP example-domain resolution, effective settings, admin authentication/unauthenticated denial, disabled lists and timestamped persisted public test queries. Static checks are **not** a test of actual root firewall or relay enforcement.

Local A and AAAA queries succeeded; selected special-domain response statuses matched standard Cloudflare. No content was fetched. A controlled restart preserved settings and timestamped query records. A graceful-stop full-volume backup was extracted into a distinct unpublished volume: both restored SQLite databases passed integrity checks and six timestamped example-domain test records were present. Restore integrity checks opened the **isolated restored copy** writable to support SQLite journal handling; no live database was overwritten.

Private initial backup: `PRIVATE_DNS_BACKUPS/20261022T175608Z/`. Isolated restore volume: `starlink-dns-pilot_restore-check-20261022t175608z`. These contain private configuration/evidence and are not committed.

TLS certificate SHA-256 observed locally:

```text
<recorded locally; not published>
```

The certificate is self-signed. Compare this fingerprint before trusting remote admin login. Recreating/restoring TLS files can change it; investigate differences, do not blindly accept them. Tests use an unauthenticated TLS bootstrap on loopback only. Never use `curl -k` to send an admin password remotely.

## Completed user-run root protection

User supplied successful installation and `--check` output. Installed root-owned guard matches the reviewed source. Loaded effective Docker `ExecStartPre` includes the guard with `ignore_errors=no`; direct drop-in file inspection is denied by parent-directory permissions, so effective service configuration and supplied root output were used instead. Root firewall pre-change backup is `/var/lib/starlink-dns-pilot-firewall-backup.XXXXXXXX`. Actual Docker restart/reboot reapplication is not empirically tested.

After publication at approximately 18:02 UTC, VM-local UDP/TCP queries to `10.10.10.20:53` succeeded and HTTPS returned the expected login redirect. An independent temporary container on Docker's default bridge could not query UDP/TCP DNS or reach HTTPS on that address (timeouts); this is a tested untrusted-source path, not proof about every external route. Four local runtime checks passed again. Trusted household-source access awaits the household-client tests below.

The following installation instructions are retained for reference; **do not reinstall merely to run household-client tests**.

Review `firewall-guard.sh` and `install-firewall.sh`, then run on Ubuntu:

```sh
sudo bash /home/operator/github/household-dns-insights-public/dns-pilot/install-firewall.sh
```

Share the resulting output, not the sudo/admin passwords. The installer:

- Backs up existing IPv4/IPv6 rules privately under `/var/lib/starlink-dns-pilot-firewall-backup.*`.
- Installs a root-owned guard and a Docker service `ExecStartPre` drop-in.
- Adds only pilot-specific chains/jumps; never flushes rules, enables UFW or changes policies. Preserves SSH/Tailscale access, router settings and all unrelated services.
- Restricts new household-facing DNS/admin requests to source `192.168.1.0/24`. Host-local access remains possible. No broad allowance for the VM subnet or Tailscale is added.
- Uses raw PREROUTING before Docker DNAT/Tailscale INPUT accepts, host INPUT protection and DOCKER-USER forwarding protection for the dedicated `br-sl-dns` bridge, including directly routed container traffic. Established upstream replies are retained.
- Does **not** restart Docker or publish LAN ports. Future Docker starts run the guard before container autostart. Deliberate fail-closed tradeoff: if guard loading fails, **Docker startup is blocked, including unrelated containers**, until the guard is repaired or its specific drop-in is removed by the administrator. This does not stop currently running services during installation.

After installation, independently verify rules, ordering and the service drop-in. A later Docker restart/host reboot must recheck protection; no restart/reboot has been forced for testing. Do not declare reboot persistence empirically tested merely because the hook is installed.

## LAN publication gate (agent, only after root output verified)

The root installer does not publish DNS. After rule verification, apply the prepared override:

```sh
docker compose -f dns-pilot/compose.yaml -f dns-pilot/compose.lan.yaml up -d
```

Then verify actual host bindings, local service behavior and at least one allowed and denied network path with root rule counters. Do not count source-restricted Compose bindings alone as an ACL. Do not change app settings yet. If NAT changes apparent source to the gateway, stop and request evidence before broadening trust.

## Proxmox household relay (installed 2026-10-22 18:23 UTC)

**Installed by the user** at 18:23:18 UTC. Reported verification: `--print` and `--check` passed without changes; `--install` applied exactly two forwarding rules; `starlink-dns-relay.service` is `active (exited)`, `enabled`, and its `ExecStart` reapply exited 0. Pre-change ruleset backup: `/var/lib/starlink-dns-relay/pre-install.XXXXXXXX`. Household reachability is **still unverified** — the household-client test below has not run yet.

**Diagnosis (read-only evidence).** Proxmox reaches the household LAN only over Wi-Fi: `wlo1` = `192.168.1.10/24`, default gateway `192.168.1.1`. The VM bridge `vmbr0` = `10.10.10.1/24` with `bridge-ports none`, so the Ubuntu VM is on a private network with no household link. Existing `nft` state has an empty `table inet filter` and one masquerade rule for outbound VM traffic on `wlo1`. Proxmox forwards IPv4 and ports 53/8443 are free.

**Consequence.** Household devices have no route to `10.10.10.20`. That is why the household laptop (`192.168.1.20`) timed out at 18:04:46 and 18:07:31 UTC — via `192.168.1.1` for `10.10.10.20` — with zero matching persisted queries. The Ubuntu-side ACL was not shown to be at fault, and the laptop is a permitted source.

**Approved scope (user "ok", 2026-10-22).** `dns-pilot/proxmox-forwarding.sh` adds one owned nftables table `ip starlink_dns_pilot`:

- on `wlo1`, source `192.168.1.0/24`, destination `192.168.1.10`, UDP 53 → DNAT `10.10.10.20:53`
- on `wlo1`, source `192.168.1.0/24`, destination `192.168.1.10`, TCP 53 and 8443 → DNAT `10.10.10.20`
- counters on both rules; client source addresses preserved (no SNAT)

It also installs a self-contained root helper `/usr/local/libexec/starlink-dns-relay` and an enabled `starlink-dns-relay.service` that reapplies the table at boot. It refuses to run unless `wlo1` is `192.168.1.10/24`, `vmbr0` is `10.10.10.1/24`, IPv4 forwarding is on, ports 53/8443 are still free, and any pre-existing table or file carries its own ownership marker. It never flushes rulesets, changes routes/bridges/policies, touches management port 8006, SSH, Tailscale or the existing masquerade rule, and never restarts Docker, networking or the firewall services.

**Install (copy from the Ubuntu VM, review, then run on Proxmox as root):**

```sh
# on the Ubuntu VM
scp /home/operator/github/household-dns-insights-public/dns-pilot/proxmox-forwarding.sh root@192.168.1.10:/root/

# on the Proxmox host
bash /root/proxmox-forwarding.sh --print
bash /root/proxmox-forwarding.sh --check
bash /root/proxmox-forwarding.sh --install
```

`--print` shows the exact nftables policy; `--check` validates the complete transaction with `nft -c` without applying it. `--install` backs up the current ruleset under `/var/lib/starlink-dns-relay/pre-install.*/` and prints the path, then replaces only its own marker-checked table and verifies exactly two forwarding rules exist. A reinstall briefly removes and re-adds that table (milliseconds); boot-time application is add-only. Share the output, not passwords or the Wi-Fi key.

**Expected household endpoints after install.** DNS `192.168.1.10:53` (TCP/UDP), admin `https://192.168.1.10:8443/admin/`. `10.10.10.20` remains the VM-internal address and is not household-reachable.

**Rollback (Proxmox, root):**

```sh
bash /usr/local/libexec/starlink-dns-relay --rollback
```

This disables the unit and deletes only the pilot table. Restoring the previous ruleset from the pre-install backup is only needed if something else was changed outside this pilot.

**Residual risk.** Ports 53/8443 on `192.168.1.10` are reserved for this relay while it is installed; another service on Proxmox cannot use them simultaneously. Other VMs keep their existing NAT, bridges and routes, but after any Starlink DNS cutover they may depend on Pi-hole for new lookups like every other household client. If the relay unit fails after a Proxmox reboot, household DNS through this path fails closed while the VM stays reachable over Tailscale. Boot persistence has not been empirically tested yet; do not force a reboot just to test it.

## Household-client reachability gate — passed

Run on the household laptop (`192.168.1.20`) connected to household Wi-Fi **after** the Proxmox relay is installed and its output verified. No DNS change on the client:

```sh
date -u
route -n get 192.168.1.10
dig @192.168.1.10 example.com A +notcp +ignore +time=3 +tries=1
dig @192.168.1.10 example.org A +tcp +time=3 +tries=1
dig @192.168.1.10 example.net AAAA +notcp +ignore +time=3 +tries=1
curl -kI --connect-timeout 5 https://192.168.1.10:8443/admin/
scutil --dns
```

**Result (2026-10-22 18:24:19 UTC).** `route -n get 192.168.1.10` resolved to en0 directly (no gateway), confirming same-subnet Wi-Fi reachability. UDP A, TCP A and UDP AAAA each returned `NOERROR` with answers; `curl -kI` returned `302` to `/admin/login`. Proxmox counters moved by exactly 2 UDP and 2 TCP packets. Pi-hole stored three rows for that window with **client `192.168.1.20`** — the real device address, not the Proxmox gateway — so per-device DNS attribution works on this path.

Two rows were answered from stale cache (`status` CACHE_STALE, TTL 0, EDE 3 "Stale Answer"); `example.net` AAAA was freshly forwarded. This is FTL's default serve-stale behaviour: an expired cached entry is returned immediately while an upstream refresh is issued. It is not a failure and it is logged as stale, not as a normal cache hit. Later queries returned fresh records (TTL 66, 0 ms). Treat `TTL 0` / EDE 3 answers as stale cache entries when reading evidence.

`curl -kI` is an unauthenticated connectivity test only. Redact unrelated VPN/internal domains from `scutil --dns`.

**Prior failed attempt (kept for the record).** 18:04:46 and 18:07:31 UTC against `10.10.10.20`: UDP/TCP DNS and HTTPS all timed out, no matching rows in the query database, no `SLDNS-FWD` hits. Root counters on Ubuntu showed the client was never blocked — the traffic never arrived, because the VM has no household route.

## Cutover verified (2026-10-22 18:27 UTC)

User saved Starlink custom DNS `192.168.1.10` with content filtering off. The app accepted an **empty Backup field and empty IPv6 fields**, and the user reports normal household browsing afterwards. Observed within minutes:

- First router-forwarded query at 18:27:48 UTC; queries kept arriving afterwards (264 rows by 18:31, 316 by 18:33).
- Status mix over a 15-minute window: forwarded 127, cache 64, stale cache 29, in-progress 102, retried 1. No rate-limit warnings; upstream RTT 42–46 ms.
- 100 of the 102 in-progress rows have a same-domain completed row within 3 seconds. They are coalesced duplicate/retry requests from the router during the cache flush at cutover, not unanswered queries.
- 55–69 distinct domains per window, consistent with ordinary household activity.

**Attribution is household-level.** Every household query arrives as client `192.168.1.1`, because the Starlink router forwards to the configured nameserver (`https://starlink.readme.io/docs/dns-and-routing`: "Starlink routers will forward requests to these nameservers"). Individual LAN devices are not visible on this path. Device addresses appear only when a client queries `192.168.1.10` directly — verified earlier with the household laptop as `192.168.1.20`. Never infer a device from timing or presence guesses.

**`dig @192.168.1.1` from the Ubuntu VM returns SERVFAIL — this is a test artifact, not an outage.** Proxmox masquerades the VM's source to `192.168.1.10`, which is the router's own configured nameserver, so the router refuses to forward it to itself. During that check the household path was already healthy and Pi-hole was already logging. Test the router path from a household device instead (`dig @192.168.1.1 example.com` on a household device that is not overriding DNS).

**Tailscale bypasses logging.** With MagicDNS active, the household laptop resolves through `100.100.100.100`, so its queries never reach the router or Pi-hole. This is a coverage gap to disclose, not something to block or intercept.

**Observation started.** `PRIVATE_OBSERVATION/samples.jsonl` receives one aggregate sample every 15 minutes for 48 hours (`python3 dns-pilot/observe_queries.py --loop --hours 48`). Samples contain counts only — no domains, URLs or client names — and the directory is git-ignored. Resume after interruption by restarting the same command; the file appends. The initial pre-loop samples were discarded because the observation test wrote into the live file; tests now redirect to a temporary directory (`STARLINK_OBSERVATION_DIR`), so the series contains only real loop samples from approximately 18:48 UTC.

## Reporting correction and non-disruptive inspection (2026-10-23)

The original sampler process started at **2026-10-22 18:33:48 UTC**. Its 48-hour
deadline is **2026-10-24 18:33:48 UTC**.
Do not confuse the local date with the UTC date. A later `--hours 48` invocation
starts a new relative 48-hour timer; it does not preserve the original cutoff.
No restart or deadline change was applied to PID 37817 during report preparation.

The sampler code on disk now uses one read snapshot for totals/outcomes and
measures actual timestamp-based 60-second row spans. Existing process code and
historical samples are unchanged. `queries_total_all_time` remains a compatibility
key for **retained rows**, not an ever-increasing lifetime total. The warning
counter covers available rotated container logs, not a particular sample window.
The old literal `rate.limit` test could miss `Rate-limiting` text; the new matcher
is tested. An independent corrected scan found zero available-log messages; old
sample zeros alone were not sufficient evidence.
The database may lag live requests by about 60 seconds. Use `task dns-status`
for container health; `task dns-health` collects query evidence and appends a sample.

Read-only reporting proof of concept: `destination_report.py` uses the existing
FTL SQLite CLI with `query_only`, one statement and a timeout. It neither copies
an active SQLite database nor changes the resolver. Every query-view row in the
selected hour remains in a private JSON export. Rendered JSON/HTML separates
reverse lookups, retains query types/retries, and marks periodic timing as a
suspected-probe heuristic only. Router-forwarded observations can include requests
generated by the router; never subtract guessed probes to claim an activity bound.
See `../README.md#one-hour-destination-report-proof-of-concept` for the local report
and offline re-render command. Classifications/exports have their own lifetimes;
they are not expired by Pi-hole's seven-day retention. No cleanup is automatic.

The one-hour report measured a router-forwarded peak of **976 persisted rows in
an inclusive 60-second span** (04:47:30.516375–04:48:30.516375 UTC on 23 October).
Dividing a 900-second total by 15 would hide that burst. Neither this measurement
nor zero observed warnings reconstructs limiter headroom; no rate-limit setting
was changed.

## App cutover and recovery

**Applied by the user on 2026-10-22 at ~18:27 UTC.** This section is retained for rollback and for any future resolver change.

| Field | Value |
|---|---|
| Primary | `192.168.1.10` |
| Backup | leave empty if the app accepts it; otherwise repeat `192.168.1.10` (no added resilience) |
| IPv6 | leave empty; no household-routable IPv6 resolver exists |
| Content filtering | must be **off** (Starlink requires this for Custom DNS) |

Before saving, record the current values privately for rollback: `1.1.1.3`, `1.0.0.3`, `2606:4700:4700::1113`, `2606:4700:4700::1003`, filtering enabled. Do not paste the Wi-Fi PSK again.

Steps:

1. Save existing settings privately and verify app access for recovery.
2. Disable Starlink content filtering, as the app requires for Custom DNS.
3. Enter the values above. Do not silently select public backup DNS; if the app forces a non-empty backup, repeating the same address is acceptable but adds no redundancy.
4. If the app rejects empty IPv6 fields or auto-falls back, stop and report the exact field behaviour instead of guessing an address.
5. Save manually and tell the agent when applied. Immediately verify ordinary queries without explicit `@` overrides, their apparent requester, client DNS configuration and IPv6 gaps. Then begin a resumable 24–48-hour observation test; it has not started yet.

A successful household-client test proves household reachability, but not that router-forwarded requests arrive with preserved source addresses. Attribution after cutover must be checked, not assumed: if clients collapse to the router or gateway address, keep household-level attribution and never infer devices by guesswork.

Default recovery: keep filtering **off**, use standard public Cloudflare `1.1.1.1` / `1.0.0.1` through verified app fields. If IPv6 is required and its path verified, standard equivalents are `2606:4700:4700::1111` / `2606:4700:4700::1001`. Verify ordinary resolution and actual resolver settings. Public recovery restores availability but bypasses logging. Restore previous Families/filter settings only if explicitly selected, never as default recovery.

If the VM/container stops after cutover with no independent fallback, new uncached lookups through it fail. Cached data/existing sessions may continue temporarily. `unless-stopped` restarts crashes/boot, not intentional stops or a powered-off VM. A public backup can receive queries even while Pi-hole is healthy; duplicate addresses provide no redundancy. An independent second logging resolver would be separate future work.

**The household path now has three dependencies:** Starlink Wi-Fi, the Proxmox relay unit, and the VM/container. Loss of Proxmox Wi-Fi or the relay removes DNS even while the VM is healthy over Tailscale. FTL's stale cache can keep already-seen names resolving briefly, but it is not a fallback and must not be described as one.

If the VM/container stops after cutover with no independent fallback, new uncached lookups through it fail. Cached data/existing sessions may continue temporarily. `unless-stopped` restarts crashes/boot, not intentional stops or a powered-off VM. A public backup can receive queries even while Pi-hole is healthy; duplicate addresses provide no redundancy. An independent second logging resolver would be separate future work.

AAAA answers over IPv4 are supported, but **not proof of IPv6 DNS coverage**. DoH/DoT, Private Relay, VPNs and caching can bypass query observations; this pilot does not block or intercept them. Label everything DNS queries, not confirmed connections or app/browsing duration.

## Consistent backup and restore

Before cutover, a brief Pi-hole-only stop is safe. After cutover it is a DNS outage: schedule with the user or separately implement an online SQLite backup. Never simply copy an active SQLite DB without its transaction state.

From project root, in a bash shell (the tested method):

```bash
set -euo pipefail
umask 077
backup="$PWD/PRIVATE_DNS_BACKUPS/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 -p "$backup"
image=$(docker inspect starlink-dns-pilot --format '{{.Config.Image}}')
docker compose -f dns-pilot/compose.yaml stop pihole
trap 'docker compose -f dns-pilot/compose.yaml start pihole' EXIT
docker run --rm --network none --entrypoint /bin/sh \
  -v starlink-dns-pilot_etc-pihole:/data:ro -v "$backup:/backup" "$image" \
  -c 'umask 077; tar czpf /backup/etc-pihole.tar.gz -C /data . && chown 1000:1000 /backup/etc-pihole.tar.gz'
cp dns-pilot/compose.yaml "$backup/compose.yaml"
printf '%s\n' "$image" > "$backup/image.txt"
docker compose -f dns-pilot/compose.yaml start pihole
trap - EXIT
```

If the LAN override is active, service stop/start targets the same existing container and preserves its bindings; do not run base-only `up` accidentally. Keep password file separately protected; a full volume archive includes private configuration, query history and password hashes, so protect it like a secret.

Restore check without overwriting production:

```bash
# Set backup to the chosen existing private archive directory first.
image=$(docker inspect starlink-dns-pilot --format '{{.Config.Image}}')
restore="starlink-dns-pilot_restore-check-$(date -u +%Y%m%dT%H%M%SZ)"
docker volume create "$restore"
docker run --rm --network none --entrypoint /bin/sh \
  -v "$restore:/restore" -v "$backup:/backup:ro" "$image" \
  -c 'tar xzpf /backup/etc-pihole.tar.gz -C /restore'
docker run --rm --network none --entrypoint pihole-FTL \
  -v "$restore:/restore" "$image" sqlite3 /restore/pihole-FTL.db 'PRAGMA integrity_check;'
docker run --rm --network none --entrypoint pihole-FTL \
  -v "$restore:/restore" "$image" sqlite3 /restore/gravity.db 'PRAGMA integrity_check;'
```

Also verify expected query counts/timestamps locally, never print household lists. Full service recovery requires a stopped service, a fresh volume wired to the pinned image/config and independently provided secret, then loopback validation before LAN publication. Do not unpack a backup over the active volume. No `down -v`, broad delete or blind firewall restore is part of this procedure. Old backups and restore-test volumes remain private until explicitly cleaned up.

## References

- https://docs.pi-hole.net/docker/configuration/
- https://docs.pi-hole.net/ftldns/configfile/
- https://docs.pi-hole.net/database/query-database/
- https://github.com/pi-hole/FTL/blob/v6.8/src/api/docs/content/specs/lists.yaml
- https://docs.docker.com/engine/network/port-publishing/ (Docker >=28 loopback restriction; installed version 29.9.1)
- https://docs.docker.com/engine/network/packet-filtering-firewalls/
