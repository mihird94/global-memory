# CCMP v1.1 — Independent Evidence and Research Validity

Date: 2026-10-11 (America/Los_Angeles)
Status: implementation handoff; acceptance pending

## Mission

Repair the evidence chain behind CCMP's synthetic research claims before adding another policy, integrating with live GMS, or presenting downstream agent-performance results. Preserve the v1 package and original evidence. A valid negative result is an acceptable research outcome; broken measurement is not.

Implementation target: `/Users/mihirdeshpande/projects/learning/agent_memory/_research/ccmp_v1`.
This specification lives in the GMS repository to preserve the handoff. It does not authorize live GMS integration.

## Independently observed baseline

The supplied run is `evidence/runs/ccmp_evaluation/20261011_175542_685947Z-2a6206b74528`; the supplied audit is `evidence/audits/20261011_175639_543915Z-17acc5503832`.

On October 11, Codex reran `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ccmp_v1/tests -v` from the parent `_research` directory: **31 tests passed**. The experiment and audit were inspected as source, not independently rerun in this review. The reported 11-gate verdict is a v1 self-audit result, not independent acceptance of its scientific conclusions.

Source findings that this pass must address:

1. `evaluator/counterfactual_engine.py::execute_task_simulation` assigns success and fixed costs from required/forbidden memory IDs. Missing required memory still succeeds at a higher assigned cost. These are simulator assumptions, not observed agent behavior.
2. `evaluate_candidate_policy` tests one candidate at a time against tasks that can require multiple memories. Its lift is a nonnegative optimality indicator, so harmful promotion cannot produce negative lift. Mode D passes an unconditional empty set to task execution instead of querying post-contest graph visibility. The same DAG is contested repeatedly across a candidate's tasks.
3. `experiments/run_ccmp_evaluation.py` writes contest rows containing a receipt and `reversal_complete`; `audit/verify_acceptance.py::audit_gate_9_contest_invalidation` counts those flags. It does not reconstruct affected descendants or independently verify fault rollback. The claim of 5,120 events does not establish 5,120 independent graph/fault scenarios.
4. Calibration targets realized A-versus-B lift, which depends on the policy's own promotion action. This confounds candidate benefit prediction with the decision to expose that candidate.
5. `data/generate_benchmark.py` accepts a seed without using it to vary scenario generation. Classes, templates, and labels are directly coupled. The bootstrap resamples replay rows without preserving shared candidate/task/template dependence.
6. The temporal auditor uses provenance creation time instead of the experiment's explicit decision reference time, checks expiry alone, and compares timestamp strings. Candidate admission checks reference-time bounds inside the `valid_to is not None` branch, leaving open-ended future validity insufficiently checked.
7. Receipt hashing omits evidence, sensitivity, validity, policy/configuration, and decision rationale. CCMP computes a receipt decision through a different expression from its final decision branches; consistency is not guaranteed for all valid configurations.
8. Manifests provide SHA-256 consistency, not authenticated digital signatures or filesystem immutability. Hypothesis candor checks reported hypothesis fields against other reported fields rather than rebuilding all findings from verified inputs. The verifier imports production validation/metrics helpers, allowing shared bugs.

These observations supersede broad interpretations of the supplied summary. They do not invalidate the historical files or assert that all numerical aggregates are wrong.

## Boundaries

- Keep all experiments hermetic: synthetic fixtures and injected temporary stores only. No reads of private live memory for benchmark construction; no writes under `~/memories`.
- Preserve original runs/audits byte-for-byte. New outputs go in new exclusively created directories. Do not silently regenerate historical evidence or edit old manifests.
- No deployment, commit, model installation/download, scheduler change, GMS production wiring, employer data, novelty assertion, or filing-readiness claim.
- Keep v1 evidence schema readable. Version changed contracts explicitly and document migration/compatibility behavior.
- Scope tiers are semantic authorization boundaries in this harness, not demonstrated production ACLs. In-memory rollback is not distributed transaction safety.

## P0 — Rebuild counterfactual semantics

### Paired replay contract

Use a frozen task episode with a complete background memory store and one explicit candidate intervention. Evaluate A/B/C/D from identical initial snapshots, task inputs, seeds, retrieval configuration, and resource budgets:

- A: the policy decision determines candidate availability.
- B: withhold the candidate; preserve all other background memories.
- C: force candidate exposure solely in the isolated stress simulator; label the authorization bypass explicitly.
- D: start from C's promoted state, contest it, then obtain available memory IDs through the actual post-contest retrieval path.

Each task executes against the full visible memory set, allowing conjunctions, distractors, conflicts, and interactions. Keep single-candidate marginal evaluation as a separately named estimand. Add full-policy rollout evaluation over batches of candidates; do not imply marginal experiments measure batch effects.

Emit task instance ID, episode/lineage/template group, candidate intervention, policy/config digest, reference times, initial snapshot digest, actual retrieved IDs, exposure decisions, simulator outputs, and outcome reasons for every mode. Record untouched controls.

