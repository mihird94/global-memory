# CCMP Behavioral v3 — Execution Readiness

Date: 2026-10-12 (America/Los_Angeles)
Status: offline implementation required; model execution not authorized by this handoff
Target: `/Users/mihirdeshpande/projects/learning/agent_memory/_research/ccmp_behavioral`
Predecessor: `docs/CCMP_BEHAVIORAL_V2_CONSTRUCT_VALIDITY_REMEDIATION_SPEC.md`

## Review outcome

Retain the revised timezone/false-stress/axis corrections and equal documentation access. Do not rerun the old corpus or infer execution readiness from corpus-count/character-length tests. Prepare one genuinely executable, independently verifiable fresh study package before proposing real runs.

Independently observed blockers:

1. `run_staged_experiment` always constructs `TaskRegistry()`; the fresh corpus requires `TaskRegistry(use_new_study_tasks=True)`. The runner CLI has no fresh-study/protocol selection. Supplying `protocol_path` copies a file but does not drive task choice, arms, repetitions, worker configuration, or ceilings.
2. Fresh corpus contains 4 easy/redundant, 4 easy/source-specific, 4 harder/source-specific tasks and **zero harder/redundant tasks**. All 12 contain one implementation file. This supports descriptive task strata, not a complete 2×2 causal factorial design or a multi-file claim.
3. Character matching passes, but word matching fails in six comparisons: `task_tb_01` placebo (16.2%), `task_tb_02` placebo (10.5%), `task_tb_03` stress (10.8%), `task_sm_02` stress (12.8%), and `task_st_03` placebo/stress (12.1% each). The test checks characters only. Neither character nor word matching establishes tokenizer matching.
4. New corpus test checks an `Authoritative Spec:` string and category presence, not actual source parity, correctness, transfer provenance, or contradiction. For example `task_tb_02` transfer says initialize tokens to capacity without qualifying the explicit `initial_tokens` override required by the task.
5. Power planning still substitutes headroom for an infeasible target, assumes discordance, and the v3 protocol retains an unsupported 12.5-point sensitivity number. Existing baseline success and inferred sample sizes must not be generalized to the fresh unexecuted corpus.

## A — One protocol-driven execution path

Implement an explicit versioned corpus selector and protocol-driven runner; preserve legacy replay behavior. A dry-run command must emit exact task IDs, corpus/source/protocol hashes, candidate pools/selections, prompt hashes, worker configuration, expected task/arm/repetition keys, and applied budgets without contacting a model.

Validate the protocol before allocating an output run or model: unknown corpus/task/arm, missing required ceilings, duplicated cells, unsupported settings, and configuration disagreement fail closed. The CLI must expose the same path used by the callable runner. Do not accept a protocol file that is merely copied while hardcoded defaults determine execution.

Auditor and runner select the same frozen corpus version. Store complete task/memory/checker/parser/config snapshots inside each new run. Never reconstruct v3 with the old mutable registry. Provide a fake-worker end-to-end rehearsal exercising the actual fresh IDs and all intended arms. Mock/deny network access and assert zero backend calls during dry run/offline tests.

## B — Define the study honestly

Recommended bounded design: retain 12 fresh tasks and call this an exploratory **procedural-summary aid study with three task strata**. Remove the full-factorial interaction hypothesis and claims of independent causal effects of difficulty/information placement. Common documentation stays identical across arms. No claim of saved interactive discovery is permitted for the single-completion worker.

If a full factorial design is essential, prepare matched task variants covering all four cells and freeze their common lineage and randomization rules; do not pretend renamed unrelated tasks are matched variants. Submit the revised design and budget before execution. Do not expand task count automatically.

Define transfer as a procedure derived from an inspectable distinct source task/artifact. Current metadata `source=synthetic_execution` does not establish a real source execution. Preserve generator/authorship honestly: manually authored summaries are acceptable but must be named as such. Include applicability/exception conditions; independently check summaries against the target contract without granting hidden information.

