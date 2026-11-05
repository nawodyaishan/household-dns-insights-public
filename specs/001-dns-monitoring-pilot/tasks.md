# Monitoring-only DNS pilot — tasks r2

Inputs: spec r2 and plan r2. Single approval record: `spec.md#combined-approval`. Assignments/tools are in plan.md; no task exceptions.

## Ordered tasks

| ID | Task and expected result | Dependencies | State |
|---|---|---|---|
| T1 | Obtain root-authorized firewall evidence; preserve services/rules and settle a fail-closed pilot-only ACL/startup design. No broad privilege bypass. | combined approval | complete: evidence supplied 17:31 UTC; user-run installer at 18:02 UTC set the Docker `ExecStartPre` guard (`ignore_errors=no`) and `--check` passed; reboot reapplication untested |
| T2 | Write configuration checks first, then Compose/secret setup; validate exact upstreams, monitoring-only options, pin/digest and persistence. Independent of root firewall installation. | combined approval | complete: pinned Compose, owner-only secret, nine static checks pass |
| T3 | Bootstrap loopback-only, disable default lists, verify DNS/admin/config/database, controlled restart and isolated backup restore. | T2 | complete: four runtime checks pass, restart and full backup/isolated DB restore verified |
| T4 | User installs reviewed scoped persistent ACLs; verify them before publishing candidate IPv4 DNS/admin bindings. Prove allowed/denied paths without affecting other services. | T1 + T3 + user root command | root install/check supplied; private ports published, VM-local allowed and default-bridge denied tests pass; household path later proven via relay; reboot reapplication still untested |
| T5 | User executes explicit Mac UDP/TCP/admin tests; correlate query evidence. Report exact fault and smallest proposed fix if necessary, never change topology. | T4 | complete: failed against `10.10.10.20`, diagnosed as missing household route; user-approved scoped Proxmox relay installed 18:23 UTC; retest at 18:24:19 UTC passed UDP/TCP/AAAA/HTTPS with relay counters and three stored rows for client `192.168.1.20` |
| T6 | Finalize verified addresses/app fields, backup/restore, cutover/rollback and availability tradeoff. Stop before user app changes. | T5 | complete: user applied Primary `192.168.1.10`, Backup and IPv6 empty, filtering off at 18:27 UTC; backup/restore and rollback documented |
| T7 | After user reports app cutover, verify ordinary household queries, apparent source identity, IPv6/alternate DNS gaps; report sanitized results. | T6 + explicit cutover confirmation | complete: cutover confirmed 18:27 UTC; router-forwarded queries logged, attribution is household-level `192.168.1.1`, Tailscale devices bypass, VM-side router tests invalid due to masquerade loop |
| T8 | Observe for 24–48 hours using resumable private sampling; review normal queries, rate limits, DB growth, monitoring gaps and user-reported known service-use examples. Report actual duration/uncertainty. | T7 | in progress: 48 aggregate samples over 11.2 h at the 05:50 UTC review, 0 error samples, longest inter-sample gap 901 s, 0 observed rate-limit warnings; corrected window ends 2026-10-24 18:33:48 UTC; sampler is a detached process with no startup unit |

## Batches

### B1 — Monitoring-only resolver pilot and observation (T1–T8)

Outcome: safe restricted service, working local and Mac DNS/admin, durable query history, tested restart/backup restore, user-controlled app cutover and a measured 24–48-hour observation report. Verification: static config tests, effective config, UDP/TCP, authentication, SQLite integrity/known records, ACL allowed/denied paths and startup-order checks; correlated Mac queries; post-cutover ordinary query/source/IPv6 checks; time-window evidence, rate-limit warnings and growth/gaps. Default recovery remains unfiltered. At completion set `awaiting human review` and stop; no follow-on application work.

State: **observation in progress; pilot verified**. Approval/execution evidence is recorded in spec.md. User installed protection and the scoped Proxmox relay; private-address ports published and locally validated; Mac UDP/TCP/HTTPS tests passed at 18:24:19 UTC. User applied the app cutover at 18:27 UTC with no rollback. At the 2026-10-23 05:50 UTC review the sampler held 48 valid samples over 11.2 h with no gaps beyond the 900 s cadence and no observed rate-limit warnings. B1 completes when the 48-hour window closes (~2026-10-24 18:33:48 UTC) and the coverage report is written. Actual reboot/Docker-restart reapplication remains untested.

### Operational intervention points (not separate approval batches)

- Root: done 18:02 UTC — the user ran the reviewed guard installer; `--check` passed. Apply the same reviewed pattern for any later rule change; never broaden access to make a test pass.
- Mac: user runs explicit tests without changing Mac DNS and supplies results. Never declare readiness from VM-only tests.
- App: user performs the final Starlink content-filter/custom-DNS change and confirms completion. That confirmation is an operational prerequisite, not another routine implementation authorization.
- Material change: any newly proposed topology, routing or broader access-control change needs explicit review and authorization before execution. Do not silently broaden trusted networks to make tests pass.

Once r2 is approved and implementation authorized, the agreed pilot and routine verification use that authorization throughout T1–T8. Await missing operational inputs, not redundant phase approval.

## Continuation

2026-10-22: User authorized “proceed”; approval recorded in spec.md, AGENTS scope updated. Created `dns-pilot/` pinned loopback Compose, inactive LAN override, tests, scoped root installer/guard and operations instructions; updated Makefile/README. Five static and four local runtime tests pass. Tests initially failed before missing configuration/guard files were added. Effective boolean FTL quiet getters return 1 for false: tests explicitly assert that behavior and exact values. Default list disabled through the versioned API (`?type=block` required), confirmed after restart. Database import/7-day retention/60-second writes confirmed. Initial private backup `PRIVATE_DNS_BACKUPS/20261022T175608Z/` restored into distinct unpublished volume; both DB integrity checks passed and six timestamped public test queries survived. The FTL SQLite CLI did not open a URI-style path; plain isolated-copy paths passed, without touching the live volume. TLS fingerprint and sources are in `dns-pilot/OPERATIONS.md`.

Technical assessment: **Pilot operational and under observation.** Cutover verified at 18:27 UTC: household queries reach Pi-hole through the router, no rate-limit warnings, upstream latency 42-46 ms. Attribution is household-level (router `192.168.1.1`); device addresses appear only for clients that query `192.168.1.10` directly. Tailscale MagicDNS bypasses router DNS on the MacBook. Still unverified: IPv6 behaviour, Proxmox/VM reboot reapplication, sustained 24-48-hour coverage. Next action: let the aggregate sampler run, then review gaps and rate limits before proposing the dashboard stage. Current working changes remain uncommitted/unpushed.

2026-10-22 18:23 UTC: user installed the scoped Proxmox relay (`--print`/`--check` clean, two rules, unit enabled+active, backup `/var/lib/starlink-dns-relay/pre-install.XXXXXXXX`). Mac retest at 18:24:19 UTC passed and Pi-hole recorded client `192.168.1.20`, proving source preservation across both DNAT hops. The household path depends on Starlink Wi-Fi, the relay unit and the VM; loss of any one removes DNS regardless of Tailscale reachability.
