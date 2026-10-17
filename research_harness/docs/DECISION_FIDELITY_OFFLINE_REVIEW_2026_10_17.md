# Decision fidelity offline package review

Verdict: **OFFLINE_SCAFFOLD_PRESENT — NOT_READY_FOR_MODEL_PILOT**.

Independent check on 2026-10-17: 92 tests passed. No model inference or production-memory changes. Passing these tests establishes the authored examples' tested behavior; the probes below expose gaps those examples do not cover.

## 1. Hidden annotations enter the proposed intervention and baseline

`ArmCOrdinaryStructured.synthesize_structured_record()` builds its summary from `source.constraints`. Arm D takes typed constraint statements and `support_span_ids` from the same hidden annotations. These are oracle-generated memories, not independent extractions from public raw text. The test that checks absence of the literal strings `gold_canonical_action` and `gold_minimal_pair_action` does not detect this leakage.

Required: introduce a public writer input carrying source text and public metadata only. C and D must consume actual or injected writer outputs; any gold-derived versions must be separate diagnostic upper bounds. Test that changing hidden constraints/answers while holding public text fixed cannot change a writer request or reader payload. B currently sees the downstream task when selecting excerpts; preregister this task-conditioned access and give other arms equivalent access, or freeze task-independent selection consistently.

## 2. “Entailment” validator accepts unsupported scope and statements

Direct offline probe:

```python
text = "This policy applies only to Cedar backups."
record = SourceBoundConstraintRecord(
    source_id="s", source_sha256="x",
    primary_statement="All projects must delete backups",
    applicability_scope="Every project including Harbor",
    span_citations={"applicability_scope": text},
)
record.validate_span_existence(text)  # (True, [])
record.validate_span_entailment()    # (True, []) -- incorrect
```

The implementation checks citation presence for scope, exceptions, ordering, prerequisites and rationale rather than whether the citation supports the value. Primary statement and optional prerequisites lack full support checks; numeric substring matching is not semantic numeric validation. `build_reader_context()` does not enforce these validators as admission gates.

Required: validate every asserted field, including source identity/digest, with explicit limits on what is automatic versus human-adjudicated. Reject or abstain on unsupported/ambiguous fields. Exercise widened scope, removed exceptions, changed polarity, reordered steps, invented prerequisites/reasons, substring-number traps and genuinely equivalent units. Invoke admission in the actual path and preserve raw versus admitted output and rejection evidence. Do not claim a general entailment checker from lexical presence.

## 3. The generic matcher has false accepts and is not a domain-effects oracle

`_matches_action()` compares nested list dictionaries using a conjunction: it rejects only if both `step` and `action` differ. Two direct probes returned True:

```python
_matches_action(
    {"action":"execute", "steps":[{"step":"drain", "timeout_ms":999999}]},
    {"action":"execute", "steps":[{"step":"drain", "timeout_ms":50}]},
)  # True: nested effect parameter ignored

_matches_action(
    {"action":"execute", "steps":[{"step":"drain", "action":"delete_database"}]},
    {"action":"execute", "steps":[{"step":"drain", "action":"drain_traffic"}]},
)  # True: wrong operation accepted
```

The generic simulator then records `last_executed`/`execution_count` after a gold dictionary match. This does not independently model resource scope, numeric effects, prerequisite state or procedure transitions. State hashes cannot repair an unsound outcome oracle.

Required: implement validated typed operations and family-specific state effects/invariants. Gold actions are test inputs, not the runtime specification passed to the executor. Strictly validate all nested action parameters. Accept independent valid alternatives through their effects, not an enumerated list alone. Include the two bypasses and real family-derived variants as negative controls.

## 4. Mutation/paraphrase checks do not test memory-to-action fidelity

The evaluator accepts an externally supplied action, builds a representation, but never requires that a reader derived the action from that representation. It hardcodes `admission_passed=True` and sets raw/admitted memory equal. Mutation sensitivity changes the supplied gold action; paraphrase checks reuse the unchanged gold action. Thus these checks can pass even when the memory content is unused or badly distorted.

Required: label existing checks as action-oracle unit tests. Add separate representation-mutation checks and an injectable reader boundary. Preserve source, raw writer response, admission decisions, actual reader messages, raw reader response, parsed action and independently replayed effect. An offline scripted reader can validate wiring, but cannot supply empirical memory-efficacy findings. Add tests proving action results are not substituted from hidden labels.

## 5. Pilot decision rule is statistically invalid

The proposal says `p > .05` establishes that extractive memory dominates or structured binding is unnecessary. Failure to reject a difference establishes neither equivalence nor dominance.

Required: preregister effect sizes and paired source-family uncertainty. If claiming equivalence/non-inferiority, define a justified margin and a suitable test/interval; otherwise report inconclusive findings as inconclusive. Cost superiority requires observed cost evidence and adequate quality, not just a nonsignificant accuracy difference. Distinguish a practical decision to prefer a simpler baseline under uncertainty from a scientific conclusion that it dominates.

## 6. Execution readiness and prior-art scope are overstated

- The proposal's 72 calls at11s/call uses an unsupported runtime estimate; the recent Qwen3 pilot showed substantially longer calls and the coder timed out. Supply a realistic overall deadline, token reservation, timeout/partial-run handling, context admission, model digest and raw-evidence design before launch. Do not treat estimated char/4 token costs and fixed ingestion offsets as measured cost.
- A Markdown proposal plus data models is not an implemented model adapter/runner. Freeze an executable schedule and hash actual prompts, sources, schemas and code before any inference.
- The prior-art matrix mischaracterizes HaluMem as just QA recall and MemTxn as merely ACID/concurrency. HaluMem explicitly evaluates extraction, updating and QA; MemTxn includes source-supported updates, temporal resolution and complete-state recovery. Correct from primary sources: https://arxiv.org/abs/2511.03506 and https://arxiv.org/abs/2607.27834. Avoid calling the matrix exhaustive or the novelty boundary established.

## Review checkpoint

Preserve this package as a development scaffold and keep inference at zero. Repair the hidden-label boundary, oracle and admission wiring first; revise the statistics and runtime proposal; provide positive and adversarial controls and frozen machine-readable inputs. Return for review after offline fixes. No new model run is needed to demonstrate closure of these concrete defects.
