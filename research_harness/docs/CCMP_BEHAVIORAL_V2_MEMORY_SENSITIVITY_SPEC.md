# CCMP Behavioral v2 — Memory Sensitivity and Evidence Recovery

Date: 2026-10-11 (America/Los_Angeles)
Status: next bounded research pass; implementation and verification required
Target: `/Users/mihirdeshpande/projects/learning/agent_memory/_research/ccmp_behavioral`
Parent: `docs/CCMP_BEHAVIORAL_COUNTERFACTUAL_STUDY_SPEC.md`

## Scientific objective

Determine whether the current null memory effect comes from redundant information, insufficient task difficulty, weak intervention delivery, insensitive correctness checks, or an ineffective memory policy. Do not assume a ceiling effect explains everything. Preserve the result that memory provided no measured success gain in the observed pilot while consuming more tokens.

This pass repairs behavioral evidence validation and constructs a diagnostic memory-sensitivity study. It does not launch the large confirmatory study or the later correction-recovery study. Negative results are valid outcomes.

## Baseline and independent review

Supplied pilot: `evidence/runs/ccmp_behavioral_pilot/20261012_032515_650813Z-c5d6baa8a94e`.
Its recorded summary reports 33/36 successes in both arms, 36 ties, zero wins/losses, and mean total tokens 551.9 versus 483.8. These are recorded outcomes pending stronger artifact-based validation; they do not establish that memory is useless generally.

Codex inspected source and independently reproduced three semantic auditor bypasses on separate temporary copies of this run, rehashing all changed artifacts in each copy:

1. Set paired mean success difference to 0.99: all gates still PASS.
2. Replace all initial/final repository digests with 64 zeros: all gates still PASS.
3. Forge all hidden-checker success flags to true and update summary success counts: all gates still PASS.

Baseline also passed. Evidence: `reports/ccmp_behavioral_pilot_audit_2026-10-11.json` in the GMS repository. These demonstrate semantic verification failures, not undetectable modification against an independently retained trusted digest.

Source observations:

- The snapshot gate checks digest length rather than hashing retained files; execution gate does not independently rerun task checks; statistical gate recomputes arm counts but not paired estimates, uncertainty, or usage means.
- Hidden-isolation gate scans worker output/tool trace for `test_hidden`; it does not examine the actual input prompt or filesystem visibility.
- The worker is a one-completion code-generation adapter, not an iterative tool-using coding agent. It has a hardcoded 256-token output limit. Wall time stops after generation and excludes patch application/checking.
- The generic code-block parser can match `python` as a filename and return before its generic fallback. Add a regression before asserting a model failure.
- The reported development-constant Brier score of 0.25 conflicts with the stated all-zero target if the constant is estimated as that target's mean: a fitted zero predictor has Brier 0 on the same sample. That in-sample score is not held-out predictive evidence.
- The inspected frozen protocol does not contain an executable derivation of the claimed 140-task/20-cluster power requirement. Require a derivation or withdraw the claim of preregistered power planning.

## P0 — Recover trustworthy artifact-level evidence

Preserve the old pilot and audit byte-for-byte. Inventory what actually survives: initial files, final files or replayable patches, exact prompts/responses, raw provider usage, model configuration, checker inputs/output, and complete source/protocol/task/memory snapshots. Never manufacture missing artifacts retrospectively.

If final repositories can be reconstructed deterministically, hash them and rerun frozen hidden checks in an isolated evaluator without model calls. Record new verification events linked to original records. If not, label affected claims NOT_VERIFIABLE and retain them as historical reported results. Do not call a hash-shape check reconstruction.

Repair the independent auditor to:

- Derive the expected task × arm × repetition inventory from a frozen schedule; reject missing/duplicate pairs, unmatched arms, and config discrepancies.
- Hash retained repository bytes, apply/reconstruct patches, and verify correspondence to worker output and actual permitted writes.
- Execute all hidden checker files, validate nonzero intended check counts, and distinguish checker crashes/timeouts from model failures. Bind checker source and verify known correct/incorrect implementations, including plausible near misses. Do not equate syntax validity with semantic correctness.
- Inspect exact worker-visible prompt/files/tool capabilities for hidden-test leakage. Treat the model endpoint's exposure separately from what the controller process can access.
- Recompute checker results, safety invariants, paired wins/losses/ties, estimates, confidence intervals, per-arm totals/means, usage denominators, and calibration from primary evidence. Match token counts to retained provider responses; token arithmetic alone cannot validate provenance.
- Verify complete frozen code/config/task/memory/checker snapshots and required artifact sets, including missing manifest-listed files. Audit an explicit run ID; preserve source-version differences honestly.

Promote the three demonstrated bypasses into rehashed semantic regression tests. Add forged provider usage with consistent arithmetic, missing one matched arm with adjusted summary, leakage through prompt contents, altered checker source, empty checker discovery, and false calibration/power reports. Require relevant semantic gate failures and an unmodified positive control.

Pin a supported Python/runtime and invoke checkers with that interpreter. The shell's default Python 3.9 cannot execute the current `str | None` annotations; report runtime incompatibility distinctly from research/test failures.

## P0 — Validate intervention delivery and repeatability

Retain the current backend as the primary instrument, labeled `single_completion_code_generation`. Make output-token, context, timeout, and generation parameters protocol-configurable. Retain actual finish reason/truncation when available. Record generation time, patch application, public checks, hidden checks, and end-to-end time separately. Capture response parse errors explicitly; a rejected/no-op patch is not proof the model lacked task knowledge.

Test named/generic code fences, multiple files, empty/malformed/truncated output, forbidden paths, and protected-file edits. Reconstruct exact bytes given to the model and verify the assigned memory is present only in its intended arm.

