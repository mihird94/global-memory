# CCMP Behavioral v2 — Construct Validity Remediation

Date: 2026-10-12 (America/Los_Angeles)
Status: scientific acceptance incomplete; bounded corrective handoff
Target: `/Users/mihirdeshpande/projects/learning/agent_memory/_research/ccmp_behavioral`
Parent contract: `docs/CCMP_BEHAVIORAL_V2_MEMORY_SENSITIVITY_SPEC.md`

## Decision

Retain the 96-run result as an exploratory observation on the existing tasks/backend: equal recorded success across four context arms, with extra token consumption. Do not accept the stronger claims of intrinsic reasoning limits, validated two-axis manipulation, broad misleading-memory robustness, unavoidable memory overhead, or a powered sample-size requirement.

Do not execute the recommended memory-only hidden-schema experiment. It gives the memory arm information unavailable to the control and violates the parent contract's equal access to requirements and authoritative documentation. Source-specific tasks must offer legitimate source access identically to every arm.

## Evidence reviewed

Run: `evidence/runs/ccmp_behavioral_sensitivity/20261012_155341_202927Z-6024f9ca29f6`.
Supplied audit: `evidence/audits/ccmp_behavioral_audit/20261012_161039_754149Z-f691b0e452d1`.

Verified source/output observations:

1. `runner/staged_runner.py` selects the original development tasks for sensitivity. `tasks/task_definitions.py` appends difficulty/redundancy annotations without implementing new tasks or a controlled information-access manipulation. For example, `task_tz_01` already specifies aware parsing, UTC conversion, Z formatting, and type rejection, and its background explicitly names `timezone.utc` and `astimezone`. Labeling it source-specific is unsupported.
2. Representative `task_tz_01` outputs from all four arms use `astimezone(timezone.utc)` correctly but serialize with `isoformat()`, yielding `+00:00` rather than the required `Z`. The observed failure is output-format compliance, not evidence of a fundamental misconception about offset conversion. Inspect all repetitions before final attribution.
3. `IncorrectContextStressPolicy` takes the first pool entry in a set of categories; the inspected timezone stress record selects `mem_tz_01_cond`, a true compatibility caveat about older Python versions. This is not the claimed stale/false/injection exposure. Labels alone cannot establish a harmful intervention.
4. `PlaceboContextPolicy` selects an irrelevant item without token-length matching. Transfer-versus-placebo comparisons therefore conflate content with unequal context length.
5. `BehavioralAuditor` reconstructs against the current `TaskRegistry`, parser, sandbox, and checker imports rather than a frozen historical snapshot. This is useful current-code replay, but does not by itself verify historical execution equivalence. The hidden-isolation gate still scans outputs/traces/patches, not exact input contents. Prompt hashes are shape-checked rather than reconstructed from recorded bytes.
6. Sensitivity paired-comparison auditing checks mean differences but does not fully recompute wins/losses/ties, CIs, or axis summaries. Inventory checks balance whichever arms remain instead of enforcing the frozen expected schedule. An entire deleted arm can evade that particular check.
7. Power code fixes z quantiles regardless of supplied alpha/power, assumes discordance, caps requested effect to headroom, and uses small cluster-size assumptions without deriving them from the actual family/repetition structure. The protocol's 12.5-point sensitivity assertion exceeds its stated 8.33-point observed baseline headroom. Neither constitutes empirical power proof.
8. The runner limits execution count but does not enforce the protocol's aggregate wall/token ceilings. Fine-grained worker timing exists but is not retained in the main execution record; its wall time excludes independent hidden checking.

## Phase A — Correct interpretation without model calls

Append a dated correction to the sensitivity report; preserve original evidence and reports through versioned files. Map each claim to retained, qualified, withdrawn, or NOT_EVALUATED with source references.

- Retain observed equal success and per-arm measured usage, subject to artifact reverification.
- Replace intrinsic-reasoning attribution with the specific observed formatting failure and uncertainty about its cause.
- Describe the two-axis table as post hoc task strata unless actual prospective manipulation can be demonstrated. Do not call annotations a causal factorial experiment.
- Qualify robustness to the exact selected memory contents. Do not generalize from a benign conditional caveat to poisoned-memory resistance.
- Replace unavoidable/general cost assertions with measured arm/task/backend-specific differences. Recompute percentages separately: generation versus end-to-end time, prompt versus total tokens. No observed success gain does not prove permanent uselessness.
- State that zero discordant pairs leaves little information about possible population effects. Keep degenerate empirical bootstrap outputs labeled; do not interpret `[0,0]` as certainty or equivalence.
- Treat existing power numbers as assumption-based approximations pending validated planning. Do not claim four clusters make inference mathematically impossible in every design; they make this pilot inadequate for the asserted guarantees.

