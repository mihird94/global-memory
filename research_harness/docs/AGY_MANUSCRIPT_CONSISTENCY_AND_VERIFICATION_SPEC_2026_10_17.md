# Agy handoff: manuscript consistency and verification integrity

Status: authorized editorial and offline verification work. No new model inference, cloud extraction, live memory changes, deployment, publication, or Git commits.

## Objective

Close the remaining contradictions in the two manuscripts, companion report and reproduction runner. Preserve the accepted methodological repairs and all historical evidence. Deliver consistent, reviewable claims grounded in the existing artifacts.

Do not add new architectural features, theoretical results, benchmark arms, or literature positioning during this pass.

## Inputs

- Paper 1: `/Users/mihirdeshpande/.gemini/antigravity/brain/b1cbfee1-d259-44d2-bda8-3319f7367cd3/paper_1_gms_two_speed_memory_manuscript.md`
- Paper 2: `/Users/mihirdeshpande/.gemini/antigravity/brain/b1cbfee1-d259-44d2-bda8-3319f7367cd3/paper_2_ccmp_correction_propagation_manuscript.md`
- Companion report: `/Users/mihirdeshpande/Downloads/GMS_SYSTEM_AND_BENCHMARKS_REPORT_2026.md`
- Reproduction runner: `/Users/mihirdeshpande/.gemini/antigravity/brain/b1cbfee1-d259-44d2-bda8-3319f7367cd3/reproduce_papers.py`
- Latest audit: `/Users/mihirdeshpande/projects/global-memory/research_harness/docs/MANUSCRIPT_RECONCILIATION_CHECK_2026_10_17.md`
- Prior claim audit: `/Users/mihirdeshpande/projects/global-memory/research_harness/docs/LATEST_MANUSCRIPT_CLAIM_AUDIT_2026_10_17.md`
- Partial pilot: `/Users/mihirdeshpande/projects/global-memory/research_harness/reports/harvest_pilot_20261017_v1/`

The external CCMP package is a read-only verification target in this pass. Do not change its implementation or protocol to make claims pass.

## 1. Reconcile claims throughout all three documents

Review abstracts, introductions, contributions, diagrams, captions, conclusions and reproduction appendices—not only the sections previously edited. Classify every substantive claim as implemented behavior, observed result, conditional model, hypothesis, or proposed extension.

### Required corrections

**Thinking-mode result.** Replace Paper 1's abstract claim that default thinking guarantees JSON truncation with wording equivalent to:

> In one Qwen3:8b fixture under a 1,536-token completion cap, thinking-enabled generation exhausted the budget without a visible response; disabling thinking produced parseable output. This is a configuration-specific observation, not a universal necessity or sufficiency result.

Retain the conditional token-budget calculation, including its assumptions. Do not imply that the inequality establishes zero visible characters in every over-budget case. Do not generalize the specific intervention to Qwen3.5:9b.

**Authorization boundary.** Replace broad prevention claims in the abstract and introduction with wording equivalent to:

> For resume/procedure intents, the heuristic withholds actionability when every relevant focus item requires corroboration. Mixed verified/unverified packets remain a limitation; this is not a claim-level authorization reference monitor or demonstrated end-to-end defense against authorization laundering.

Do not imply that an `accepted` label alone proves source-event authorization or independent corroboration. Retain the direct mixed-authority counterexample as a limitation.

**PACMI characterization.** Use the same accurate distinction in both papers and the companion report: significant primary final-answer comparison against the strongest baseline; nonsignificant result for the particular cascading-removal ablation. Avoid framing the use of exact tests alone as empirical superiority of CCMP.

**Timing populations.** Separate the 142-case regression suite from the45-query ablation. The2.38ms hybrid and8.22ms reranked medians belong to the referenced45-query ablation. Derive suite-specific timing claims from the corresponding suite report. Do not average medians or invent an aggregate latency from suite aggregates; use per-query raw timings if an aggregate is needed. Include report identity, availability, warm/cold scope and units for every latency table.

### Preserve these established qualifications

-142 cases comprise31 canonical cases plus111 correlated variants; these are authored adapters, not official public dataset executions.
- Dense ablation vectors are synthetic fixture representations, not an evaluation of an embedding model's general quality.
- Tiered regex/LLM routing and A0 raw rereading remain proposed extensions, not deployed or registered features.
- The amortization formula is conditional, requires positive per-use savings and equal-quality assumptions, and does not prove measured full-reset superiority.
- Turn-index patterns do not identify causal mechanisms without controlled history/carrier interventions.
- The storage audit is a simplified surrogate, with duplicated representations separated from unique records.
- The saved gold run has one admitted/persisted non-secret noise record; do not claim zero total prohibited-content leakage.
- The new pilot stopped `FAILED_BACKEND`: six of eight calls attempted; coder zero of two parseable, Qwen3 four of four parseable; two coder cases unattempted. Preserve unknown timeout usage and avoid a completed paired superiority claim.
- No live graph extraction ran in the older saved gold run; deterministic graph controls are separate evidence.