For every task provide: complete authoritative requirements; known-correct implementation; at least two plausible incorrect implementations; public/hidden check inventory and counts; verification that correct passes and incorrect fails for intended reasons. Run these offline. Include boundary cases such as initial state overrides, failed consumption/refill timestamp updates, half-open limits, handler errors, and cycles where specified. If source/task requirements are inconsistent, resolve and version them before freezing.

Stress candidates must contradict a named requirement and have an executable witness showing the consequence of following them. Placebo must be truthful/irrelevant under the declared applicability. Match character and word lengths to the promised tolerance and, where an installed tokenizer is available, match actual prompt-context token increments within a prospectively fixed tolerance. If tokenizer counts are unavailable, qualify the matching claim and retain a token-overhead confound; do not call it eliminated.

## C — Budget and missingness semantics

Keep protocol's proposed ceilings as a **proposal**: 96 model attempts, 3600 seconds, 100000 total model tokens. None is renewed by this specification. Include all smoke calls/retries and record unknown usage; do not count unavailable tokens as zero.

Enforce elapsed end-to-end wall time including hidden checking. Before each dispatch, cap its timeout and generation allowance to remaining feasible budget. Account for prompt tokens and provider uncertainty; specify bounded overshoot where exact hard token control is unavailable. Stop safely and preserve partial evidence.

Unattempted budget-skipped cells are `NOT_EVALUATED`, not failed agent attempts. Separate planned, attempted, completed, timed-out/crashed, skipped, and checked counts. Do not give omitted cells false checker booleans that flow into success denominators. Report partial matched-pair availability and protocol-defined missingness; do not turn resource allocation into an agent performance loss. Retain failed actual attempts for intention-to-treat analysis.

## D — Analysis and independent validation

Remove unsupported power/sensitivity numbers from v3. Keep an exploratory budget; report planning assumptions separately. Infeasible target effects return an explicit infeasible result without a sample size for a different target. Accept externally specified consistent discordance assumptions and validate their feasibility against baseline/effect. Use real independent family/repetition structure; do not treat three tasks or repeated deterministic outputs as independent source families. Normal-quantile correctness alone does not validate the power model.

Predeclare descriptive contrasts: transfer−withhold, transfer−placebo, and stress−withhold; success, harm, and cost remain separate. Neutrality requires a declared equivalence margin and suitable uncertainty, or remains a descriptive observation. Preserve ties and negative effects; do not force hypothesis support. The three strata are descriptive unless a valid randomized manipulation is supplied.

Independent acceptance must reconstruct exact prompts and selected memory bytes, checker outcomes from frozen artifacts, expected schedule, all reported contrasts/uncertainty, matching diagnostics, budget history, and missingness. Validate semantic errors even after manifest rehashing. Add tests proving wrong corpus selection, copied-but-ignored protocol, inaccurate transfer exception, character-only matching, falsely declared factorial cells, omitted checker, and skipped-cell denominator inflation fail explicitly.

## Deliverables and final execution gate

Return:

```text
DRY_RUN_COMMAND_AND_SCHEDULE=
FRESH_CORPUS_AND_PROTOCOL_HASHES=
REFERENCE_AND_COUNTEREXAMPLE_CHECKS=
TRANSFER_PROVENANCE_AND_APPLICABILITY=
STRESS_WITNESSES_AND_MATCHING=
STUDY_STRATA_AND_REMOVED_CLAIMS=
BUDGET_ENFORCEMENT_AND_MISSINGNESS=
INDEPENDENT_AUDIT_TESTS=
PROPOSED_REAL_EXECUTION_COMMAND_AND_CEILINGS=
KNOWN_LIMITATIONS=
```

Stop after offline preparation and a reviewable schedule. No model calls, downloads, private memory changes, deployment, or commits. Real execution requires the subsequent user execution decision against this concrete package.
