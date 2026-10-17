# Agy handoff: decision fidelity of agent memory

Status: begin offline study design, implementation and validation. Return for review before new model inference. This is a candidate replacement for the broad GMS systems manuscript, not a declaration of novelty or a completed paper.

## Research question

When an unchanged authoritative source is compressed into memory, does that memory preserve the constraints needed to make correct downstream decisions?

Test whether apparently relevant, schema-valid memories omit or invent scope, exceptions, units, ordering, prerequisites or causal rationale—and whether those changes alter executable decisions. Evaluate a simple source-bound representation against strong baselines. A null result is valid.

### Boundary from Paper 2

- This study: source truth stays fixed; measure distortion during initial memory construction and subsequent use.
- CCMP: source truth changes; measure downstream correction propagation and recovery.

Do not insert corrections or revocations into this study to manufacture overlap with CCMP. Reusing simulator infrastructure is acceptable; independently define sources, tasks, labels and outcome contracts. Do not reuse the same evaluation episodes across both papers as independent evidence.

## Working hypothesis, not conclusion

Ordinary structured memory may preserve topical content while altering decision-relevant constraints. Binding constraint fields to source support may reduce wrong actions, provided it does not cause excessive omission, refusal or token overhead.

Do not assume the proposed representation wins. Full source or simple extractive memory may dominate it.

## Stage 1 — Prior-art and claim boundary

Read primary sources and produce a concise comparison matrix before claiming novelty:

- HaluMem: https://arxiv.org/abs/2511.03506
- Memory Provenance Laundering: https://arxiv.org/abs/2607.29167
- Endogenous Authorization Laundering: https://arxiv.org/abs/2609.01836
- MemTxn: https://arxiv.org/abs/2607.27834
- When Evidence Changes: https://arxiv.org/abs/2610.03902

Locate exact sections on extraction hallucination, constraint preservation, action evaluation and source-grounded writes. Distinguish our proposed executable decision endpoint from existing operation-level extraction metrics. Record overlap and unresolved novelty questions honestly. Do not claim first, comprehensive or state of the art.

## Stage 2 — Independent research package

Create `/Users/mihirdeshpande/projects/global-memory/research_harness/decision_fidelity/` with its own protocol, sources, annotations, adapters, simulators, evaluator, audit and tests. Keep outputs under `research_harness/reports/decision_fidelity/`.

Dependencies flow from research into product interfaces only. Do not change production retrieval, schemas, curation defaults or memory contents to improve research results. Do not read private memories or load external CCMP evidence as study input.

Preserve all prior manuscripts, partial pilots and unrelated working-tree edits. No commits, deployment, publication, model downloads or Agy-to-other-agent messaging are authorized by this handoff.

## Stage 3 — Source/task corpus and gold contract

Build a small, independently inspectable development corpus first: at least 12 source families spanning these six constraint types:

1. Applicability scope: project, tenant, actor, environment or resource.
2. Exceptions and negation: explicit exceptions, rejected alternatives, conditional permission.
3. Quantities and units: duration, size, thresholds and conversions.
4. Ordered procedures and failure handling.
5. Required versus optional prerequisites: including unsupported extra requirements.
6. Rationale attribution: explicit reason, absent reason and multiple distinct reasons.

For each source family, author a minimal pair that changes one decision-relevant detail and therefore changes at least one gold decision. Keep the rest of the source/task as constant as possible. Variants from one family are correlated; family, not individual paraphrase, is the statistical unit.

Use fictional services and synthetic data. No real credentials; secret-format canaries, if included, must be clearly synthetic and are diagnostic rather than the main endpoint. Sources should vary naturally; do not make the proposed representation's schema the only way to express correct information.

Each family must include:

- Immutable source text with stable span IDs and digest.
- Explicit authoritative facts/constraints, their scope and support spans.
- Public downstream task and all necessary public environment documentation.
- A gold action outcome or set of valid outcomes, including allowed abstention only when actually warranted.
- At least one valid alternative action/serialization.
- Wrong-action, excessive-refusal and omitted-required-action counterexamples.
- Counterfactual source variants and irrelevant wording changes that should or should not alter the gold decision, respectively. These are separate fixed-source episodes, never mid-episode updates.

Keep public source text, hidden labels and reference solutions separate. Memory writers get source text and public instructions; readers get the selected representation, task and identical public action schema/environment access. Neither gets hidden gold fields.

Use executable outcomes where source meaning changes what must happen: permitted resource operations, exact configuration effects, scheduler durations, ordered recovery steps and exception handling. Do not treat substring presence, schema validity or a state hash alone as semantic correctness.

### Rationale-specific caution

Do not turn a reason into an execution prerequisite unless the source states that relationship. Measure unsupported rationale separately. A rationale change only counts as a decision error when a defined downstream decision actually depends on it. Do not invent a rationale-sensitive task merely to penalize harmless paraphrase.

### Generalization boundary

The initial authored corpus is development evidence. Do not call it a blind holdout. Specify an independently authored or independently reviewed held-out set for a later stage, split by source family/template before any model outputs. Do not tune prompts, matching rules or thresholds on that held-out set.

## Stage 4 — Four representations

Implement these arms behind the same reader-facing interface:

| Arm | Representation | Purpose |
| --- | --- | --- |
| A | Full authoritative source | Reference baseline; not automatically an oracle for a model reader |
| B | Extractive source excerpts | Strong simple compression baseline |
| C | Ordinary structured LLM memory | Current-style consolidation baseline |
| D | Source-bound constraint memory | Proposed intervention |