Predeclare signed success/quality differences and signed token/tool cost differences. Harm, privacy, stale exposure, and scope violations remain separate measurements. If reporting a composite utility, predeclare its weights and units; do not hide safety losses in an aggregate. Rename the v1 positive-only measure to `optimality_gain_indicator` when retaining it for compatibility.

Tests must demonstrate a beneficial intervention, a harmful intervention with negative success/quality delta, required-memory conjunction, unrelated-memory preservation, and an intentionally broken contest implementation causing D to leak and fail. A/B/C/D must be independently initialized or explicitly represent a verified ordered lifecycle; repeated contests must not inflate distinct-event counts.

### Simulator disclosure

Keep `evaluation_kind=synthetic_structural_simulation` in machine-readable results and all reports. Fixed costs are assigned synthetic costs. No claim of measured agent accuracy, token consumption, or causal real-world utility is allowed from this simulator. A future behavioral track requires an executable worker, answer artifacts, independent task checking, and measured usage; that is outside this pass.

## P0 — Audit contest state rather than flags

Emit reconstructable graph snapshots/events before and after every distinct contest, target root, expected reachable closure, observed affected IDs, unrelated controls, event order, result, and retrieval exposure. Build an independent traversal in the auditor.

For each supported failure injection point, record the pre-state, fault location, operation outcome, and restored semantic state. Recompute exact node/edge/status restoration. Specify the permitted append-only rollback audit event separately; do not demand audit history deletion for byte-identical rollback. Verify event sequence/counters and retained object references do not expose invalid partial state.

Exercise chains, diamonds, multi-parent descendants, unrelated subgraphs, repeated contests, unknown roots, cycles/missing parents, and derivation after ancestor invalidation. Never allow an invalid parent to create a current active descendant. Test true concurrency only if supported; otherwise label sequential idempotence accurately. Existing `test_06_concurrent_contest_idempotent` alone is not proof of concurrent safety.

Report unique graphs, unique contest operations, retries, successful cascades, injected failures, and rollback observations separately. Rollback with no injected-failure evidence is `NOT_EVALUATED`, not 100%.

## P0 — Time, authorization, and receipt integrity

1. Parse aware timestamps and normalize to UTC; reject malformed/naive values unless an explicitly documented conversion applies. Use injected `decision_time`, `task_time`, and `contest_time`, never wall-clock fallback in reproducible acceptance.
2. Adopt explicit half-open validity `[valid_from, valid_to)` with infinity for missing `valid_to`; reject empty/inverted windows. Always check premature validity, including open-ended records. Test equality and timezone offsets.
3. Revalidate availability at task execution time. A candidate valid when admitted can expire before a later task. Independently audit both admission and exposure.
4. Either implement distinct valid-time and transaction-time histories plus two-axis historical queries, or replace every bi-temporal claim with the narrower implemented valid-time claim. Do not invent a second temporal axis for a green gate.
5. Scope checks must include owning project/task/team identifiers and membership, not just tier ordering. Project A memory must not leak into sibling project B. Unknown scope/tenant/time fails closed. Keep always-promote's deliberate unsafe baseline outcomes separate from enforced policy safety gates.
6. The current validator rejects confidential-to-team promotion unconditionally and has no approval-token contract. Retain that prohibition for v1.1 and correct token-based claims. Implementing approval tokens requires a separately specified authority, binding, expiry, and revocation contract.
7. Compute the final decision once, then hash a versioned canonical JSON receipt envelope binding candidate content, evidence/source digests and lineage, authority/scope identifiers, sensitivity, validity, injected decision context, policy version/configuration, rationale, and resulting decision. Distinguish event time from irrelevant process wall-clock metadata. Avoid ambiguous delimiter concatenation.
8. Receipt tests must cover invariance to PID/hostname/process clock and canonical ordering, and sensitivity to every decision-relevant field. Recompute every saved receipt, not a single fixture. Threshold configuration must alter actual decisions consistently; reject unsupported settings explicitly.

## P1 — Statistical identification and calibration

