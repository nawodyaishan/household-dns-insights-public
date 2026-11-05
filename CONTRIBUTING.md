# Contributing

Thanks for helping make household DNS reporting more understandable, reliable and privacy-conscious. Documentation, accessibility improvements, synthetic test cases, bug reports and focused code improvements are all useful. You do not need a Starlink router, Pi-hole or real household data for the offline application tests.

This is the **public** repository: it holds the code, the design documents and the engineering record with household-specific values removed. The live household deployment, its raw evidence and its session records live in a private repository and are out of scope here — do not ask for, reconstruct or paste them. Changes are reviewed and exercised against synthetic fixtures only.

## Before contributing

This repository does not currently contain a license file. Please ask the maintainer about contribution and reuse terms; do not assume an open-source license has been granted.

Read the [project overview](README.md) and the [current feature spec](specs/006-reliable-household-operation/spec.md), [plan](specs/006-reliable-household-operation/plan.md) and [tasks](specs/006-reliable-household-operation/tasks.md). For substantial changes, discuss the outcome and scope before investing in an implementation. Approved feature documents do not authorize deployment, network changes or paid services.

## Development setup

Prerequisites: Git, [Task](https://taskfile.dev/) (go-task ≥ 3), Python **3.13** and [uv](https://docs.astral.sh/uv/). The application uses `destination-report/pyproject.toml` and `destination-report/uv.lock`; do not introduce a parallel dependency environment. Docker is optional for explicitly requested synthetic container checks and is not required for the offline suite.

Every command lives in `Taskfile.yml`. Task names, variable names and defaults match the former Makefile one-for-one, so a recorded `make <name>` still works as `task <name>`. Completed task ledgers keep the tool that was actually used at the time; do not rewrite them.

From the repository root:

```sh
task help-contributors
task dev-setup
task quality
task check
```

`task dev-setup` may download the locked dependencies and configures the local Git hook; it refuses to overwrite a different existing hook path. Subsequent quality checks use the prepared environment offline. `task help` lists all tasks, including operational commands with side effects.

## Verification

- `task quality`: lock consistency, format check, lint and offline application tests with synthetic fixtures and fake external adapters.
- `task test-offline`, `task format-check`, `task lint` or `task lock-check`: focused portions of the same gate.
- `task check`: repository Python syntax, whitespace and private-file ignore checks.
- `task runtime-check`: optional Docker-based synthetic container tests; not needed for ordinary offline changes.

Add focused tests for behavior changes and describe what you ran, what passed and what remains unverified in your change. `task format` and `task lint-fix` intentionally modify files; inspect their changes. The pre-push hook runs the offline quality gate when configured.

## Privacy and safety

- Use invented domains, synthetic timestamps and fixtures. Never include raw DNS logs, household identifiers, credentials, private reports or backups in commits, issues or screenshots.
- Treat DNS lookups as observations, not proof of a connection, gameplay, identity or duration. Keep missing coverage and uncertainty visible.
- Do not run live source reads, deploy services, change firewall/DNS/routing or call paid providers without the owner's separate authorization. Commands in the Taskfile are not permission to run them.
- Do not run `task campaign-benchmark` against an existing household image: the pending T14 rehearsal must isolate its release identities first.
- Do not submit real vulnerability details or household evidence in a public issue. Contact the maintainer privately first.

## Proposing a change

1. Explain the problem, intended behavior and any relevant issue or feature requirement; for bugs include a sanitized reproduction.
2. Keep changes focused and add or update tests and documentation as appropriate.
3. Run the applicable checks above and report omissions honestly.
4. Open a pull request describing the change, evidence, risks and any operational effects. Never include secrets or household data.

For current implementation and live acceptance status, consult the [006 task ledger](specs/006-reliable-household-operation/tasks.md) and the [R01–R18 acceptance packet](specs/006-reliable-household-operation/b7-acceptance-packet.md), not just historical test counts.
