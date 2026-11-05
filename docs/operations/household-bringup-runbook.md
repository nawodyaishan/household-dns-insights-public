# Household bring-up runbook: Pi-hole → Proxmox relays → Starlink DNS → services

Repeatable, ordered procedure to bring the full household monitoring stack up
(after a reboot, a host maintenance window, or from a stopped state) and to
tear it down safely. The DNS relay phases were executed with verified evidence
(2026-10-22 for the DNS relay, 2026-10-28 for the shared dashboard path). The
**owner dashboard relay (8789) and the stack lifecycle commands are
offline-verified only** — they are first executed at gate L1, and this runbook
is their reviewed execution script.

## Safety rules (always)

- Root commands are run **by the owner**, not by an agent or automation.
- Never flush nftables rulesets, never touch the Starlink router config, bridges,
  routes, or anything except the two ownership-marked tables below.
- Pi-hole **blocking stays off** (monitoring-only pilot). The Starlink DNS toggle
  in the app is the owner's manual action, never scripted.
- Raw queries/domains stay in private files; do not paste them into chat or tickets.
- One phase at a time; verify each phase before starting the next.

## Fixed names and addresses

| Thing | Value |
|---|---|
| Ubuntu VM (this repo's host) | `10.10.10.20/24` on `ens18`, behind Proxmox `vmbr0` |
| Proxmox host | `pve-zenbook`, Wi-Fi `wlo1` = `192.168.1.10/24`, bridge `vmbr0` = `10.10.10.1/24` |
| DNS pilot container | `starlink-dns-pilot` (`dns-pilot/compose.yaml`), publishes `10.10.10.20:53` and `10.10.10.20:8443` |
| DNS relay (Proxmox) | unit `starlink-dns-relay.service`, nft table `ip starlink_dns_pilot` — **2 rules**: UDP 53 and TCP {53, 8443} DNAT → `10.10.10.20` |
| Shared dashboard relay (Proxmox) | unit `household-report-relay.service`, nft table `ip household_report_relay` — **1 rule**: TCP 8787 DNAT → `10.10.10.20:8787` |
| Owner dashboard relay (Proxmox) | unit `household-report-owner-relay.service`, nft table `ip household_owner_relay` — **1 rule**: TCP 8789 DNAT → `10.10.10.20:8789`; helper `dns-pilot/dashboard-owner-relay.sh` refuses to run while the shared table still forwards 8789 (that historical mixed rule needs a deliberate migration first) |
| Dashboard VM guard (VM) | helper `dns-pilot/dashboard-vm-guard.sh`, nft table `inet household_report_guard` (both ports/bridges), Docker drop-in with `ExecStartPre` (fail-closed) |
| Dashboard app | container from `destination-report/compose.yaml`, published **only** on the approved binds: shared `10.10.10.20:8787` or owner `10.10.10.20:8789` (one profile at a time per compose merge), IPv4-only bridge |
| Household endpoints | DNS `192.168.1.10:53`, admin `https://192.168.1.10:8443/admin/`, shared dashboard `http://192.168.1.10:8787`, owner dashboard `https://192.168.1.10:8789` |
| Stack lifecycle | `task stack-setup|check|status|start|stop|restart|upgrade|rollback|backup|restore|uninstall CONFIG=…` — see [stack lifecycle runbook](stack-lifecycle-runbook.md) |

After a **normal reboot**, all units are boot-persistent; in most cases only the
"Reboot verification" checks below are needed, not a reinstall.

---

## Phase 1 — Start Pi-hole (VM, non-root)

```sh
cd ~/github/starlink-monitoring
docker compose -f dns-pilot/compose.yaml up -d
```

Verify (all read-only):

```sh
docker ps --filter name=starlink-dns-pilot --format '{{.Names}}\t{{.Status}}'
docker exec starlink-dns-pilot pihole status | head -8
dig +time=3 +tries=1 @10.10.10.20 example.com A +short
```

Expected: `Up … (healthy)`; `[✓] FTL is listening on port 53`; `[✗] Pi-hole
blocking is disabled` (this line **must** stay); an A record answer.

Recording check (counts flush in 60-second batches):

```sh
docker exec starlink-dns-pilot pihole-FTL sqlite3 /etc/pihole/pihole-FTL.db \
  "PRAGMA query_only=ON; SELECT COUNT(*), MAX(id) FROM query_storage;"
sleep 65   # repeat the SELECT; count must have increased
```

Stop here if blocking is enabled, resolution fails, or the count does not move.

## Phase 2 — Proxmox relays (`pve-zenbook`, root)

Copy scripts if not present, then from the repo on the VM:
`scp dns-pilot/proxmox-forwarding.sh dns-pilot/dashboard-proxmox-relay.sh root@pve-zenbook:/root/`

On Proxmox, for **each** helper (`proxmox-forwarding.sh` first, then
`dashboard-proxmox-relay.sh`, then — only when the owner dashboard is being
published — `dashboard-owner-relay.sh`):

```sh
bash /root/proxmox-forwarding.sh --check       # DNS relay: syntax/topology, no changes
bash /root/proxmox-forwarding.sh --install     # installs/enables starlink-dns-relay.service
bash /root/dashboard-proxmox-relay.sh --check  # shared dashboard relay (8787)
bash /root/dashboard-proxmox-relay.sh --install
bash /root/dashboard-owner-relay.sh --check    # owner dashboard relay (8789), refuses a mixed shared table
bash /root/dashboard-owner-relay.sh --install
```

Verify:

```sh
systemctl is-enabled starlink-dns-relay.service household-report-relay.service household-report-owner-relay.service
bash /root/proxmox-forwarding.sh --status | grep -c 'dnat to 10.10.10.20'   # expect 2 rules
bash /root/dashboard-proxmox-relay.sh --status | grep -c 'dnat to 10.10.10.20:8787'  # expect 1
bash /root/dashboard-owner-relay.sh --status | grep -c 'dnat to 10.10.10.20:8789'    # expect 1
```

Expected lines on install: `Relay table has 2 forwarding rules, expected 2.`
(DNS), `Scoped dashboard relay present; DNS pilot relay unchanged.` (shared
dashboard) and the owner relay's scoped 8789 confirmation. Each helper refuses
unowned tables and prints a private backup path. The two dashboard relays are
**independently owned**: removing one never removes the other, and neither
touches DNS/8443.

From a **household device**, confirm the relay path before any Starlink change:

```
dig @192.168.1.10 example.com          # or: nslookup example.com 192.168.1.10
```

An answer here proves `household → wlo1 → DNAT → VM Pi-hole` end-to-end.

## Phase 3 — VM dashboard guard and app (VM)

Guard first, publication second (owner, root):

```sh
cd ~/github/starlink-monitoring
sudo bash dns-pilot/dashboard-vm-guard.sh --check
sudo bash dns-pilot/dashboard-vm-guard.sh --install
```

Publish the app (owner, docker group):

```sh
HR_CONFIG_DIR="$HOME/.config/starlink-monitoring/campaign" \
HR_INPUT_DIR="$HOME/.local/share/household-report/input" \
HR_STATE_DIR="$HOME/.local/share/household-report/state" \
HR_PORT=8787 HR_LAN_BIND=10.10.10.20 \
HR_ALLOWED_HOSTS=192.168.1.10:8787 HR_PUBLIC_URL=http://192.168.1.10:8787 \
docker compose -f destination-report/compose.yaml -f destination-report/compose.lan.yaml up -d
```

Verify:

```sh
docker ps --format '{{.Names}}\t{{.Ports}}' | grep household   # one bind: 10.10.10.20:8787 only
curl -s -o /dev/null -w '%{http_code}\n' --header "Host: 192.168.1.10:8787" http://10.10.10.20:8787/  # 200
curl -s -o /dev/null -w '%{http_code}\n' http://10.10.10.20:8787/                                     # 400 (Host refused)
```

Household device: `http://192.168.1.10:8787/` must render the landing page.

### Phase 3b — Owner dashboard profile (8789, https + AI-capable)

The owner profile is prepared offline and published only after `owner-preflight`
passes; it never coexists with a conflicting bind (the compose merge must yield
exactly one approved host binding):

```sh
cd ~/github/starlink-monitoring
task owner-preflight                       # offline: origin pair, TLS coverage, merge shape
task stack-setup CONFIG=~/.config/starlink-monitoring/destination-report/operator.json
task stack-start CONFIG=...                # starts the selected pair only: no campaign, no network change, no spend
task stack-status CONFIG=... MODE=offline  # sanitized: release drift, journal, collector state
```

Verify from a household device: `https://192.168.1.10:8789/` renders the login
page and the certificate covers `192.168.1.10`. The shared instance keeps
serving `http://192.168.1.10:8787` and can never dispatch AI, including via
direct POSTs. The full lifecycle (stop/restart/upgrade/rollback/backup/restore/
uninstall) is documented in the [stack lifecycle runbook](stack-lifecycle-runbook.md).

## Phase 4 — Starlink app DNS (owner, manual app action)

In the Starlink app, re-enable the Pi-hole DNS address **`192.168.1.10`** for
household clients. Nothing in this repo performs this step.

Verify from a household device (default resolver, no `@`):

```
dig example.com        # or simply browse to a site
```

Then confirm household queries are being recorded (on the VM):

```sh
docker exec starlink-dns-pilot pihole-FTL sqlite3 /etc/pihole/pihole-FTL.db \
  "PRAGMA query_only=ON; SELECT COUNT(*) FROM query_storage;"
# repeat after ~65 s; the count must keep growing while devices are active
```

## Phase 5 — Start the campaign (requires explicit owner authorization)

```sh
cd ~/github/starlink-monitoring
HR_BRIDGE_CONFIG="$HOME/.config/starlink-monitoring/campaign/campaign-bridge.json" \
HR_LAN_RELAY_IP=192.168.1.10 \
task campaign-preflight MODE=live          # must pass every check first
HR_BRIDGE_CONFIG="$HOME/.config/starlink-monitoring/campaign/campaign-bridge.json" \
HR_LAN_RELAY_IP=192.168.1.10 \
task campaign-start START=YES DAYS=3 RETAIN_DAYS=7
task campaign-status                       # sanitized: no domains/clients
```

`campaign-start` re-runs the live preflight and refuses to run otherwise. The
bridge timer (`household-campaign-bridge.timer`) imports settled hourly windows
every 60 seconds; observations appear at `http://192.168.1.10:8787` as windows
settle. Never bypass a failed preflight.

### Short runs: clip the campaign to 12 hours (verified 2026-10-30)

`--days` accepts whole days only (3/4/5), so a shorter run starts a 3-day
campaign and finishes it early — the recorded end is clipped to the stop time
and the frozen report covers exactly the hours that ran, with no invented
coverage for the rest.

1. Note the `updated_utc` (or `start_epoch`) that `campaign-start` prints — the
   campaign began the second that command returned. The historical start is redacted.
2. Add 12 hours and set a reminder; stop no earlier than the calculated time.
3. At the 12-hour mark:

```sh
cd ~/github/starlink-monitoring
task campaign-stop STOP=YES
```

4. After the stop completes, the campaign finalizes and one frozen report covers
   the whole recorded window; `task campaign-report CAMPAIGN=<id>` is no longer
   needed unless a day-cut report is wanted. Do not restart Pi-hole, the app,
   or the Starlink DNS toggle before the stop runs — the stop statement below in
   **Teardown** applies only after this point.


## Reboot verification (no reinstall)

```sh
# VM (non-root)
docker ps --filter name=starlink-dns-pilot --format '{{.Status}}'          # healthy
docker ps --format '{{.Names}}\t{{.Ports}}' | grep household               # still bound to 10.10.10.20:8787 (or :8789 for the owner profile)
curl -s -o /dev/null -w '%{http_code}\n' --header "Host: 192.168.1.10:8787" http://10.10.10.20:8787/
# Proxmox (root)
systemctl is-active starlink-dns-relay.service household-report-relay.service household-report-owner-relay.service
```

If Docker fails to start on the VM, suspect the guard's fail-closed
`ExecStartPre`; inspect with `systemctl status docker.service`, and only remove
the drop-in via the guard's `--rollback` (never by hand while the app is published —
the guard refuses that while a TCP/8787 port is published).