Match repetition seeds across arms and vary them between repetitions; retain deterministic temperature-0 replay as a repeatability diagnostic. Measure distinct outputs and effective repetition diversity. Repeated identical solutions do not create new task-family evidence.

## P1 — Separate difficulty from information value

Create a two-axis task design: easy/harder implementation crossed with redundant/source-specific procedural information. Every arm must receive the same complete user requirements and access to the same legitimate source documentation. Memory is a reusable retrieval/compression aid; it must not secretly provide a hidden acceptance rule available nowhere else.

Examples of source-specific knowledge: a documented project error convention, an interface-version migration exception, a cache generation invariant, or a parser dialect rule. Provide that authoritative source through a bounded read/retrieval tool identically in all arms. Log reads and effort. This measures whether memory saves discovery or execution work rather than rewarding possession of a secret answer.

If retaining the one-completion adapter without source tools, supply identical authoritative reference material in all arms and describe the intervention as a procedural summary aid. Do not claim interactive information discovery from this instrument.

Use independently checkable multi-file changes and boundary cases for the harder axis. Do not simply lower output budgets or omit requirements to induce baseline failures. Include enough capacity for a reference solution; verify this offline.

For each task construct four development-only interventions:

| Arm | Intervention |
|---|---|
| Withhold | No candidate; identical requirements, references, and background |
| Transfer memory | Verified procedure from a different source task, adapted only by frozen rules |
| Placebo context | Length-matched irrelevant but truthful procedure |
| Incorrect context stress | Plausible stale/misapplied procedure; isolated safety track |

Add a diagnostic solution-hint control to a small development subset if needed. Label it answer assistance, excluded from transfer efficacy. If even that control cannot alter task outcomes, investigate checker sensitivity/adapter capacity before interpreting the null.

Freeze task eligibility from contracts and structural properties before seeing arm outcomes. Report every generated task and rejection reason. Do not select only tasks with positive memory lift, retune on held-out tasks, or relabel weak tasks as independent families. Split by actual source lineage and mechanism; keep variants together.

## Bounded execution plan

Implement and run artifact recovery/offline validation first; no model calls are needed for that stage. Then freeze a new exploratory protocol and output a dry-run schedule before executing.

Proposed maximum: **12 fresh development tasks × 4 arms × 2 paired repetitions = 96 real generations**, with an aggregate 45-minute wall ceiling and explicit per-call/aggregate token ceilings derived from task capacity. Retain already available authorized local execution only; no new downloads or paid providers. Count failed attempts and retries toward the ceiling. Stop at the first exhausted ceiling; preserve partial evidence and do not replenish automatically.

Balance tasks across the two design axes and at least four genuine source families. This is a sensitivity pilot, not a powered confirmatory study. Keep all current holdout tasks unused by this pass. If a new worker/tool interface is required, validate it offline before consuming the run budget. No automatic follow-on model sweeps.

## Analysis and decisions

Report paired success, harm, and cost changes for transfer-versus-withhold and transfer-versus-placebo, stratified by information/difficulty axis. Show task-level outcomes, independent source-family counts, distinct output rates, truncation/parser failures, source reads if applicable, and token/time overhead. Attribute uncertainty to the actual clustered sampling design.

With zero discordant pairs, report observed zero effect and limited information, not a population effect known exactly. A degenerate empirical bootstrap may be displayed with that limitation; add a predeclared suitable interval/sensitivity analysis accounting for small independent samples. Do not switch methods after observing which interval supports a preferred conclusion.

Compute development constant predictors from the declared development target and evaluate on disjoint records or grouped cross-validation. Report in-sample scores as such. Independently audit Brier targets, baselines, and units. Avoid calibrating on this small exploratory sample and claiming general validity.

Power planning must be an executable artifact with effect-size assumptions, paired discordance, intracluster dependence, cluster sizes, error rate, multiplicity, and sensitivity ranges. Four source families cannot identify these precisely. Report plausible sample-size ranges and uncertainty; do not present 140/20 or another fixed number as derived without evidence.

Decision rules:

- Successful delivery with no transfer benefit: report no demonstrated benefit for these tasks/backend; do not force expansion.
- Benefit confined to source-specific tasks: scope the finding to that condition, then design a fresh confirmatory corpus.
- Hint control works but transfer memory does not: investigate memory content/transfer applicability.
- Hint control fails or checks/adapter are insensitive: fix instrumentation before another efficacy run.
- Harm rises with misleading memory: quantify vulnerability separately from useful-memory benefit.

## Deliverables and stopping condition

Return repaired artifact verifier and semantic tests; immutable-by-convention pilot correction/reverification package; pinned runtime and worker protocol; new source-grounded task/memory fixtures and independent checkers; frozen sensitivity protocol and schedule; actual bounded pilot evidence if prerequisites pass; and independently recomputed exploratory findings.

Report `OLD_PILOT_RECOVERABILITY`, `AUDIT_BYPASS_REGRESSIONS`, `INSTRUMENT_VALIDITY`, `TASK_INFORMATION_AXES`, `EXECUTION_BUDGET_USED`, `TRANSFER_VS_PLACEBO_VS_WITHHOLD`, `HARM_AND_OVERHEAD`, `CALIBRATION_CORRECTIONS`, `POWER_ASSUMPTIONS`, `EVIDENCE_PATHS`, and `NEXT_SCIENTIFIC_DECISION`.

Stop after the bounded sensitivity study or a failed prerequisite. Do not launch confirmatory execution, correction-recovery experiments, live GMS integration, deployments, commits, or private-memory mutations.
