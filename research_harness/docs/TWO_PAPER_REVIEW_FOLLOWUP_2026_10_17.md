# Follow-up audit of manuscript remediation

2026-10-17. Independent offline checks: harvesting evaluator tests 10 passed; recovery unittest discovery 33 passed. No real inference rerun or external package modification.

## Accepted improvements

- Candidate and rationale metrics are scoped as proxies; graph matching now includes all three fields with one-to-one assignment.
- Temporary disk persistence and readback replace the earlier schema-only durable-storage counter.
- Exact paired permutation, McNemar, bootstrap, and Holm helpers are now implemented; rehearsal findings stay unevaluated.
- Paper 2 describes visible invalidation metadata and distinguishes conversational continuity from per-opportunity environment execution.
- The saved `/tmp/qwen3_think_intervention.json` records a useful intervention on one Qwen3:8b fixture: thinking enabled produced 1536 evaluated tokens, 7183 thinking characters, zero response characters and termination by length; disabled produced 564 tokens, 2054 response characters and two parsed candidates. This is saved-run evidence, not an independently repeated inference experiment.

## Remaining blockers and limits

1. **Partial trajectories still enter statistical comparisons.** In `ccmp_recovery/evaluator/contrasts.py`, completeness checks only that all four trajectory objects exist. Pair construction also checks only object presence, divides stale counts by three regardless of observed opportunity count, and does not exclude `is_right_censored` trajectories or require control invocations. Thus a halted trajectory object can be analyzed as an ordinary completed episode. Entirely absent scheduled episodes are invisible because the episode set is the union of observed trajectories. Bind the analysis to the frozen schedule; validate unique expected opportunity IDs, appropriate outcome-specific observation windows and controls; retain partial observations and distinguish fixed-window completion from time-to-recovery censoring. Report complete-pair counts per contrast.
2. **Point estimates and uncertainty need one population.** Reported H1/H2 deltas use marginal aggregate arm rates, while permutation tests and confidence intervals use per-episode pairs. Under missingness these are different estimands. Compute the reported paired estimate, intervals, p-values and status from the same eligible episode pairs. Define H3's cost estimand and quality constraint explicitly; retention significance does not test token efficiency.
3. **The storage audit is still a surrogate.** It creates simplified candidate/relationship tables and simulates retrieval by projecting selected fields. This establishes persistence/readback behavior for that surrogate, not end-to-end production admission, promotion, indexing and retrieval. Either label its scope throughout or add an isolated integration test through real product entry points. Distinguish duplicated JSON/SQLite representations from independent records in the 0/14 denominator.
4. **Empty graph output is not a successful graph safety test.** The reported raw/admitted graph stages are 0/0. Separate unavailability, parse failure, empty valid output and admission rejection. Add valid positive controls and prohibited graph outputs before claiming graph-boundary protection from that run.
5. **Thinking evidence is narrower than the abstract.** The inspected intervention is one fixture on Qwen3:8b. Do not attribute its exact 7183-character trace or causal intervention result to Qwen3.5:9b without corresponding raw evidence. Preserve raw requests/responses, supported thinking metadata and model/runtime identities in a durable run bundle rather than only `/tmp`.
6. **Generalization remains open.** A repaired known query, three gold scenarios, eight authored recovery episodes, and correlated variants remain development/pilot evidence. Freeze inputs and settings, obtain held-out evaluation, and run the real recovery comparison before presenting policy efficacy or submission readiness.

## Verdict

Substantial remediation accepted; “all blockers resolved” is premature. Next priority is schedule-aware paired analysis and honest storage-audit scope, followed by frozen held-out studies. The two-paper direction remains viable; no publication or model sweep is authorized by this review.
