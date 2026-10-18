# Research execution handoff: Codex + Antigravity
Status: PRE-EXECUTION RESEARCH PLAN. No new model runs or paper claims are authorized by this document.
Baseline: 8311db485e6ab4d7b304290aef090abce3ca8fc1

## Research priorities
1. **Decision Fidelity** (first): static-source memory compression. Does a memory representation preserve decision-critical scope, negation, units, ordering, prerequisites and rationale, without excessive refusals?
2. **CCMP-Bench** (second): corrections to authoritative source facts, invalidation of stale plans and downstream actionable memory.
3. **GMS systems paper** (third): consumer-hardware memory retrieval, abstention and safe consolidation, benchmarked independently of its own regression suite.

### Ground rules
- Keep production tools/, desktop/, services and private ~/memories out of research experiments. Use synthetic public fixtures only.
- Separate engineering checks from model-based evidence; a 96/96 offline suite is NOT 96 independent behavioral experiments.
- Never send any synthetic or real infrastructure action to live infrastructure; simulators only.
- Record raw requests/responses, model configuration, source/schedule/code SHA, actual latency and tokens, parse and admission outcomes, safety or backend failures, and simulator outcomes.
- Do not silently retry frozen trials, repair incomplete JSON, omit failures, or count partial runs as full experiments.
- Do not modify the original frozen 72-call pilot schedule. New arms and preregistration require a new manifest/version.
- All external model endpoints, model downloads, cloud processing and production configuration changes require separate approval.

## Gate 0 — Codex: implementation verification
Read, in order:
- research_harness/decision_fidelity/docs/FROZEN_PILOT_PROPOSAL.md
- research_harness/decision_fidelity/docs/frozen_schedule.json
- research_harness/decision_fidelity/corpus.py
- research_harness/decision_fidelity/representations/arm_c_ordinary_structured.py
- research_harness/decision_fidelity/representations/arm_d_source_bound.py
- research_harness/decision_fidelity/evaluator/evaluator.py
- research_harness/decision_fidelity/evaluator/reader.py
- research_harness/decision_fidelity/simulators/domain_simulators.py

Run offline tests, then test the end-to-end model path using fake/mocked Ollama responses. Confirm:
1. Exactly 72 planned calls: 12 scenarios, 2 writers and 4 readers each; frozen model qwen3:8b, think=false, seed 1742, temperature=0, context 8192, completion 2048, timeout 90s.
2. Writers C/D access *public source text only*. Readers see only the intended representation and task. Hidden gold actions and constraints must never enter prompts or writer-side validations.
3. Writer JSON actually feeds reader context: no fallback to rule-based heuristic or gold-derived representation if writer output is invalid.
4. Arm D admitted payload is derived from the model's JSON, not separately from the source. Reject absent/invalid citations, false entailment, broadened scope, inverted negations, number/unit errors and hallucinated rationale.
5. Validate nested action objects, wrong parameters, absent required steps, and legitimate vs excessive refusals using the independent hermetic simulator.
6. Collect actual prompt/completion usage for BOTH writer and reader, not just approximated carrier tokens.
7. On timeout, parse failure or unexpected model telemetry, fail closed. Preserve failure artifacts. Never claim success from replay/mock runs.
8. Re-check synthetic canaries cannot enter production stores and that tests do not touch the real private memory root.

## Gate 1 — Antigravity: execute initial development pilot
Only after the Codex safety review, run the *unchanged* 72-call local frozen pilot with exactly the preregistered model/settings. Report all 12 cases and four arms, including failed admissions, premature abstentions and malformed/timeout outputs. Mark this as an **authored development pilot**, not held-out evidence.

For initial descriptive analysis, the unit is six independent source *families*, not twelve independent minimal-pair examples or 72 independent model calls. Report matched family means, paired differences and uncertainty; do not claim 5-percentage-point non-inferiority from six families.

## Gate 2 — discriminating experiments, in order
DF1 — **Matched-schema admission ablation**: C (plain KV); D0 (typed constraints, same writer prompt/schema as D1, no source-bound guard); D1 (identical typed writer + deterministic source binding); D2 (same writer + separately validated semantic entailment). D0 vs D1 estimates incremental gate effect; C vs D0 estimates schema/prompt effect. Measure wrong actions, legitimate refusals, *excessive* refusals, and admission yield.

