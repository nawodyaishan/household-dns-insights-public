# 005 campaign operations runbook

Scope: the bounded household campaign (005 T14–T19) on this Ubuntu VM. This
runbook is **offline delivery documentation**. It does not assert that the campaign
has run. Operational acceptance requires the separately authorized T16 checks and a
T17 campaign to its real deadline.

Nothing here changes household routing, DNS, firewall, DHCP or Starlink topology.
The resolver keeps its independent retention; do not alter it.

## Evidence levels

| Level | What it proves | Where it comes from |
|---|---|---|
| Offline | Policy, storage, reports, routes, retirement and packaging behave in synthetic tests | `task quality`, `task runtime-check`, `task campaign-benchmark` |
| Installed | The HTTP/IP LAN profile, bridge timer and a read-only source really work here | T16, owner-authorized |
| Observed | One real 3–5-day campaign completed and produced a final report | T17, owner-started |

Do not describe synthetic evidence as household operation.

## Private paths and defaults

| Variable | Default | Purpose |
|---|---|---|
| `HR_CAMPAIGN_CONFIG_DIR` | `~/.config/starlink-monitoring/campaign` | Private 0700 host bridge config; not mounted into the shared web container |
| `HR_INPUT_DIR` | `~/.local/share/household-report/input` | Private capture artifacts and `gaming-namespaces.json` |
| `HR_STATE_DIR` | `~/.local/share/household-report/state` | `app.sqlite3` and rendered units |
| `HR_BRIDGE_CONFIG` | `$HR_CONFIG_DIR/campaign-bridge.json` | Fixed-contract bridge configuration (0600) |
| `CAMPAIGN_DB` | `$HR_STATE_DIR/app.sqlite3` | Campaign and report store |
| `CAMPAIGN_NAMESPACE` | `$HR_INPUT_DIR/gaming-namespaces.json` | Owner-reviewed gaming namespaces |
| `HR_LAN_BIND` | `10.10.10.20` | The one VM address bound by Docker; not household-routable |
| `HR_LAN_RELAY_IP` | empty | Opt-in Proxmox household browser IP `192.168.1.10` (r4) |
| `HR_PORT` | `8787` | The one published port |
| `HR_LAN_PUBLIC_URL` | `http://<bind>:<port>` | The one approved HTTP origin; no domain or certificate |
| `HR_LAN_ALLOWED_HOSTS` | `<bind>:<port>` | Must equal the origin's host:port |

The LAN override (`compose.lan.yaml`) uses `!override` for ports and volumes. It must
publish exactly one explicit private VM address and **not** mount credentials or TLS
into the shared browser service. Never replace those with append-style Compose syntax.
The original loopback profile retains its password and TLS configuration.

### R4 relayed household browser profile (offline tooling; not installed)

The original `http://10.10.10.20:8787` is VM-internal and cannot be used from
household `192.168.1.x` devices. The reviewed alternative is **browser origin
`http://192.168.1.10:8787`**, forwarded on Proxmox to the **unchanged VM Docker
bind `10.10.10.20:8787`**. For this profile pass `HR_LAN_RELAY_IP=192.168.1.10`
to each `task campaign-preflight` or `task campaign-start` invocation; the Taskfile
derives the one public URL and allowed Host. Preflight accepts only this exact
pair and checks the app's isolated IPv4 bridge `br-hr005`. Never point browsers at
the VM address and assume the browser Host/Origin will match the relayed profile.

Two **uninstalled, separately owned** root helpers are prepared:
`dns-pilot/dashboard-proxmox-relay.sh` (one Wi-Fi TCP/8787 DNAT rule, no changes to
the DNS relay) and `dns-pilot/dashboard-vm-guard.sh` (drop other ingress to the
published app port and other forwarding into `br-hr005`). Both support `--print`,
`--check`, `--install`, `--status`, `--rollback`; only `--print` is non-root. Review
their full policies, private backups and root side effects before any owner-run
installation; `--check` requires root capabilities but does not apply. **No helper
has been run with root, no firewall or network change has been applied.** The VM
helper adds a Docker `ExecStartPre`: if its guard fails during a later Docker
startup, Docker can fail to start (including Pi-hole and unrelated containers).
This fail-closed operational risk needs explicit review before root installation.

Order for a separately authorized T16 continuation: confirm source generation,
check the two root helpers and Docker bridge-name availability, owner installs the
VM guard before publishing the app, owner installs the Proxmox relay, then verify
live preflight, installed bridge and actual reachability from a household device.
Confirm denied paths from nonhousehold/other VM/VPN sources and that DNS 53/8443
still works. DNAT and a VM host bind are not proof of ACL safety. On a failed
test, stop app publication first and roll back **only** the dashboard relay/guard;
never roll back the independent DNS pilot. No router changes or Pi-hole DNS
re-enablement is part of installing the dashboard. A real household campaign
requires the owner to turn Pi-hole DNS back on before separately authorizing T17.

