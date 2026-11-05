# Future direction and historical ideas

The project's direction is bounded household DNS observation and understandable gaming-related reports, with explicit privacy, coverage and interpretation limits. The approved current implementation scope is [feature 006](../../specs/006-reliable-household-operation/spec.md), with progress and live gates in its [task ledger](../../specs/006-reliable-household-operation/tasks.md).

The [MVP planning document](../project-scope/mvp-spec-v1.md) explains the motivation, evidence and longer-term questions. It predates the campaign and reporting implementation: its supersession note points to the current architecture, and older proposed behavior should not be treated as the running system or as authorization for new work.

The [Homebrew CLI delivery decision](homebrew-cli-delivery-decision.md) records the 2026-11-04 choice of Option A: keep Python, make the existing tools a `household` console script, and publish a prebuilt PEX bundle through the existing [`homebrew-tap`](https://github.com/nawodyaishan/homebrew-tap). No Go migration. It also records the one structural caveat — `household stack` needs a `--stack-dir` checkout — and the licence and release prerequisites.

The original discussion that produced these ideas is retained privately and is not published here; this index records only the sanitized decisions that came out of it. Clinical value, diagnosis, complete gameplay detection and continuous monitoring are not established outcomes of the current feature.
