# Project reference

Sanitized reference material for understanding what the system can observe and how it is built. The documents are dated descriptions, not proof of current live health or authorization to operate the system.

| Document | Contents |
| --- | --- |
| [Current architecture](current-architecture.md) | Components, data flow, access profiles, deployment baseline and known gaps |
| [Source-data inventory](source-data-inventory.md) | Available evidence, collection methods and limitations |
| [Starlink destination and presence report](../investigations/STARLINK-DESTINATIONS-AND-PRESENCE-REPORT.md) | Historical router capability and campaign evidence |

For current requirements and progress, see [006 spec](../../specs/006-reliable-household-operation/spec.md), [plan](../../specs/006-reliable-household-operation/plan.md) and [tasks](../../specs/006-reliable-household-operation/tasks.md). For operational steps and approvals, use the [bring-up](../operations/household-bringup-runbook.md), [stack lifecycle](../operations/stack-lifecycle-runbook.md) and [campaign](../operations/005-campaign-runbook.md) runbooks. Task ledgers in `specs/` record dated evidence; use the newest applicable one and verify live state separately.

Do not publish raw queries, client identifiers, credentials or private provider responses in reference documents. Distinguish observed facts from inference, date live-state claims, and retain unknowns and collection gaps.
