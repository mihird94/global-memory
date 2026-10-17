# Independent review of the two proposed GMS papers

Review date: 2026-10-17. Scope: both supplied manuscript files, current local implementation, saved retrieval reports, and offline recovery tests. No real model runs, cloud extraction, submission, or changes to the external research package were performed. This is a focused evidence audit, not an exhaustive literature review or venue acceptance prediction.

## Overall decision

The two topics can support distinct papers: (1) an empirical local memory systems study and (2) an executable correction-recovery benchmark. Neither current manuscript is submission-ready. Prioritize the second research question, while retaining the first as a narrower engineering study until extraction measurement is repaired.

Avoid a circular argument: the deployed GMS implementation cannot be the only system evaluated by a benchmark designed around GMS's own interventions. The benchmark needs independently implementable interfaces and comparisons; the systems paper needs independent data and generalization evidence.

## Paper 1 — Two-speed local memory

### Verified progress

The saved `eval_run_20261017_085056.json` reports 142/142 authored regression cases passing, up from 141/142 on October 13. Suite counts and reported suite latency statistics match manuscript Table 2. This is a useful regression repair, with 31 canonical cases and 111 correlated variants. It is not 142 independent experiments or evaluation on the official public datasets.

### Blocking issues

1. **Table 1 combines evidence from different runs without making this clear.** The October 4 ablation contains BM25 NDCG .700, hybrid .821, and reranked .880. The October 17 ablation reports .658, .816, and .816 respectively; importantly, reranking is explicitly unavailable because `flashrank` cannot be imported. Do not credit the fallback row as cross-encoder execution. Freeze one environment and revision, rerun comparisons, and distinguish historical from current results. The October 4 reranked median was 14.53ms, so a blanket sub-10ms claim does not cover that configuration. Tail latency and cold starts must also be reported.
2. **Gold metrics are proxies, not the claimed semantic measurements.** In `tools/eval_model_harvesting.py:evaluate_gold_extraction`, a candidate can match through key regex OR keywords, even without correct semantics. Rationale faithfulness checks keyword presence in rationale OR statement. Report these as automated matching proxies pending independent human adjudication, and distinguish raw-model quality from post-admission quality.
3. **Graph scoring omits the object.** Triple matching checks subject and predicate substrings but does not check the expected object, permits one extracted triple to satisfy multiple targets, and lacks graph precision. A wrong-object relation can receive credit. Require complete normalized subject/predicate/object matching with one-to-one assignment and semantic alternative handling.
4. **“Durable storage leaks” are not storage observations.** The evaluator counts prohibited strings in schema-approved candidate objects; it does not persist and re-read the full storage path. Raw graph leaks are not included in that candidate leak counter. Separate raw candidates, raw graph output, admitted candidates, staged records, accepted records, graph/index exposure, and retrieved output. Use an isolated temporary store to establish durable outcomes. Preserve raw requests, responses, validator decisions, and denominators.
5. **The reasoning-starvation explanation needs an intervention.** The evaluator uses `/api/generate`, a fixed budget, and no explicit thinking setting, while discarding full response telemetry from its result bundle. Empty response or timeout does not by itself demonstrate the precise cause. Compare supported thinking settings, budgets, response schemas, and runtimes; capture response/thinking token counts, termination reason, and parser failures. Do not generalize from three scenarios to all reasoning models or claim priority without a literature review. Official Ollama documentation describes model-specific thinking controls and separate thinking/response fields: https://docs.ollama.com/capabilities/thinking.
6. **Formalization differs from code.** The manuscript describes a three-state gate; code returns supported/conflicted/stale/insufficient and separate abstention guidance. Its overlap logic is not the stated coverage equation. The equation can exceed one and is undefined for zero content tokens. The claimed exponential recency formula does not describe the inspected RRF contribution, which uses boosts. One effective/expiry interval is not a complete bitemporal model: explicitly distinguish valid time from transaction/observation time. Label a proposed abstraction separately from implemented behavior.
7. **Calibration and generalization are not established by repairing a known failed case.** Freeze the repair and test unseen paraphrases, temporal constraints, negation, conflicting evidence, and cases where framing words carry meaning. If calling the gate calibrated, define the calibration target and measure it; otherwise call it a deterministic sufficiency heuristic.
8. **Absolute guarantees exceed the measurements.** Zero leaks on selected patterns is not zero leakage generally. Model unloading does not mean zero process or application RAM. The unload helper returns an empty model list on connection failure, so “verified unloaded” can be inferred from unavailable telemetry. Separate unreachable from verified empty, and report resident-model memory rather than zero background footprint. A regex scanner is pattern-based, not cryptographic. Hashing records establishes integrity, not truth or authenticity.

### More defensible framing

Suggested title: **“Local Agent Memory Under Resource Constraints: Retrieval Sufficiency and Safe Consolidation.”**

Lead with a measured quality/resource tradeoff and a concrete storage-boundary evaluation. Include classical schema-plus-regex and non-LLM extraction baselines, held-out scenarios, repeated runs, and realistic workload scale. Specify hardware, model digests, quantization, runtime versions, and cold/warm conditions. Three scenarios remain a feasibility pilot; 50% rationale-keyword coverage is a weakness to explain, not strong semantic faithfulness.