DF2 — **Cost/quality baselines**: A full-authoritative re-read; B BM25 sentence excerpts; B2 budget-matched extractive snippets; B3 task-agnostic cached excerpt; optionally current-source-only. Keep access to correction/current source equal when relevant. Include compilation, indexing, writer, retrieval, reading and inference costs. Evaluate reuse horizon K = 1, 5, 20. Prompt token reductions alone do not establish total cost savings.

DF3 — **Held-out generalization**: Independently author >=40 additional source families, separate from 12 existing development families. Stratify across all six constraint categories, source lengths, distractors, multi-clause negations, scope, units, order, rationale and legitimate abstention tasks. Split at FAMILY level before tuning; hold out >=32 families for final evaluation and use <=8 for new development. Include blinded second reviewer and dispute log. Hash sources, tasks, gold actions and rubric.

DF4 — **Model robustness**: >=2 different local models and >=3 seeds per held-out family/arm. Report prompt/runtime context and model digest, quantization, token cap, think mode and cold/warm timings. Do not pool thinking-enabled and disabled experiments without a prespecified plan.

DF5 — **Evaluator adversarial audit**: Enumerate false accept AND false reject tests for nested keys, 4 vs 4096, ms vs s, absent steps, before/after, true negation scope, forged verbatim spans, entailed vs unsupported rationale. Use human audit for semantic-judgment labels. SHA integrity cannot establish semantic correctness.

DF6 — **CCMP independent replication**: External implementation currently sits outside this repo under projects/learning/agent_memory/_research/ccmp_recovery. Package a pinned, independently downloadable release or submodule with checksum; test a clean checkout. Add A0 current-source reread, fair full reset retaining unchanged controls and equal information access. Run genuinely independent held-out episodes with 3-step trajectories, accurately categorize halts/censoring, paired episode-level inference and true token rebuild costs.

DF7 — **Paper 1 revalidation**: Run independent unseen retrieval queries; compare BM25, vector, true cross-encoder (explicitly distinguish fallback), RRF and no-memory. Report cold/warm p50/p95/p99, hardware, dataset construction and raw/test leakage. Replace keyword proxy F1 with blind semantic annotation and complete subject-predicate-object one-to-one graph scoring. Observe raw candidates -> admitted -> persisted -> indexed -> retrieved canary records separately.

## Gate 3 — statistical and publication acceptance
- Primary DF estimand: paired per-family correctness difference D1 minus C on *held-out* sources, not a count of generated calls.
- Primary estimand, multiplicity family, alpha, missingness policy, failure inclusion, effect-size uncertainty and family clustering must be frozen before confirmatory experiments.
- A 5pp NON-INFERIORITY margin is NOT equivalence: equivalence needs both one-sided conditions. Null p > .05 never proves parity; use adequately powered confidence-interval/equivalence methods.
- Do not claim "calibration" without a calibration target, "100% safe" from canary filters, or "first" without exhaustive supporting related work.
- Null or negative results are valuable if the intervention and evaluation are fair.

## Agent branch/workflow contract
Codex: separate branch research/codex-* for code/audit fixes. Antigravity: research/antigravity-* for corpus/run/report. One PR per experiment group, no overwrite of colleagues' work; preserve original frozen manifests. Put run outputs in reports/ with explicit filenames and checksum manifest; inspect for secrets before committing any artifact.

## Final report for independent inspection
Provide:
- Base and head SHA, PR and changed files
- Model digest/backend, hardware, seed, options, frozen schedule/source SHA
- Commands, exit codes, per-suite test totals and raw failure logs
- Number of *independent* family/episode clusters, completed/halted cases and calls
- Per-arm outcomes, wrong-action vs excessive refusal breakdown, paired intervals
- Full writer+reader token costs and wall times, including amortization
- Adversarial false positive/negative results and blind adjudication notes
- Surviving weaknesses, supported findings, inconclusive hypotheses, negative results
- Paths to JSONL traces, simulation audits, summary JSON and claim ledger

The next round of ChatGPT review should use the finished commits and exact run artifacts, not summaries alone.