For D, define fields for statement/action, applicability, conditions/exceptions, numeric value/unit, ordering, prerequisites and rationale where relevant. Every nonempty asserted field must cite a specific supporting span; unspecified fields stay null/absent. Preserve source authority as metadata supplied by the harness rather than inferred by the writer.

Separate span existence from entailment: a quoted source span can exist yet fail to support the generated field. Require explicit support validation and evaluation. Do not infer correctness from a hash, citation, validator label or matching keywords.

Freeze how B selects excerpts. Report an implementable extractor as the main baseline; an oracle extractor using hidden labels may appear only as a labeled diagnostic upper bound.

### Fair budgets

Give every writer access to the same complete source, and every reader identical tasks and public tool interfaces. Readers cannot secretly reread the full source in compressed arms. If a source lookup tool is provided, provide it equally and count all calls/tokens.

Report two explicitly distinct conditions if needed:

- Equal reader context budgets, using sources that fit the full-source condition; no hidden source truncation.
- Compression-cost curves across predefined budgets, with truncation and omissions recorded.

Count source ingestion, extraction, validation, lookup, reader generation and retries in total cost. Do not compare compressed prompt cost against a baseline that unnecessarily pays repeated preprocessing or excludes caching by assumption. Do not let deterministic validation invisibly provide missing answers to one arm.

## Stage 5 — Evaluator and failure localization

Record the entire chain:

`source → raw writer output → admitted representation → reader request → raw reader output → parsed action → simulator effect → independent outcome`.

Report separately:

- Unsupported additions and omitted/altered constraints, by type.
- Decision/action correctness against the source contract.
- Wrong actions, unnecessary refusals, missing required actions and legitimate abstentions.
- Raw versus admitted memory quality and admission rejection rate.
- Token/latency cost and context size, with actual versus unknown usage distinguished.
- Writer failures, reader failures, evaluator errors and unattempted cases.

Use the same reader across representations within a primary comparison. A later crossed writer×reader experiment may test portability, but is not required for this first implementation. Keep thinking settings, temperature, seeds and model identity explicit.

Add controlled memory mutations before any inference: remove an exception, widen scope, change units, swap procedure order, insert a prerequisite, fabricate a reason. Check whether each mutation changes the appropriate downstream outcome. Include harmless paraphrases and equivalent unit conversions that must remain correct.

Use human adjudication or an independently reviewed support contract for semantic judgments that cannot be implemented soundly. Do not silently substitute keyword F1 or a self-grading writer. Record disagreements and ambiguous cases.

## Stage 6 — Offline verification and frozen pilot proposal

Validate without calling a model:

1. Gold source/actions pass every simulator; independently valid alternatives pass.
2. Targeted mutations fail for the intended reason; irrelevant changes do not fail.
3. Empty/all-refusal memory does not win by avoiding wrong actions: task completion and false refusals remain visible.
4. Every arm uses the correct public inputs; hidden labels do not enter writer/reader prompts.
5. Mixed-source scope and rejected-alternative controls distinguish assertion from quotation.
6. Raw responses are preserved before parsing; malformed output remains an observed failure.
7. Missing cases, partial trajectories and failed calls cannot inflate denominators or create all-pass reports.
8. Rehashed fabricated outcomes are rejected through independent replay rather than hashes alone.
9. Network is denied in tests; no live memory path or real provider can be reached through a fallback.

Freeze a pilot proposal containing exact cases, prompts, representation schemas, model choices, schedule, resource limits, admission behavior and analysis. Capture source/code/dependency identities and raw-evidence layout. Define one primary decision-fidelity contrast and paired source-family analysis; do not optimize a composite score or claim equivalence from nonsignificance.

Use the previous local partial pilot as a resource warning, not as evaluation data: `qwen2.5-coder:7b` produced truncated JSON and a timeout, while thinking-disabled `qwen3:8b` was parseable on four cases but added unsupported rationale. Propose a bounded local model/configuration only after this warning is reflected in timeout/output-budget design. Do not launch inference in this stage.

## Review checkpoint and go/no-go criteria

Return the offline package, prior-art matrix, casebook/gold contracts, arm definitions, mutation matrix, tests, frozen pilot protocol and unresolved assumptions for Codex review.

Proceed toward a full study only if:

- The task oracle responds to genuine decision changes, not wording artifacts.
- The source-bound arm adds a testable mechanism beyond existing schemas/citations.
- Simple excerpts and full source are competitive, fairly implemented baselines.
- The study can detect both unsafe over-action and costly under-action.
- Contribution overlap with HaluMem, provenance work and CCMP is explicitly bounded.

If those conditions fail, report that outcome. Do not manufacture a paper by introducing stronger-sounding theory or claiming significance from rehearsal.

## Ready-to-paste Agy prompt

Start the decision-fidelity study described here as a candidate replacement for Paper 1. Build the offline corpus, source-grounded action oracles, four representation interfaces, failure-localization evaluator and adversarial mutation tests. Preserve the distinction from CCMP: sources remain unchanged. Compare against full source and implementable extractive baselines, and do not equate schema/citation validity with semantic support. Produce a frozen bounded local pilot proposal and stop for review before inference. Preserve old evidence and unrelated edits; no private-memory reads, cloud processing, model runs, commits, deployment or publication. Return exact artifact paths, actual offline test results, nearest-prior-art differences and remaining risks.
