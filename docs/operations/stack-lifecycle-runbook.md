# Stack lifecycle runbook (setup → uninstall)

Written 2026-11-02 for feature 006 T13. This is the canonical walkthrough of the
**typed operator driver** behind `task stack-*`. Every command resolves one
explicit configuration, enforces one boundary, and prints one sanitized JSON
result. Nothing here is live-executed yet: the first real run happens at gate
L1, where this document is the reviewed execution script.

Driver: `destination-report/tools/stack_cli.py` (30 offline tests in
`tests/offline/test_stack_cli.py`, including a fresh and a legacy walkthrough).

---

## Safety rules (always)

- Root/systemd/Docker actions are run **by the owner**, never by automation.
- No stack command starts or finishes a **campaign**, reads resolver source
  rows, changes firewall/DNS state, or **spends money**. Campaigns stay behind
  `task campaign-start START=YES …`; AI runs stay behind the web preview →
  confirm flow with its own budget gates (and L4 for paid calls).
- Every external effect is one argument array (`docker compose`, `docker build`,
  `docker image inspect`, `docker tag`, `systemctl`) through one runner with a
  neutralized environment: ambient `COMPOSE_*`, `HR_*`, `AI_*` and `EXA_*`
  variables never influence a driver-invoked subprocess.
- Destructive commands refuse without their exact confirmation token.
- Raw evidence, credentials and household rows never appear in driver output.

---

## Host dependencies (actual, not aspirational)

| Dependency | Why | Notes |
| --- | --- | --- |
| Docker Engine + Compose **v2.24+** | The compose merges use the `!override` tag (owner profile) | `docker compose version` must report ≥ 2.24 |
| `uv` + the project lock | Runs the driver and host tools from `destination-report/uv.lock` | `task dev-setup` creates the environment; offline `UV_OFFLINE=1` works once created |
| Python **3.13** (`>=3.13,<3.14`) | Project requirement; host tools import application modules, so a bare system `python3` is **not** sufficient | Provided by the project venv |
| `git` | Release manifests read `rev-parse`/`status` for identity and drift | Manifest build refuses a dirty tree without `--allow-dirty` |
| systemd (owner user) | Bridge service/timer are system units, rendered non-root | Rendering never installs; install is a separate explicit action |
| Docker group membership | `docker compose` calls | Privileged in practice — documented, not hidden |
| Private disk | 0700 state/input/config directories; preflight asks for ≥ 2 GiB free | Backups add their own footprint |
| Pi-hole container | Only for capture (`host_bridge.py` reads it through the bounded export) | Never touched by setup/check/status/start/stop |

No task installs packages, downloads at service start, opens a port, or
touches the Starlink router.

---

## Configuration: fresh versus legacy (never both)

**Fresh (preferred):** one operator JSON, selected per command with `CONFIG=`:

```sh
task stack-setup CONFIG=~/.config/starlink-monitoring/destination-report/operator.json
```

The file must be `0600`, not a symlink, with no unknown fields and no duplicate
keys *within any one object* (different sections may repeat key names, e.g.
`paths.config_dir` and `bridge.config_dir`). An example lives in
`operator_config.create_example_config()`.

**Legacy:** omit `--config` and the driver reads the `HR_*` environment (the
pre-006 Make variables). It supports `setup`, `check`, `start`, `status`,
`stop`, `restart` and `uninstall` — the commands that need no release
identity. `upgrade`, `rollback` and `backup` refuse on the legacy path with
"needs an explicit release in the operator config".

**Mixed paths fail:** selecting `CONFIG=` while any legacy `HR_*`/`EXA_*`/`LLM_*`
or app AI variable (`AI_PROVIDER`, `AI_PAID_MODE`, …) is present in the
environment is refused with the offending names. Resolve the conflict; the
driver never guesses which source wins.

---

## The commands