The split between fast retrieval and offline consolidation is not sufficient novelty by itself. Prior work includes MemGPT's memory tiers (https://arxiv.org/abs/2310.08560) and SCM's offline consolidation architecture (https://arxiv.org/abs/2604.20943). These references establish relevant overlap, not equivalence or comparative quality. Avoid unverified “first” and broad “cloud-centric prior work” claims.

The reproduction appendix must use the pinned project environment and separate the ablation command from the suite command: `run --suite all` does not reproduce Table 1. Label hardware inference requirements and local HTTP explicitly rather than implying dependency-free offline reproduction.

## Paper 2 — CCMP-Bench correction propagation

### Strongest contribution candidate

Measuring whether a corrected source changes subsequent executable actions, including stale carriers and preservation of unrelated controls, is a coherent question. Keeping graph invalidation, carrier refresh, and a fair reset separate is experimentally useful. A negative result is still informative if treatment differences and scoring are valid.

### Blocking issues

1. **The statistical implementation claim is false for the inspected checkout.** `ccmp_recovery/evaluator/contrasts.py` has no McNemar, permutation, or bootstrap implementation. It leaves `p_value=None` and labels positive differences SUPPORTED in empirical mode. Change the text to a proposed analysis or implement and independently test the exact claimed procedures before execution. Missing episodes currently default to zero/false in parts of aggregation; they must be represented as missing/censored.
2. **Claimed 61 tests are not reproduced.** Independent discovery found 30 tests, all passing. Provide the precise revision, test command, and immutable result if 61 refers to a different checkout. A passing test count does not itself establish all manuscript claims.
3. **The API task description contradicts the implementation.** The manuscript says `cursor` is deprecated in favor of `page_token`; the inspected simulator accepts `cursor` and rejects old `page`. Resolve from frozen episode definitions and generate the manuscript task table from those definitions.
4. **“Stateful” must distinguish conversation from environment persistence.** The inspected API simulator initializes a fresh environment inside each action evaluation. That is an action-effect check, not a persistent environment across three opportunities. Either retain environment state and specify transitions or describe sequential conversational opportunities with independent simulator checks. A state digest records state identity; it does not independently establish correctness without a separate target/invariant oracle.
5. **Eight authored episodes establish a harness pilot, not a general benchmark.** Expand across independently authored sources, graph depths, support structures, correction times, stale-carrier types, unchanged controls, and distractors. Split development from held-out tasks and report episode/family clustering. Do not inflate sample size with correlated continuations.
6. **Show the causal pathway for H1.** If graph-only invalidation changes no visible context or retrieval result, no behavioral effect is identifiable. If staleness metadata is visible, declare it as part of treatment. Give all arms identical correction access and retrieval opportunities; record actual inputs and budget rebuilding work fairly.
7. **Predeclare statistical choices and multiplicity.** With eight episode pairs there are only 256 possible sign assignments; exact enumeration is practical. McNemar's two-sided probability needs capping at one and explicit all-tie handling. Define outcomes, randomization/exchangeability assumptions, primary comparisons, ties, censoring, effect-size intervals, and multiple-testing control. Failure to detect a difference does not establish equivalence or efficiency at matched quality.
8. **Do not attribute our harness defects to external benchmarks.** The demonstrated regex and unfair-reset defects arose in this project's earlier versions. The drafts provide no cross-benchmark audit establishing that existing benchmark literature shares these exact flaws. Phrase them as failure modes found during benchmark development unless published implementations are actually audited and cited.
9. **The live sweep is still future work.** The draft correctly avoids policy efficacy numbers, but “ready for execution,” “gaming-resistant standard,” and “first controlled” remain unverified. Preserve readiness and empirical findings as separate claims. No frontier API use on private material is authorized by this review; synthetic public fixtures are a separate execution decision.

### More defensible framing

Suggested title: **“CCMP-Bench: Executable Tests of Correction Propagation in Agent Memory.”**

Use the current eight episodes for a pilot and adversarial evaluator-validation appendix. The main paper needs held-out episodes, repeated real-model runs under explicitly supported settings, confidence intervals at the episode level, simple current-source-only and equal-budget baselines, and enough model/memory-system diversity to test generality. Keep H1/H2/H3 conclusions pending the evidence.

## Recommended next work, in order

1. Freeze code, corpus, evaluator, environment and manuscript evidence references for both papers.
2. Repair the gold evaluator and correction statistical implementation before spending on further inference.
3. Replace unsupported claims with scoped observations; reconcile the latest retrieval ablation and task definitions.
4. Predeclare held-out evaluation and execution budgets; preserve local-only processing for private memory.
5. Run the resulting studies, then select venue and final claims from the observed contribution.

Keep the papers separate only if their main empirical contributions remain distinct: systems/resource and consolidation evidence for Paper 1; correction-recovery measurement and comparative behavioral evidence for Paper 2.