Use the existing primary-source citations and exact section/table references. No additional literature survey is required.

## 2. Create an evidence-linked claim ledger

Write `/Users/mihirdeshpande/projects/global-memory/research_harness/docs/MANUSCRIPT_CLAIM_LEDGER_2026_10_17.md` with one row per major numerical, security, implementation and theoretical claim.

Required columns: claim ID; concise claim; classification; document locations; evidence path and field or source section; population/denominator; limitation; verification outcome.

Keep historical and current runs separate. Mark unknown measurements unknown. Do not fabricate missing environment metadata or retrofit raw evidence from summaries. Keep preexisting evidence bundles unchanged.

## 3. Make offline verification fail honestly

Update `reproduce_papers.py` so it clearly distinguishes:

1. Offline tests and fixture execution.
2. Integrity/result reconciliation against saved empirical artifacts.
3. New inference reproduction, which is disabled and out of scope for this handoff.

### Required runner behavior

- Use the selected project Python consistently, including CCMP. Record executable, version and relevant package availability. A virtualenv path alone is not a dependency/version pin; avoid claiming a pinned environment without recorded dependency identities.
- Require the explicit CCMP path for full two-paper verification. If missing, return nonzero with `INCOMPLETE` rather than an all-pass summary. An explicitly selected single-paper mode may omit the other paper but must label its narrower scope.
- Add bounded subprocess timeouts and report failure, timeout, unavailable dependency and missing artifact separately.
- Parse structured retrieval results and require every expected strategy to have actually executed. An unavailable reranker must not receive a reranking verification pass through fallback results.
- Validate exact schedule/suite denominators against frozen inputs; derive displayed test counts from actual test output, not hardcoded labels.
- Check claimed saved metrics against their precise saved JSON fields. Do not require fresh timing measurements to equal historical timing constants.
- Treat the partial pilot's `FAILED_BACKEND` as an honestly recorded empirical failure. It can pass artifact-integrity verification while empirical completion remains `PARTIAL`; never collapse these into one green efficacy label.
- Emit machine-readable step results and a final summary containing scope, statuses, observed counts, evidence paths and command identities. Maintain a readable console summary.
- Default execution must not dispatch LLM inference, ingest private memory, download models, or modify stored memories. Run test fixtures in isolated roots. Do not auto-enable existing `--live-ollama` behavior in this handoff.

Prefer calling existing functions and parsing their structured results over brittle console-text matching. Do not create a second implementation of the research scoring logic.

## 4. Focused negative controls

Add offline tests proving the runner cannot report full verification success when:

1. The CCMP directory is absent in full two-paper mode.
2. A requested retrieval method reports `available=false`, including a successful fallback output.
3. A saved numerical claim or denominator is inconsistent with its report.
4. A child process times out or exits nonzero.
5. A saved bundle is partial or has a checksum mismatch.

Positive control: a valid partial pilot passes integrity reconciliation and remains explicitly partial. Another positive control must demonstrate that varying fresh latency does not invalidate an accurately attributed historical result.

Use injected subprocess results and temporary artifact copies. Do not mutate the original evidence or invoke a real model for these tests.

## 5. Deliverables and acceptance

Deliver revised manuscripts and companion report, the claim ledger, updated reproduction runner, focused tests, and a saved machine-readable offline verification report. Preserve unrelated working-tree changes. Do not send messages or start another agent.

Acceptance requires:

- No abstract/introduction/conclusion contradicts the scoped body claims.
- Every major quantitative claim maps to a named artifact, field and denominator.
- Implemented/proposed and observed/hypothesized distinctions remain explicit.
- Negative controls fail for the intended reasons.
- Existing relevant harvesting/research/CCMP tests pass, with counts obtained from actual execution.
- No new inference, private-memory processing, commit, deployment or publication occurred.

Use verdict `EDITORIAL_AND_OFFLINE_RECONCILIATION_COMPLETE` only if all of the above pass. This verdict is not empirical efficacy acceptance, independent generalization, or submission readiness. Report unresolved findings plainly rather than declaring all papers scientifically complete.

## Ready-to-paste instruction

Implement this specification as a bounded editorial and offline-verification pass. Read the latest reconciliation audit first, fix contradictions across all document sections, build the evidence-linked claim ledger, and harden the reproduction runner with focused negative controls. Preserve all historical evidence and unrelated edits. Run no models and touch no live memory. Return precise changed paths, observed test counts, machine-readable verification results and remaining limitations; do not claim publication readiness.
