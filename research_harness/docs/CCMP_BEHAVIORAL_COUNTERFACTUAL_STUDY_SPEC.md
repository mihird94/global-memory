# CCMP — Behavioral Counterfactual Memory Value Study

Date: 2026-10-11 (America/Los_Angeles)
Status: execution handoff; confirmatory execution blocked on verifier remediation

## Research question

Can a frozen memory-promotion policy predict and improve the actual downstream performance of a coding agent, beyond deterministic safety gates and simple selection heuristics?

The contribution sought is experimentally measured memory value under controlled interventions. This specification makes no claim of novelty, production readiness, or general agent intelligence. The unit of evidence is an agent's executed task and independently checked artifact, not a simulator-assigned outcome.

## Prerequisite and boundaries

Complete `CCMP_V1_1_ACCEPTANCE_REMEDIATION_SPEC.md` first. Its six demonstrated semantic bypasses must be rejected by the repaired auditor while the unmodified package passes. Preserve its positive and negative evidence. Until that gate closes, implementation of this study's runner, fixtures, checkers, and dry-run tests may proceed, but no result may be called a validated behavioral finding.

Build a separate hermetic package, preferably `ccmp_behavioral/` beside `ccmp_v1/` under `/Users/mihirdeshpande/projects/learning/agent_memory/_research`. Do not replace the structural simulator. Use new versioned evidence directories and retain prior evidence unchanged.

No live GMS writes, private memory import, employer artifacts, production repositories, deployments, commits, model downloads, or implicit paid API usage. Reuse an already available authorized agent backend. If credentials, a paid service, or a new installation are needed, finish the runnable local package and report the execution dependency. Never substitute simulated results for unavailable behavioral execution.

## Hypotheses and primary outcomes

Pre-register the protocol, thresholds, checker versions, baseline policies, seeds, splits, budgets, and analysis code before confirmatory execution. Commit hashes are useful provenance but committing is not required; hash the complete dirty source snapshot.

- **H1 — Memory efficacy:** eligible, independently supported memories improve task success relative to withholding on unseen task families.
- **H2 — Selection value:** the frozen CCMP utility policy improves success relative to safety-only exposure at the same memory/token budget. If it does not, report no demonstrated incremental value of utility gating.
- **H3 — Predictive validity:** frozen benefit predictions improve held-out Brier score over a constant predictor estimated on development data. ECE and reliability plots are secondary diagnostics, not a threshold to optimize retrospectively.
- **H4 — Safety:** policy-selected memories do not exceed a predeclared task-harm noninferiority margin relative to safety-only exposure. Set and justify that margin before holdout. Zero observed failures alone is not evidence of zero risk.

Primary endpoint: binary task success from independent executable checks. Report artifact correctness, harmful changes, scope/privacy violations, abstention, observed model tokens, tool invocations, wall time, and billed cost where available separately. Do not combine safety and success into one headline score. Token/time efficiency is secondary; include the cost of policy scoring and context preparation.

## Task and memory corpus

Use small, self-contained coding repositories with deterministic hidden acceptance checks. Examples: API contract repair, configuration migration, cache invalidation, timezone boundary handling, parser repair, schema evolution, and concurrency bug repair. These are proposed families, not independent samples merely because their names differ.

Each task contains a versioned initial repository snapshot, user instruction, allowed tools, time/token/tool budget, public tests, hidden checks, and an independent task oracle. Required background facts must be available identically across arms. The intervention memory is additional context, not the task's answer key.

Represent each memory with content, source evidence, validity, applicability, scope, and lineage. Include:

- Accurate procedural knowledge that transfers from a different source task.
- Correct but irrelevant memory.
- A procedure valid only under a condition absent in the target task.
- Stale guidance and plausible false guidance.
- Benign quoted adversarial text and actual instruction-injection attempts.
- Complementary and conflicting background facts, labeled as exploratory interaction cases.

Useful/harmful labels must be grounded in task contracts and independently inspected source artifacts, not a keyword shared with the policy. Keep task answers, hidden tests, labels, and target outcomes out of policy/worker inputs. Record how memories were authored; model-generated candidates require generator identity and source lineage. Never treat an LLM judge as sole correctness authority.

Split by source repository/task generator/evidence lineage. Near duplicates, paraphrases, and variants remain in one split group. Check content/structural overlap and publish duplicate diagnostics. Freeze a fresh holdout: prior CCMP holdout names and templates are already observed development material.

## Experimental arms

First run an efficacy experiment with paired memory-present and memory-withheld conditions. Then run the selection experiment with the following frozen policies:

| Arm | Context selection |
|---|---|
| Withhold | Identical background; candidate memory omitted |
| Safety-only | All eligible candidates up to a fixed budget, with deterministic tie ordering |
| Frozen heuristic | Same safety gates and budget; simple predeclared ranking |
| CCMP | Same safety gates and budget; frozen utility-aware ranking |
| Forced stress | Ineligible/false candidate forcibly exposed only in an isolated adversarial track |

The forced-stress arm is excluded from fair policy efficacy comparisons and labeled as an authorization bypass. All selection arms use the same candidate pools, safety boundary, allowed tools, task budgets, and token accounting. Do not let a baseline lose simply because it has less context capacity.

For a single candidate, define signed paired success effect as `success_present - success_withheld`. For policy comparisons, pair outcomes by task instance, repetition, backend, and candidate pool. Retain negative effects. Report empirical win/tie/loss counts.

