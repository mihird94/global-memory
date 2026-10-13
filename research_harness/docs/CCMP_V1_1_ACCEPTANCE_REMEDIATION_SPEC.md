# CCMP v1.1 — Acceptance Remediation Contract

Date: 2026-10-11 (America/Los_Angeles)
Status: independent acceptance rejected; corrective implementation required
Target: `/Users/mihirdeshpande/projects/learning/agent_memory/_research/ccmp_v1`
Parent contract: `docs/CCMP_V1_1_RESEARCH_VALIDITY_SPEC.md`

## Outcome and scope

The v1.1 implementation improves signed outcome reporting, action-independent calibration, scope/time modeling, and disclosure. Its acceptance verifier does not establish its claimed guarantees. Do not treat `CCMP_V1_1_SYNTHETIC_HARNESS_VALIDATED` as accepted until this corrective pass closes the evidence gaps. Keep H3's unsupported result visible; do not tune the benchmark to make H3 pass.

Preserve all existing runs, audits, and original evidence. Add new versioned artifacts and append corrections. No live GMS integration, writes under `~/memories`, deployment, model downloads, or commits. This is a bounded repair of the prior contract, not a new research subsystem.

## Independently reproduced evidence

Codex reran the full suite: **43 passed in 1.657 seconds**. The baseline auditor returned all eight gates PASS against run `20261012_005900_459885Z-3f9cddb72fd4`.

For each mutation below, Codex copied that run to a new temporary directory, applied exactly one mutation, recomputed all artifact digests/sizes in the copied manifest, and invoked `CCMPV1_1Auditor.run_all_gates()` without writing an audit directory. **Every corrupted package still returned all eight gates PASS**:

| Mutation | Violation undetected |
|---|---|
| Replace every decision receipt with 64 zeros | No cryptographic receipt recomputation or cross-record binding |
| Add the contested candidate to Mode D's retrieved IDs | Reversal flag trusted despite actual exposure |
| Change rollback post-state digest and set nested restoration flag false | Top-level `rollback_verified=true` overrides contradictory evidence |
| Delete one replay row | No expected record cardinality/completeness check |
| Remove `ccmp_safety_only` from replay, decision, contest, and batch logs | Missing policy not detected |
| Set reported H1 utility mean to 999999 | Hypothesis and utility aggregates not recomputed |

Machine-readable results: `reports/ccmp_v1_1_independent_audit_2026-10-11.json` in the GMS repository. These tests demonstrate verifier defects; they do not claim an adversary can alter an independently retained manifest digest undetected.

## P0 — Replace declarative gates with executable checks

### Complete receipt reconstruction

`audit_gate_4_receipt_integrity` currently checks length only; its independent receipt-hash helper is unused by that gate. Save enough canonical envelope data to reconstruct each receipt from frozen candidate inputs, complete policy/configuration, rationale, scope/authority, sensitivity, validity, and injected decision time. Independently hash and compare every saved receipt, then join decision/replay/candidate records and verify consistency. A 64-character arbitrary hex digest must fail. Merely hashing a supplied envelope without checking its fields against authoritative inputs is insufficient.

### Contest closure and rollback reconstruction

`audit_gate_2_contest_rollback` currently reads success flags. The experiment's graph snapshot log contains only episode ID, initial background digest, and control IDs; it cannot reconstruct nodes or edges. Emit actual pre/post node/edge/status snapshots, contest identity/root/time, observed retrieval, and permitted audit-event differences. Independently traverse expected descendants and compare invalidated sets and actual exposure. Check unrelated controls remain unchanged.

Emit fault trial inputs, exact injection point, pre/post semantic snapshots, and audit history. Independently hash those snapshots and verify restoration. Compare all flags against recomputed state; never use flags as evidence. A forged positive flag with leaked candidate/descendant or mismatched restoration must fail.

The run currently includes one two-node rollback trial at one failure step. Do not call that coverage across all unique graphs. Add chain, diamond, multi-parent, disjoint-control, invalid-parent, repeated-contest cases and all supported mutation failure stages. Report attempted/verified distinct graph/fault pairs, skips, and failures. Keep sequential idempotence separate from concurrency.

### Authoritative input and record inventory

Freeze benchmark episodes, task definitions, protocol, policy configurations, code snapshot, and expected inventory inside the run package. Independently derive expected policies × episodes × tasks × modes and operation identities. Reject duplicate IDs, one missing row, missing policy, unexpected rows, unresolved references, wrong split membership, malformed/empty datasets, NaN/infinity, and mismatched denominators. Validate exact file sets and schema versions before semantic evaluation.

Derive privacy/scope/staleness from candidate and background-memory metadata, task ownership/time, and actual retrieved IDs. Ignore self-reported safety flags as proof. Check all enforced policies; explicitly label deliberate always-promote or forced-exposure bypasses. Check admission at decision time and exposure at each task's own time. Do not substitute task 0's time for subsequent tasks.

### Raw recomputation

