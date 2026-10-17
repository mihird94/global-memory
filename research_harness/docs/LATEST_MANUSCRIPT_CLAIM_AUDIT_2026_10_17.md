# Latest manuscript claim audit

2026-10-17. Inspected both revised manuscripts, policy registry, extraction/retrieval implementation, saved ablation and partial pilot, plus primary-source literature. No new inference or manuscript edits.

## Improvements retained

Paper 1 now includes the incomplete frozen local pilot, source-faithfulness limitations and surrogate storage scope. The newly cited arXiv identifiers resolve to real, relevant papers. Paper 2 still has a plausible contribution in action-effect evaluation of correction propagation. Relevant literature strengthens the context, but does not establish our efficacy.

## New or remaining overclaims

1. **PACMI comparison is inaccurate.** Paper 2 says PACMI's confirmatory paired tests failed to reach significance, citing an error change from 11 to 3. PACMI reports a significant final-answer comparison against its strongest baseline; the nonsignificant result concerns its cascading-removal ablation. Distinguish those contrasts, and do not present our choice of exact tests as an empirical advantage before our own comparison exists. Source: https://arxiv.org/html/2610.05732v1 (abstract and statistical results).

2. **The cited cost paper already studies longer horizons.** Paper 2 characterizes Chu et al.'s finding as a short-horizon phenomenon and claims to resolve it with amortization. The cited work includes a length sweep with 20 later uses and task-filtered re-reading/repair variants. Our formula is a simplified conditional model, not an explanation that overturns their measurements. Match baselines, filtering, full ingestion/revision/response costs, quality and caching assumptions. Source: https://arxiv.org/html/2610.03902v1, Sections 6.2–6.3 and length-sweep tables.

3. **Budget arithmetic is not a necessity theorem for disabling thinking.** If total output budget is B, reasoning uses T, and minimum required schema length is L, T+L>B precludes that schema under the assumed tokenizer/serving contract. It does not imply that T must equal zero: T=100, L=500, B=1536 permits both. It also does not imply an empty visible response rather than a partial one, nor rule out a shorter valid no-write envelope. Present the single-fixture intervention as evidence of one serving/configuration failure; remove claims of universal mathematical necessity or guaranteed schema success with thinking disabled.

4. **Crossover model cannot prove superiority over full reset.** The stated equation compares `C_refresh + K*L_carrier` with `K*L_raw`. It requires positive `L_raw-L_carrier`, fixed costs, no additional updates and equal outcome quality. It says nothing about full reset without a separate cost model. For these simplified assumptions, the first integer K giving strict savings is `floor(C_refresh/(L_raw-L_carrier))+1`; distinguish this from a conservative sufficient boundary. Do not treat a hypothetical 50k/2k example as measured evidence.

5. **New A0 baseline is described as implemented but absent from the registry.** `PolicyRegistry` still contains the original four core policies plus a destructive-wipe diagnostic; `stateless_raw_reread` is not registered. Label A0 proposed until implemented and audited, then refreeze schedule, budget and statistical analysis. Eight episodes × five policies × four calls would be 160 initial calls, not the existing 128.

6. **Cross-harness prevention claim exceeds the gate.** The formula itself rejects actionability only when all focus items require corroboration. A direct offline probe with two equally relevant source-valid items—one verified, one unverified—returns `supported`. Therefore the gate is not a claim-level authorization reference monitor and does not establish exclusion of every uncorroborated instruction from a mixed packet. Prove source-event/permission binding and downstream enforcement before claiming protection against authorization laundering. Relevant primary work: https://arxiv.org/abs/2609.01836 and https://arxiv.org/abs/2607.27834.

7. **Tiered routing is not deployed.** `evaluate_regex_heuristic_baseline()` is an evaluation baseline over the labeled corpus. Inspection found no production Dream Cycle routing rule that reserves LLM calls for narrative-only inputs. Report baseline performance separately and label a modal-trigger router as a proposed intervention requiring its own coverage/quality study. Three scenario results do not establish a routing Pareto frontier.

8. **Turn index does not identify the proposed causal mechanisms.** First-turn versus later-turn errors do not isolate attention anchoring or autoregressive self-locking. Add controlled history-on/off, prior-action insertion/removal and carrier refresh interventions with equal tasks/budgets. Until then, use these mechanisms as hypotheses, not demonstrated explanations.

9. **Ablation table has the wrong sample count.** Manuscript Table 1 says 24 cases; its referenced `ablation_run_20261017_102439.json` records 45 queries for each strategy. Derive denominators from raw reports. Fixture dense embeddings must remain identified as synthetic rather than evidence for a real embedding model's quality.

10. **Reproduction pass does not mean empirical completion.** Default script mode runs tests, fixture evaluation and retrieval; it does not rerun the live extraction findings or execute a CCMP model sweep. It also judges steps by exit status, can skip Paper 2 when its directory is absent, and does not by itself enforce all manuscript numerical claims. Its hardcoded test-count labels can become stale. Report validation, empirical reproduction and result matching separately.

## Next action

Retain the corrected pilot evidence. Replace implemented/prevented/proved/solved language with accurate implemented-versus-proposed distinctions; correct prior-art contrasts and table counts; then freeze a small empirical extension with A0 and history ablations if those become central claims. The immediate gain is claim discipline, not more theoretical terminology. This audit does not authorize a new model sweep or communication to Agy.
