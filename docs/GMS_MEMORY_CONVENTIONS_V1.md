# GMS Memory Conventions v1

## Purpose

GMS is a context-engineering system, not a scrapbook of facts. Its job is to help a future agent recover the smallest trustworthy context needed to act correctly.

The system therefore separates evidence, interpretation, accepted memory, and task state. AI-generated summaries are proposals until their authority and evidence support promotion.

## 1. Memory lifecycle

Every durable item moves through explicit stages:

```text
source event → extracted candidate → validation → audited system decision → active/contested
             → active memory → superseded/expired/archive
```

- Source events are immutable evidence: conversations, files, commands, tests, user instructions, and system observations.
- Candidates are AI or deterministic interpretations of evidence. They are not active truth.
- Active memories are reviewed or deterministically verified records usable in context packets.
- Supersession preserves history. Never silently overwrite a durable decision.
- Archive/expiry removes an item from normal retrieval without destroying its audit history.

## 2. Authority classes

Use one explicit authority value:

- `user_instruction`: Mihir directly stated a preference, constraint, decision, or correction.
- `verified_system_output`: reproduced command, test, API, database, or file observation.
- `source_document`: faithful extraction from an identified authoritative document.
- `llm_inference`: model interpretation, synthesis, hypothesis, or suggested relationship.
- `imported_legacy`: prior memory whose evidence or authorship is incomplete.

Authority is not confidence. It describes why a record may be believed and which promotion rule applies.

Promotion rules:

- The default is system-decides, owner-may-contest: source-present, schema-valid records may be promoted by the registered system curator with an append-only rationale and rollback linkage.
- Current authenticated owner instructions outrank older harvested policies. Missing sources, malformed records, destructive permissions, and unresolved conflicts fail closed.
- LLM-origin decisions and policies remain explicitly attributed to inference. They may become contestable active memory, but never impersonate the owner; integrity warnings remain visible and lower their retrieval authority.
- Imported legacy records remain reviewable and must not be labeled verified without evidence.

## 3. Canonical record content

Every active record must answer:

1. What is asserted?
2. Why is it relevant or true?
3. Where and when does it apply?
4. What should another agent do differently?
5. What evidence supports it?
6. Has it been reviewed, disputed, superseded, or scheduled for re-check?

Minimum common fields:

```json
{
  "schema_version": "gms-context-record-v1",
  "record_type": "decision|policy|fact|procedure|project_state|observation|question|lesson_candidate",
  "key": "project.domain.subject.attribute",
  "statement": "Concise standalone assertion",
  "scope": {"project": "...", "workstream": "...", "applies_to": ["..."]},
  "provenance": {"extractor": "...", "source_refs": ["..."], "extracted_at": "..."},
  "evidence": [{"ref": "path#Lx-Ly", "excerpt_hash": "sha256:..."}],
  "freshness": {"effective_at": "...", "review_after": null, "supersedes": []},
  "review": {"status": "proposed|accepted|rejected|deferred|superseded", "requires_human": true}
}
```

Decisions and policies additionally require substantive `rationale` and actionable `implications`. Procedures require trigger, ordered steps, success criteria, failure handling, and last verified environment. Project state requires goal, current truth, progress, remaining work, blockers, evidence, and next action.

## 4. Naming conventions

- Canonical keys use lowercase dotted namespaces: `global_memory.scheduler.dream_cycle.time`.
- Do not mix underscore and dotted aliases for the same concept.
- First segment is the owning project or durable domain.
- Use stable subject names; values carry changing state.
- Dates belong in values/provenance unless the date identifies an immutable event.
- Store aliases separately and resolve them to one canonical key.
- A collision such as `alphaos.swing.plugin_version` versus `alphaos_swing_plugin_version` must produce a merge candidate, not two active facts.

## 5. Evidence conventions

- Cite a real path plus stable heading, line range, record ID, command digest, or API request identifier.
- Hash the normalized cited excerpt—not the entire file—unless the entire file is the evidence.
- Record observation time separately from event/effective time.
- Preserve the exact command/test and exit status for verified system output.
- A missing source, anchor, or hash match downgrades the record to `unverified`; it must not be silently repaired by an LLM.
- Inference must be labeled as inference and linked to the evidence used to derive it.

## 6. Human-authored versus AI-curated memory