Independently recompute each mode's simulator output from frozen task/exposure inputs; signed deltas, composite utility using the frozen protocol weights, target C-versus-B benefit, reliability bins, ECE/Brier for every policy, classification labels, paired estimates, CIs, and H1–H4. Compare all aggregates and hypothesis reports against recomputed values. Cross-check action-independent targets agree across policies for identical interventions.

Gate functions must invoke their independent helpers. Defining BFS/hash routines without using them is not verification. Use hand-calculated tiny fixtures to validate the reference implementation independently of producer outputs.

## P0 — Correct Mode D and batch execution

Mode D currently uses `retrieved_B.intersection(active_ids)`. That construction excludes the candidate even if the contested graph still returns it, and its exact-scope query can drop valid team-scoped background prerequisites. Build the candidate-inclusive store, contest it, and run the actual authorization/time-aware retrieval over all remaining active nodes. Preserve valid unrelated background memories across scope tiers. Recompute D's outcome from that actual result. Inject a no-op contest and assert both leaked exposure and failed reversal are observed.

The current batch rollout only records `candidate_promoted` and task count for a single candidate. Implement a genuine multi-candidate shared-store rollout with downstream task outcomes and memory interactions, or remove batch-policy rollout from implemented claims and mark that required estimand NOT_EVALUATED. Full acceptance remains closed while a required estimand is missing; do not silently redefine the contract to get a PASS.

Add dedicated tests importing `counterfactual_engine_v1_1`, `policies_v1_1`, and the actual new runner. The existing engine/policy tests still import their v1 counterparts and do not verify v1.1 engine behavior.

## P1 — Repair scenario independence and inference

`generate_benchmark_for_seed` changes seed-dependent identifiers, not randomized scenario mechanics. All eight named families reuse the same five intervention templates and assigned costs. The two holdout names therefore do not establish semantic separation from tuning. The degenerate H1 CI `[26.10, 26.10]` reflects identical family-level outcomes; it is not strong evidence of population precision.

Generate real variation in independently meaningful task structures, content, costs, validity timelines, evidence lineages, interactions, and controls with a seeded RNG. Strip identifiers and compare structural fingerprints across seeds/splits; report duplicates and template leakage. Assign split groups by actual generative lineage/mechanism, not renamed families. Keep paraphrases correlated. Preserve the original holdout as already observed data; declare a new prospective protocol and holdout rather than claiming retroactive preregistration.

Pair policy outcomes by explicit episode/task/intervention keys before cluster resampling. Missing or mismatched baseline pairs must fail; the current bootstrap can silently omit baseline subtraction when a cluster is absent. Report independent cluster count, seed count, cluster means, variance, and degeneracy diagnostics. Set a justified minimum cluster criterion prospectively; insufficient independent evidence yields NOT_EVALUATED for inferential claims, while mechanical correctness can be evaluated separately. Do not force a nonzero interval artificially.

## P1 — Provenance and mutation-test honesty

The current manifest hashes only the runner as source code and does not verify even that source hash in the audit. Snapshot and bind all relevant producer/verifier/model/policy/generator/metric files, frozen protocol, dependencies, and benchmark. Distinguish replaying historical frozen source from checking whether the current checkout matches it. Reject escaping paths, symlinks outside the run, missing required manifest entries, and exclusive-directory creation collisions.

Replace misleading mutation tests with the named semantic changes. Existing examples:

- “Forged reversal” changes the flag to false rather than leaking a descendant while keeping it true.
- “Decision disagreement” shortens the hash rather than substituting a valid-length wrong digest.
- “Wrong ground truth” alters reported ECE instead of a label.
- “Deleted replay” empties the entire file instead of deleting one row.
- “Missing policy” changes seed metadata instead of removing a policy.
- “Stale exposure” and “Sibling leakage” change flags instead of actual exposure and ownership/time.
- “Source code change” appends a replay row instead of changing source.

Every semantic mutation must be internally rehashed and must fail the relevant semantic gate while digest consistency passes. Keep separate unrehashed byte-tamper tests for manifest integrity. Require unmodified-package PASS as a positive control. Failures must identify file/line/record, expected value, observed value, and violated invariant; crashing is not a successful rejection.

## Required verification and stopping condition

1. Preserve and reproduce the six demonstrated bypasses as regression fixtures before fixing the verifier. After repair, each must fail for the intended semantic reason.
2. Run all v1 compatibility and new v1.1 tests. Include no-op contest, cross-scope controls, multiple task times, actual batch interactions, nonfinite metrics, missing pairs, and semantic seed/split variation.
3. Produce a new evidence package with complete immutable-by-convention input snapshots and a new explicit audit target. Recompute every hypothesis; retain unsupported/inconclusive outcomes without forcing success.
4. Append a correction qualifying the prior eight-gate acceptance and historical H1/H4 evidence. Do not overwrite old reports.
5. Return source/config hashes, raw counts, gate results, six bypass regression results, v1.1-specific test names, batch status, independence diagnostics, H1–H4 outcomes, and limitations.

Stop after these corrections and verification. No further policy expansion or live integration is authorized by this handoff.