`CONFIG=` below abbreviates `CONFIG=~/.config/starlink-monitoring/destination-report/operator.json`.

### `task stack-setup CONFIG=… [--build]`

Prepares, does **not** install.

- Creates (or verifies) the private `0700` config/input/state/bridge directories.
- Writes the bridge configuration once (`campaign-bridge.json`, `0600`); an
  existing file with different contents is **refused** — source identity is
  never rebound silently.
- Renders `household-campaign-bridge.service`/`.timer` for a non-root account
  (`--user`; root is refused). Rendering enables nothing.
- Writes `stack-prepared.json` bound to a digest of the exact configuration:
  later commands refuse to run if the config changed since setup.
- `--build` is the only opt-in external effect: one `docker build` of the
  locked image. Default: `build: not-requested`.

### `task stack-check CONFIG=… [MODE=live]`

Offline by default: private directory modes, prepared-state binding, release
manifest (host-bundle digest and schema compatibility), journal state. `ok:
false` lists sanitized issues; nothing is changed.

`MODE=live` adds exactly one narrow read: `docker compose ps -a` for the
selected project. No resolver contact, no source extraction, no provider call.

### `task stack-start CONFIG=…`

Starts the **selected application pair only**, after verifying the prepared
state and (when a release is configured) that the selected image ID exists
locally. Output states `campaign: not-started`, `network: unchanged`,
`spend: disabled`. There is no variant that also starts a campaign.

### `task stack-status CONFIG=… [MODE=offline]`

Aggregated sanitized health: profile, compose project, store schema version
(read-only — status never migrates), campaign states, maintenance journal
position, prepared-state presence, collector heartbeat classification, and the
runtime container read (`MODE=offline` skips even that). `external_calls: none`.

### `task stack-stop CONFIG=… STOP=YES` / `task stack-restart CONFIG=… RESTART=YES`

Stop: bridge unit first (when rendered; an absent unit is a warning, not a
failure), then `docker compose stop`. Data is retained; DNS is untouched.
Restart is exactly stop-then-start of the same prior operation — never a new
campaign, never a network change.

### `task stack-upgrade RELEASE=… [ARCHIVE=…] UPGRADE=YES`

A reviewable maintenance transaction, all six stages journaled **before** their
work runs (so an interruption is visible and resumable, never silent):

```
stop-bridge → stop-writers → backup → migrate → recreate → check
```

- Guards run before anything stops: target ≠ current image (immutable
  `sha256:` identity — tags are not identity), target schema ≤ this
  application's schema, no in-place downgrade.
- Backup goes to `ARCHIVE` (default `state/backups/<utc>/`), must be empty,
  `0700`, and is verified (digests, artifacts, campaign deadlines).
- Recreate tags the target image, writes a private compose override, and
  recreates **both** containers in one `up -d --force-recreate`; the check stage
  requires stable running containers. A failure leaves the journal active at the
  failed stage with the stack stopped — never one old/one new instance as success.
- On success: `next` tells you to point the operator config's `release` section
  at the target manifest and re-run setup/check. **The driver never rewrites
  owner configuration.**
- Resume after interruption: same command with `--resume` (same target only).
  Reset only via `stack-journal reset --confirm reset-journal`.

### `task stack-rollback RELEASE=… [ARCHIVE=…] ROLLBACK=YES`

Same transaction back to a **preserved** release manifest (keep the preceding
manifest — that is the rollback artifact). A rollback to an older *schema* is
refused in place and points at `stack-restore` into a new directory; production
promotion from a restore is a separate, explicitly documented owner operation.

### `task stack-backup ARCHIVE=… BACKUP=YES`

A standalone quiesce-and-backup transaction for the current release: stops
bridge and writers under the maintenance lock, takes the verified consistent
backup (SQLite backup API + artifacts + manifest), recreates the same release
and checks it. `ARCHIVE` must be a new empty `0700` directory. Brief downtime
applies — that is why it is confirmed.