Human-authored memory and AI-curated memory may share storage but must remain distinguishable.

- `observed_agents` is attribution, never authority.
- `extractor` identifies who transformed evidence; it does not claim authorship of the underlying decision.
- `reviewed_by` identifies the approving identity and requires an append-only rationale-bearing audit event.
- The UI must visibly label `User stated`, `System verified`, `Document extracted`, `AI inferred`, or `Legacy imported`.
- AI may propose links, tags, summaries, questions, and merge/supersession candidates. It may not fabricate rationale or impersonate Mihir.

## 7. Consolidation operations

Nightly consolidation chooses one explicit operation per candidate:

- `add`: new independent information.
- `reinforce`: same assertion with additional evidence; preserve both evidence references.
- `merge`: combine complementary records without losing unique provenance.
- `supersede`: replace time-sensitive truth while retaining the prior version.
- `contradict`: preserve competing claims and route to review.
- `noop`: duplicate, trivial, or non-durable content.
- `archive`: no longer normally relevant, with rationale and restoration path.

Similarity alone never authorizes merging. Compare scope, effective time, polarity, authority, and entity identity first.

## 8. Retrieval and context assembly

Retrieval is a plan, not one vector search:

1. Resolve project, entities, time window, and task intent.
2. Retrieve lexical exact matches, semantic candidates, graph neighbors, recent episodes, active decisions, procedures, and unresolved conflicts.
3. Apply authority, freshness, scope, and supersession filters.
4. Diversify results so one repetitive source cannot dominate.
5. Return compact context with inclusion reasons and citations.
6. Include contradictions and unanswered questions when they could change the action.

Context packets should prioritize:

```text
current task/checkpoint
→ active project decisions and constraints
→ relevant procedures
→ fresh verified facts
→ unresolved conflicts/questions
→ recent episodes
→ broader related graph context
```

Never treat embedding similarity as truth. Never hide a newer contradiction because an older record ranks higher semantically.

## 9. Freshness and forgetting

- Use domain-specific review horizons, not one global decay score.
- Permanent policies still require review when their source or scope changes.
- Operational facts should carry explicit expiry or revalidation conditions.
- A stale record remains inspectable but is excluded from default actionable context.
- Prefer archive/supersede over deletion. Delete only confirmed pollution, secrets, or user-requested removals, with an audit record where safe.

## 10. Learning from agent work

Store task-scoped outcomes rather than global agent reputation.

- Capture goal, approach, commands/tests, changed artifacts, result, failure mode, and next step.
- Convert repeated successful patterns into procedure candidates.
- Convert repeated failures into lesson candidates with triggering conditions and countermeasures.
- Promote a lesson only after evidence from a concrete failure/correction; do not infer universal rules from one ambiguous episode.
- Measure usefulness by downstream task success, retrieval relevance, contradiction resolution, and context compression—not memory volume.

## 11. Evaluation gates

Continuously test:

- temporal questions (what was true then versus now);
- contradiction and supersession handling;
- multi-hop project/entity retrieval;
- preference and policy faithfulness;
- source citation validity;
- irrelevant-memory resistance;
- context packet token efficiency;
- resumption success for another agent;
- zero durable mutation in preview/test paths.

Evaluate LLM harvesters on their generated outputs. Static fixtures validate schemas only and must never be reported as model-quality results.

## 12. Current migration policy

The current flat fact store remains readable for compatibility. New durable decisions and policies must use structured records. Existing flat records should be migrated incrementally by importance:

1. user preferences and safety constraints;
2. active project decisions;
3. operational procedures;
4. volatile system facts;
5. archival trivia only when it proves useful.

Do not bulk-convert all flat facts with invented rationale. Stage evidence-linked candidates and review high-impact records first.

## Research basis

- A-MEM motivates dynamic note attributes, linking, and memory evolution rather than isolated fact storage: https://arxiv.org/abs/2502.12110
- Mem0 motivates explicit extraction, consolidation, graph representation, and evaluation across temporal and multi-hop questions: https://arxiv.org/abs/2504.19413
- AgeMem motivates exposing store/retrieve/update/summarize/discard as explicit memory operations rather than hidden heuristics: https://arxiv.org/abs/2601.01885

These ideas are adapted to GMS’s local-first and human-review boundaries; paper results are not treated as proof that a technique improves this system without local evaluation.