**Shared-control warning:** Any device that can route to this IP/port can read the
existing web views (including raw household domains/client data in diagnostics) and
perform existing browser actions (including campaign start/extend/early finish and
inventory edits). HTTP does not encrypt traffic or authenticate the server. LAN
membership is not identity: guests, compromised devices and other reachable networks
may get the same access. No provider calls are enabled in the campaign profile. This
configuration is not appropriate for participant/clinical use without a new review.
Host-only installation, backup and retirement are not browser actions.

## Preconditions (T16 configuration, owner action)

Prepare these by hand before `campaign-install`:

1. **Campaign config directory** — `0700`, containing the private bridge contract only.
   Do not place web credentials or TLS files here for the shared-control profile.
2. **Reviewed namespace** — `$CAMPAIGN_NAMESPACE`, private and reviewed for suffix
   scope. A valid-empty list needs `ACK_EMPTY=YES` on preflight and
   `--ack-empty` on the campaign start.
3. **Bridge configuration** — 0600 `$HR_BRIDGE_CONFIG` with the fixed keys
   (`python`, `docker`, `compose`, `input_dir`, `config_dir`, `state_dir`,
   `container`, `database`, `generation`, `identity`). `config_dir` must equal
   `HR_CAMPAIGN_CONFIG_DIR`; `input_dir`/`state_dir` must equal the approved private
   paths; `database` must stay under `/etc/pihole/` and end in `.db`. Assign a new
   `generation` when resolver identity/ID continuity changes; do not relabel old
   rows.
4. **Docker and disk** — the owner account can run Docker and Compose; at least
   2 GiB is free on each private path.

## Deployment checklist

Run in this order. Every step is explicit; no offline gate installs or publishes.

```sh
# 1. Offline configuration only: private paths, HTTP/IP origin, Compose merge,
#    bridge contract, reviewed namespace, disk headroom, AI-off profile.
task campaign-preflight

# 2. Read-only source readiness: container running, FTL query columns, query
#    counts/oldest/newest, database.maxDBdays, registered generation, no active campaign.
task campaign-preflight MODE=live

# 3. Review the JSON. It prints counts, settings and check names only.
#    If any check fails, fix configuration; do not bypass it.

# 4. Build the image and install the bridge timer (sudo will prompt).
task campaign-install INSTALL=YES

# 5. Confirm the bridge is scheduled. It does no source read while no campaign is active.
task campaign-bridge-status

# 6. Present the concrete bind, reachable subnets, raw-data/HTTP risks and rendered units to
#    the owner. Start only after explicit campaign-start authorization, then:
task campaign-start START=YES DAYS=3 RETAIN_DAYS=7

# 7. Check progress without domains or clients.
task campaign-status
```

`campaign-start` runs the live preflight again, starts the LAN profile and starts the
one active campaign. It does not change router, DNS relay or Proxmox routing.

## During the campaign

- The supervised host bridge runs every 60 seconds. Each tick claims at most ten
  one-hour settled windows and is bounded to ten minutes. An inactive or completed
  campaign produces no source reads.
- Failed or missing source windows stay visible as gaps; they are never advanced
  past. A source-ID reset that cannot be inferred becomes an operator uncertainty.
- `task campaign-status` shows sanitized state. Do not print raw rows, domains,
  clients or credentials into chat or tickets.
- Anonymous `/household` availability expires from the **current campaign end plus
  its selected retention days**, not from frozen metadata.

Extend only while active, at most to start + 120 hours:

```sh
uv run --project destination-report python destination-report/tools/campaign_cli.py \
  --db "$CAMPAIGN_DB" extend --hours 12
```

## Stop, reports and finalization

Early finish clips the recorded end and opens the finalization allowance:

```sh
task campaign-stop STOP=YES                 # finish + finalize
task campaign-status
```

A final report can be requested locally; repeated equivalent requests reuse the
frozen result:

```sh
task campaign-report CAMPAIGN=<campaign-id>
task campaign-report CAMPAIGN=<campaign-id> DAY=YYYY-MM-DD
```

Private exports (0600, never overwritten) use the existing tool:

```sh
python destination-report/tools/export_campaign_report.py \
  --db "$CAMPAIGN_DB" --report <report-id> --format json --output /private/report.json
```

Report generation loads the bounded campaign input in memory. Campaign tiers are
capped at 120 hours; the T15 benchmark below records representative resources.