### `task stack-restore ARCHIVE=… DEST=… RESTORE=YES`

Restores a verified archive **only** into an empty private `0700` directory —
isolation, for inspection or as the first step of a cross-schema recovery.
It never overwrites running state; output says so explicitly.

### `task stack-uninstall CONFIG=… [UNINSTALL=YES]`

Without `UNINSTALL=YES` it is a **preview**: what would be removed (the compose
project, the rendered bridge units) and what is retained (state, input,
configuration, images, backups, DNS). With the confirmation it disables the
timer and removes only owned publication. DNS and the resolver are never
touched — DNS shutdown/failover stays an owner-managed action.

### `task stack-journal CONFIG=…`

Prints journal status (`active`, completed stages, next stage). Reset requires
the driver's `--confirm reset-journal` and is reserved for an owner decision
after reviewing an interrupted transaction.

---

## Confirmation gates

| Command | Gate | Token passed to the driver |
| --- | --- | --- |
| `stack-stop` | `STOP=YES` | `--confirm stop` |
| `stack-restart` | `RESTART=YES` | `--confirm restart` |
| `stack-upgrade` | `UPGRADE=YES` | `--confirm upgrade` |
| `stack-rollback` | `ROLLBACK=YES` | `--confirm rollback` |
| `stack-backup` | `BACKUP=YES` | `--confirm backup` |
| `stack-restore` | `RESTORE=YES` | `--confirm restore` |
| `stack-uninstall` | `UNINSTALL=YES` (else preview) | `--confirm uninstall` |
| journal reset | driver-level | `--confirm reset-journal` |

`stack-setup`, `stack-check`, `stack-status`, `stack-start` and `stack-journal`
are non-destructive and need no gate; `stack-start` still verifies the prepared
state and selected release first.

---

## Fresh walkthrough (synthetic, offline-verified)

```sh
task stack-setup   CONFIG=…            # dirs 0700, units rendered, prepared written; no runner calls
task stack-check   CONFIG=…            # ok:true — bundle verified, journal inactive
task stack-status  CONFIG=… MODE=offline
task stack-start   CONFIG=…            # pair only: campaign not started, network unchanged, spend disabled
task stack-stop    CONFIG=… STOP=YES   # bridge then applications; data retained
task stack-restart CONFIG=… RESTART=YES
task stack-uninstall CONFIG=…          # preview only; then UNINSTALL=YES to remove owned publication
task stack-journal CONFIG=…            # status only
```

Upgrade/rollback/backup additionally need a release-bearing config and a target
manifest; the transaction stages are exercised in the offline suite with a fake
runner (ordered argv, journal completion, verified archive, resume after an
interrupted stage, guard refusals before any effect).

## Legacy walkthrough (pre-006 environment)

```sh
export HR_DATABASE=~/.local/share/household-report/state/app.sqlite3
export HR_INPUT_DIR=~/.local/share/household-report/input
export HR_CONFIG_DIR=~/.config/starlink-monitoring/destination-report
STACK="uv run --project destination-report python destination-report/tools/stack_cli.py"
$STACK setup
$STACK check
$STACK start
$STACK status --offline
$STACK stop --confirm stop
```

Same boundaries; `release: legacy-unmanaged` is reported honestly rather than
pretending an identity that does not exist. Adding `--config` while these
variables are exported is refused (mixed path).

---

## Where the evidence lives

- Offline walkthrough and boundary tests: `destination-report/tests/offline/test_stack_cli.py`
- Driver: `destination-report/tools/stack_cli.py`
- Recovery contracts: `household_report/maintenance.py` (journal, backup,
  isolated restore, upgrade guards) — `tests/offline/test_maintenance.py`
- Release identity: `household_report/release.py` — `tests/offline/test_release.py`
- Live behavior (real Docker/systemd) is **gate L1**, recorded in the 006
  acceptance packet — not claimed here.