## Teardown (reverse order; DNS address first, Pi-hole last)

1. Starlink app: disable the Pi-hole DNS address (household returns to default DNS).
2. `task campaign-stop STOP=YES` (if a campaign is active) or let it finish.
3. Unpublish the app: the same `docker compose … up` env with `down`.
4. VM guard: `sudo bash dns-pilot/dashboard-vm-guard.sh --rollback` (refuses while
   the app is still published — that refusal is intentional).
5. Proxmox relays: `--rollback` on `dashboard-owner-relay.sh` first (if published), then
   `dashboard-proxmox-relay.sh`, then `proxmox-forwarding.sh` (the dashboard helpers
   never touch the DNS pilot table, and vice versa; each relay rolls back independently).
6. Optionally stop Pi-hole: `docker compose -f dns-pilot/compose.yaml down`.

## Troubleshooting

| Symptom | Check first | Then |
|---|---|---|
| Household `dig @192.168.1.10` fails | `systemctl is-active starlink-dns-relay.service` on Proxmox; `wlo1` still `192.168.1.10/24` | Re-run `proxmox-forwarding.sh --install` (idempotent, owned-table aware) |
| Dashboard unreachable from household | `systemctl is-active household-report-relay.service`; VM `docker ps` bind; guard `--status` | Reinstall the relay; re-publish only if the guard is present |
| Dashboard 400 from household | Device sending wrong Host? Only `192.168.1.10:8787` is allowed | Browse exactly `http://192.168.1.10:8787/` |
| Query count not moving | 60 s flush window; device actually using `192.168.1.10` as DNS? | Check the Starlink app toggle; `dig example.com` without `@` |
| Pi-hole admin unreachable | `https://192.168.1.10:8443/admin/` from household, or `https://10.10.10.20:8443/admin/` from the VM | DNS relay covers TCP/8443; container health |
| Boot guard blocks Docker startup | `systemctl status docker.service`; guard table missing or interface name changed | Review the guard `--status`; use `--rollback` only after unpublishing |
| Owner relay refuses to install | Shared table still forwards 8789, or a Proxmox listener already owns TCP/8789 | Migrate the historical mixed rule deliberately (backup first); never edit nftables by hand |