## Backup and isolated restore

Backups are private external copies. Server expiry cannot revoke them.

```sh
install -d -m 0700 /private/backups/<timestamp>     # must be empty
task campaign-backup ARCHIVE=/private/backups/<timestamp>
uv run --project destination-report python destination-report/tools/campaign_retirement.py \
  --db "$CAMPAIGN_DB" --input-dir "$HR_INPUT_DIR" verify --archive /private/backups/<timestamp>
install -d -m 0700 /private/restore-check          # must be empty
uv run --project destination-report python destination-report/tools/campaign_retirement.py \
  --db "$CAMPAIGN_DB" --input-dir "$HR_INPUT_DIR" restore \
  --archive /private/backups/<timestamp> --destination /private/restore-check
```

- Backup uses SQLite's backup API plus SHA-256 manifests and refuses while any
  campaign is active or finalizing. A backup of a live multi-campaign store and an
  interrupted filesystem cleanup remain unexercised.
- Restore refuses a populated destination and never touches the running database.
- If filesystem cleanup is interrupted after retirement, private orphan artifacts
  may remain for operator inspection; no automatic recursive delete occurs.

## Retirement

Retirement is explicit and irreversible for campaign rows. Shared snapshots,
provider/analysis ledger and unrelated input files are kept.

```sh
# Preview: digests and counts only.
task campaign-retire CAMPAIGN=<campaign-id>

# After the backup (or an explicit decline), execute:
task campaign-retire CAMPAIGN=<campaign-id> DIGEST=<preview-sha256> \
  BACKUP_CHOICE=backed_up CONFIRM=<campaign-id>
# or BACKUP_CHOICE=declined with the same explicit confirmation.
```

## Recovery scenarios

| Situation | Action | Check |
|---|---|---|
| VM or container restarted | Start the LAN profile and bridge again; the campaign deadline is unchanged | `task campaign-status`, `task campaign-bridge-status` |
| Bridge tick crashed | The host lock and leases expire; the next tick resumes pending imports | `campaign-status`, then inspect `pending-artifacts` through the CLI |
| Report worker restarted | The job is reclaimed after its lease; a frozen report is replayed, not regenerated | `task campaign-report` or `report-status` shows the same report ID |
| Source reset suspected | Register a new generation; do not relabel captured rows | `campaign-status` shows the new generation; gaps stay explicit |
| Store damaged | Restore a verified backup into an isolated directory first | `verify` plus `quick_check` during restore |
| Browser cannot reach HTTP/IP origin | Check the intended device's route to the approved VM IP; correct only after separate network authorization | preflight `public origin`/`Compose merge` and T16 second-device browser check |

Do not infer device absence or campaign failure from one missing poll, API error or
stale lease. Record it as a monitoring gap.

## Rollback

- **Before installation:** nothing is running; revert the working tree or branch.
- **Stop without deleting:** `task campaign-uninstall UNINSTALL=YES` stops the LAN
  service and removes only the bridge units. Private configuration, state and
  evidence remain.
- **Code rollback:** `git revert <commit>` on a branch. Schema migrations v3–v6 are
  additive, but do not silently downgrade a database that has already migrated.
  Restore a tested pre-migration backup into an isolated installation instead.
- **Household impact:** none of these commands change router/DNS/topology. The Pi-hole
  resolver and its retention stay as they are.

## Resource measurement method (T15)

`task campaign-benchmark` builds the current image and runs two separate one-off
containers with synthetic data only:

1. `prepare` — five-day campaign, 120 hourly windows, 120 synthetic rows per hour
   (14,400 rows), one to-date report, JSON/CSV export, finalization.
2. `verify` — a new process that re-checks the frozen report digest, generates one
   completed-day report, then backs up, verifies and restores into an isolated
   empty directory.

Measurements come from the benchmark process itself (`ru_maxrss`, user+system CPU,
wall-clock stages, SQLite page count, artifact/export byte totals) and are printed
as one sanitized JSON line. Record the actual run in
[`specs/005-continuous-household-reporting/tasks.md`](../../specs/005-continuous-household-reporting/tasks.md).

This is packaged synthetic evidence, not household load. A real campaign's row
count depends on household query volume and cannot be inferred from it.

## Known unverified items

- Real LAN reachability from a second device, DNS-relay/Proxmox routing and the actual reachable audience.
- Installed systemd unit behavior and controlled service/VM restart on this host.
- Real source generation continuity, FTL retention lag and reset detection.
- Multi-worker rate limiting (the limiter is per process).
- Backup of a live multi-campaign store and interrupted cleanup.