The predicted probability target must be explicit: improvement in task success under exposure versus withholding, estimated over repeated executions. One observed paired win is a noisy observation, not an intrinsic ground-truth label for the memory. Freeze the repetition/target construction and uncertainty handling before evaluating calibration. Do not equate a heuristic utility score with a calibrated probability without a development-only mapping.

## Worker execution and isolation

Every run starts in a fresh checkout/container-equivalent sandbox with the identical initial task snapshot. Use the same tool/environment contract and model configuration. No prior conversation, shared caches containing answers, cross-arm writable directories, persistent agent memory, or access to holdout labels/checkers. Keep hidden checkers outside the worker-visible filesystem; verify this isolation before execution. Disable network by default.

Randomize arm execution order within blocks to reduce time/provider-order confounding. Use matched seeds where the backend supports them; describe them as best-effort controls, not a guarantee of identical stochastic trajectories. Record temperature, model/backend identifier, version information, seed support, and sampling parameters. Freeze provider/model changes or analyze them as separate blocks.

Record the exact prompt/context bytes, candidate pool and selected IDs, initial/final repository digests, tool trace, worker output, patch, independent checker output, usage metadata, and terminal status. Never synthesize usage when the backend does not provide it; mark it unavailable. Include worker failures/timeouts in the intention-to-treat analysis. Predeclare infrastructure retry rules and exclusions; preserve every attempted run.

Use safe fixture tasks without real credentials or external side effects. Harm includes breaking protected APIs, deleting unrelated artifacts, violating explicit constraints, or following injected instructions. Check these through independent guards and task checks, not worker self-report.

## Staged execution and budgets

1. **Offline harness validation:** fake worker fixtures test orchestration, isolation, failure accounting, and independent checkers. Label results contract tests; they contribute no behavioral observations.
2. **Feasibility pilot:** proposed default is 12 tasks across at least four actual source families, three repetitions, and paired present/withheld runs: 72 worker executions. Use development data only. Freeze an explicit run-count/token/time ceiling before dispatch; no unbounded automatic retries. This pilot informs variance, failure modes, checker reliability, and power planning, not confirmatory support.
3. **Confirmatory study:** determine task/family/repetition count from pilot variance, minimum meaningful success improvement, clustering, safety margin, and budget. Pre-register power assumptions and family-level uncertainty. If resources are insufficient, report an underpowered exploratory study rather than force a hypothesis verdict.
4. **Transfer replication:** if an additional backend is already authorized and available, freeze selection policy and test it without tuning on new tasks/backend. Otherwise mark transfer NOT_EVALUATED; absence does not justify a cross-model claim.

Do not expand execution beyond the declared ceiling automatically. If execution needs additional access or budget, deliver the package and pilot plan for review before dependent runs.

## Independent analysis and evidence audit

Analyze intention-to-treat outcomes. Report absolute success rates and paired percentage-point differences with uncertainty clustered by the actual source/task family; expose independent family count and repeated-run dependence. Use predeclared multiplicity handling for confirmatory hypotheses. Calibration analysis must account for repeated estimates and its target's sampling uncertainty.

Independently recompute all outcomes from retained artifacts/checker traces, rather than trusting result booleans. Validate policy/task/arm/repetition inventory, one-to-one pairs, exclusions, finite values, budgets, context equivalence, and source hashes. Recompute effect sizes, CIs, reliability bins, Brier scores, and hypothesis outcomes from line-addressable records. No production policy imports in the independent reference evaluator.

Mutation tests must catch: changed patch with unchanged success flag; forged checker result; one deleted/duplicated arm; a mismatched starting snapshot; hidden-test leakage; wrong selected memory; fabricated usage; inconsistent model configuration; altered exclusion; and rehashed fabricated aggregates. Semantic mutations must fail even after artifact manifests are recomputed.

The manifest binds complete code/config/protocol/task/memory/checker snapshots and raw outputs. It provides hash consistency relative to retained digests, not authentication or hardware immutability. Explicit run IDs are required for final acceptance.

## Deliverables and acceptance

Deliver a runnable worker adapter, task/memory corpus, isolated task runner, independent checkers, frozen protocol, analysis/reference auditor, mutation tests, reproducibility commands, and pilot/confirmatory evidence as execution availability permits.

Separate verdicts:

- `HARNESS_CONTRACTS_VERIFIED`: isolation, inventory, checker, and tamper tests pass; does not imply any model run occurred.
- `PILOT_EXECUTED`: real worker artifacts exist with measured outcomes; exploratory only.
- `CONFIRMATORY_STUDY_VALID`: preregistered design and independent evidence audit pass, regardless of hypothesis support.
- H1–H4: supported, unsupported, or inconclusive according to the frozen tests. Report NOT_EVALUATED where the required comparison did not run.

Return:

```text
VERIFIER_PREREQUISITE=
IMPLEMENTED_AND_TESTED=
WORKER_BACKEND_AND_AUTHORIZATION=
FROZEN_PROTOCOL_HASH=
EXECUTION_BUDGET=
TASK_FAMILIES_AND_SPLIT_DIAGNOSTICS=
REAL_WORKER_RUN_COUNTS=
SUCCESS_AND_HARM_EFFECTS_WITH_UNCERTAINTY=
CALIBRATION_TARGET_AND_RESULTS=
ACTUAL_USAGE_AND_UNAVAILABLE_FIELDS=
INDEPENDENT_AUDIT_AND_MUTATION_RESULTS=
H1_H2_H3_H4_VERDICTS=
EVIDENCE_PATHS_AND_LIMITATIONS=
```

Stop at the authorized stage and budget. Correction recovery and memory-interaction studies follow separately; do not add them as new confirmatory hypotheses to this run.