Analyze all timezone outputs with independent component checks: type rejection, naive rejection, correct UTC instant, and exact serialization. A one-line output-format repair may be evaluated offline as a diagnostic intervention, explicitly labeled human-assisted and excluded from model success counts. Preserve original patches/outcomes.

Audit selected stress/placebo/transfer contents for every task. Emit selected IDs, exact contents, rationale, applicability, expected incorrect consequence, actual model exposure, and independent verification. An incorrect label does not count as stress exposure. Do not retrospectively reassign the intervention or rerun under the old run ID.

## Phase B — Close measurement and budget contracts

Freeze complete initial task/memory/protocol/checker/parser snapshots with exact prompt and provider request/response bytes. Reconstruct historical runs using those versions, not mutable current modules. If unavailable, label historical version equivalence NOT_VERIFIABLE rather than backfilling metadata.

The independent reference verifier must enforce the full expected schedule, raw pair identities, selected-content-to-prompt correspondence, complete checker discovery, exact patch bytes, phase timings, usage provenance, all paired statistics, axis summaries, and power inputs. Validate manifest-listed missing files and source/config hashes. Distinguish current-code replay from frozen historical replay and disclose shared implementation dependencies.

Add rehashed semantic tests for: entire arm deletion with adjusted summaries; forged axis labels; unchanged prompt hash with wrong selected context; false stress classification; altered paired CI/win count with unchanged mean; wrong phase timing; missing checker file; changed source snapshot. Gate failures must identify the specific violated contract. Unmodified evidence is the positive control.

Make the runner execute a frozen protocol rather than separately hardcoded parameters. Enforce actual aggregate model-attempt, wall-time, and token ceilings including failures/retries. Retain partial schedules with NOT_EVALUATED comparisons when a ceiling interrupts a block. No automatic budget replenishment. Preserve smoke attempts and their budget accounting rather than deleting their evidence.

Power planning must use supplied alpha/power or reject unsupported values, validate inputs, distinguish hypothetical assumptions from measured discordance, represent actual hierarchy, and report sensitivity to assumed within-family dependence. Do not silently change the target effect to a feasible alternative. Reject infeasible alternatives or report them explicitly. Validate approximations against independent simulation/reference cases before using a power statement.

## Phase C — Prepare a scientifically identifiable next study

Create fresh task/source families with operational definitions of difficulty and source specificity. Every arm receives complete requirements and identical access to authoritative source material. Memory summarizes reusable evidence from a different task; it must not be the only place a hidden acceptance rule appears.

For a one-completion worker, embed identical full reference documentation in every arm and vary a verified procedural summary. Alternatively implement bounded read/search tools identically across arms and measure saved discovery steps. Label the worker capability actually executed. Keep these designs separate rather than conflating summary benefit with privileged information.

Use independently authored multi-file/stateful tasks for difficulty, and source-specific conventions that cannot be inferred from generic library knowledge but are available in the common documentation. Check reference solutions and plausible incorrect solutions before freezing tasks. Exclude no task based on observed memory benefit.

Length-match placebo context within a predeclared token tolerance; report deviations. Construct genuinely incorrect stress content with explicit task-contract contradictions, separating false guidance, stale guidance, quoted harmless text, and injection. Verify delivery with exact prompts. Define success, neutrality/equivalence, and harm thresholds precisely: failure to show benefit is not proof of neutrality, and a `<=0` contrast includes a tie rather than requiring vulnerability.

Before any new real execution, deliver the frozen corpus/protocol, reference-checker tests, schedule, power limitations, budget accounting, and reproducibility commands. **This corrective handoff authorizes offline repair and study preparation only; no additional model runs or confirmatory execution.** The earlier 96-run allowance has been consumed. Present the concrete new design and budget for a subsequent execution decision.

## Deliverables and stop

Return `CLAIM_CORRECTIONS`, `TIMEZONE_FAILURE_COMPONENTS`, `ACTUAL_STRESS_EXPOSURES`, `FROZEN_VERSUS_CURRENT_REPLAY`, `AUDIT_REGRESSIONS`, `BUDGET_ENFORCEMENT`, `POWER_VALIDATION`, `NEW_TASK_ACCESS_PARITY`, `PROPOSED_EXECUTION_BUDGET`, and `KNOWN_LIMITATIONS` with evidence paths.

Stop after offline corrections, tests, and a reviewable fresh study package. No live GMS changes, deployment, commits, downloads, paid service use, hidden-schema-only treatment, or new model execution.