- Freeze a protocol file before new evaluation. Declare task population, primary estimands, hypotheses, policy thresholds, ECE bins, resampling units, seeds, splits, missing-data handling, and exploratory analyses.
- Split by source lineage/scenario family, not paraphrase rows. Separate tuning data from one frozen holdout. Prove seed variation changes generated scenarios, not only output metadata. Correlated variants remain labeled variants.
- Use at least five independent generator seeds with per-seed results; this is a robustness floor, not proof of statistical power. Document independent scenario-family counts and limitations. Use paired cluster bootstrap over the declared independent family/episode units; preserve task/candidate dependence and shared policy comparisons.
- Define calibration targets independently of the policy action: e.g. probability that forced candidate availability improves the task relative to withholding, using C versus B. Distinguish benefit probability from expected signed utility. Do not apply Brier/ECE to an unbounded signed utility score.
- Include reliability bins/counts, Brier, calibration coverage, and uncertainty; state deterministic heuristic scores are uncalibrated unless validated on held-out outcomes. Empty/mismatched/nonfinite inputs must fail or be not-evaluable, never return perfect zero error.
- Audit policy-facing inputs: strip ground-truth labels and benchmark class names. Add keyword-free harmful examples, benign quoted attack text, evidence-copy/source-laundering cases, temporal reversals, and minimum-scope alternatives.
- Add safety-equivalent ablations: same admission/scope/time gates with utility gating disabled; utility-only and risk-only controls; simple frozen heuristic; always/never sentinels. Separate the benefit of deterministic gates from the contribution of utility scoring.
- Derive H1–H4 from raw paired outcomes and declared tests. H1 addresses the newly declared utility estimand; H2 reports harm and privacy separately; H3 uses held-out action-independent calibration; H4 uses independent graph/fault evidence. Unsupported or inconclusive hypotheses do not automatically make the harness structurally invalid.

## P1 — Independent verifier and evidence package

The verifier must not import production policy, admission, traversal, or metric implementations for its independent checks. Shared serialization schema is acceptable; independent small reference implementations and hand-calculated fixtures establish correctness.

Require fixed expected file sets and schema versions; reject missing policies/modes/tasks, duplicate record IDs, unresolved references, truncated JSONL, nonfinite values, inconsistent labels, empty populations, and denominator mismatches. Rebuild labels from frozen benchmark truth, not `ground_truth_promotable` copied into decisions. Recompute every reported aggregate, CI, bin, hypothesis, graph property, and receipt before comparing reports.

Privacy scanning must cover benchmark, raw JSONL, logs, reports, and manifests. Describe exact pattern coverage; a finite regex list cannot certify absence of all personal names or secrets. Do not include private host paths in portable evidence.

Bind code snapshot hashes (including uncommitted sources), benchmark/protocol/configuration hashes, dependency/runtime provenance, output bytes, and audit target identity. Reject path traversal, symlinks escaping the run root, missing required entries, and unexpected artifacts. Choose runs by explicit ID; avoid mtime-based implicit acceptance.

Use `hash_manifest_verified`, not `signed`, unless authenticated signatures and a verifier trust root actually exist. Describe directories as append-only by application convention and tamper-evident relative to a retained digest; do not claim an attacker cannot replace both files and local manifests.

Mutation tests must alter one layer at a time and assert a failed audit: forged reversal flags with a leaked descendant; omitted rollback trace; modified validity; decision/receipt disagreement; wrong ground truth; changed CI/calibration bin; duplicated/deleted replay; missing policy; stale exposure; sibling-project leakage; and source change after run. Also use internally rehashed malicious packages to prove semantic checks go beyond digest matching.

## Deliverables and acceptance

Deliver source repairs, focused adversarial tests, versioned protocol/schema, independent verifier, new run/audit directories, updated technical report, and an append-only claim-correction register. Map each v1 claim to retained/qualified/superseded, with rationale and exact evidence references. Preserve originals.

Acceptance gates:

| Gate | Required evidence |
|---|---|
| Paired execution | Complete A/B/C/D snapshots and actual exposures; negative outcomes represented |
| Contest/rollback | Independent closure and fault-restoration checks; controls unaffected |
| Temporal/scope | Decision/task-time boundaries and sibling-scope isolation verified |
| Receipt integrity | All saved decisions bound and independently recomputed |
| Statistical validity | Frozen protocol, leakage-free splits, clustered paired estimates |
| Calibration | Declared independent target; finite validated inputs; held-out records |
| Evidence audit | Complete independent recomputation and semantic tamper rejection |
| Claim honesty | Structural simulation labeled; no signature, concurrency, bi-temporal, or agent-performance overclaim |

Allow gate statuses `PASS`, `FAIL`, `NOT_EVALUATED`; required missing evidence closes acceptance. Report hypothesis support separately from implementation acceptance. Successful completion means `CCMP_V1_1_SYNTHETIC_HARNESS_VALIDATED`, not production readiness or empirical agent benefit.

Run the full unit suite and independent verifier against an explicit new run, plus the verifier mutation matrix. Add CLI options for explicit output roots/run IDs/protocols as needed and document exact commands that actually executed. Do not rerun old experiments in place.

Return:

```text
IMPLEMENTED=
TESTS=
PROTOCOL_AND_CODE_HASHES=
NEW_RUN_ID=
NEW_AUDIT_ID=
STRUCTURAL_ACCEPTANCE=
H1_H2_H3_H4_RESULTS=
UNIQUE_SCENARIOS_AND_CONTESTS=
FAULT_ROLLBACK_EVIDENCE=
CLAIMS_QUALIFIED_OR_SUPERSEDED=
KNOWN_LIMITATIONS=
```

Stop after implementation and verification. Do not wire into live GMS or begin a behavioral model study under this specification.
