# Mbrain Pass 5 — Rationale-First Context Harvesting

Status: implementation contract for Antigravity
Date: 2026-09-08
Repository: `/Users/mihirdeshpande/projects/global-memory`
Authoritative skill: `/Users/mihirdeshpande/projects/global-memory/SKILL.md`
Do not commit unless Mihir explicitly requests it.

## 1. Outcome

Turn the operationally working Dream Cycle into a context-engineering pipeline.

The nightly run currently succeeds technically, but it promotes compact one-sentence strings such as:

```text
mbrain_agent_trust_architecture = Global agent trust ... is retired ...
```

That is an observation, not a sufficient durable decision record. A future agent still lacks the original rationale, implications, scope, provenance, evidence, and conditions under which the decision should be revisited.

Pass 5 must ensure that:

1. LLM harvesting produces typed, evidence-linked candidates.
2. Decisions and policies cannot pass validation without rationale and scope.
3. LLM candidates do not silently become canonical project truth.
4. Mbrain provides a useful review experience for accepting, editing, merging, rejecting, or deferring candidates.
5. Context packets prefer authoritative rationale-bearing records over shallow summaries.
6. Global agent trust/reputation no longer controls promotion or nightly behavior.

## 2. Independently verified baseline

Codex verified the following before this specification was written:

- **160/160 tests pass** across 23 suites.
- All desktop JavaScript syntax checks pass.
- `git diff --check` is clean.
- Dream Cycle completed a live run in **51.19 seconds** with exit code `0`.
- Runtime telemetry reported provider `antigravity`, six promoted facts, graph rebuild, and index rebuild.
- The launchd job is installed and loaded.
- Project Context Workspace, deterministic context packets, cross-view search, graph clustering, entity merge, task API parity, SQLite WAL hardening, PPR retrieval, and the synthetic benchmark are present.

### Verified semantic defect

The six promoted facts in `~/memories/semantic/facts.json` are flat strings:

- `gms_durable_policy_format`
- `mbrain_agent_trust_architecture`
- `mbrain_context_packet_engine`
- `global_memory_sqlite_concurrency`
- `retrieval_benchmark_bm25_performance`
- `retrieval_benchmark_harness_path`

They do not satisfy the Global Memory skill's Context Engineering Contract. Some are ordinary technical facts, but the policy/architecture decisions lack first-class rationale, implications, scope, and embedded provenance.

### Verified architectural inconsistency

`tools/dream_cycle.py` still runs global agent reputation calibration through symmetric Dawid–Skene/Beta-style reliability updates. The user-facing trust model was retired because a global agent score collapses domain, task, evidence, recency, and failure severity into false certainty. Keeping it as an unseen promotion control would preserve the same invalid product model behind the UI.

### Verified local-model configuration mismatch

The installed Ollama models are `qwen3:8b` (5.2 GB), `qwen2.5-coder:7b` (4.7 GB), and `qwen3-embedding:0.6b` (639 MB). Current defaults reference missing `qwen3:0.6b` for Dream Cycle fallback, missing `qwen2.5:7b` for concept enrichment, and missing `qwen3.5:9b` for optional synthesis. The successful live run used Antigravity, so it did not verify local reasoning.

### Local-model decision for Pass 5

- Use **`qwen3:8b`** as the canonical local Ollama reasoning model for typed context harvesting, rationale extraction, and concept enrichment.
- Continue using **`qwen3-embedding:0.6b`** exclusively for vector embeddings.
- Continue using `ms-marco-TinyBERT-L-2-v2` as the lazy local FlashRank reranker; it is not generative.
- Keep `qwen2.5-coder:7b` for explicitly selected code work, not context harvesting.
- Unify `DREAM_LLM_MODEL` and `CONCEPT_MODEL` defaults around `qwen3:8b`.
- Validate configured model availability through Ollama before work begins. Missing models must produce a visible unavailable/deferred state, never silent substitution.
- Preserve the one-model-at-a-time rule and send `keep_alive: 0` after every terminal path.

## 3. Non-negotiable product decisions

1. GMS is a context-engineering system, not a status ledger.
2. A durable decision must be understandable when retrieved by itself.
3. Agent identity is provenance, never proof of truth.
4. There is no global agent trust, reliability, reputation, quality, health, or confidence score.
5. Evaluation belongs at the claim/task/evidence level.
6. LLM extraction is proposal generation, not truth creation.
7. No model is loaded by opening Mbrain, Explore, Projects, Review, or Concepts.
8. Dream Cycle must remain bounded, local-first, unload models on all terminal paths, and degrade safely.
9. Existing uncommitted work and icon assets must be preserved.
10. Do not rename `gms_trust.sqlite` in this pass; use a compatibility migration plan rather than a destructive filesystem change.
11. The canonical local reasoning model is `qwen3:8b`; the embedding model is `qwen3-embedding:0.6b`.

## 4. Typed context record model

Introduce a versioned record envelope for harvested semantic candidates.

```json
{
  "schema_version": "gms-context-record-v1",
  "record_type": "decision",
  "key": "mbrain.agent_trust_architecture",
  "statement": "Do not use a global agent trust or reliability score in Mbrain.",
  "rationale": "A single score collapses unrelated dimensions and creates false certainty.",
  "implications": [
    "Show provenance, recency, contributions, disputes, and outcomes separately.",
    "Evaluate claims and tasks rather than agent identity."
  ],
  "scope": {
    "level": "project",
    "project": "global-memory",
    "workstream": "mbrain",
    "applies_to": ["desktop-ui", "dream-cycle", "context-packets"]
  },
  "provenance": {
    "observed_agents": ["Mihir", "Codex"],
    "extractor": "DreamCycle-antigravity",
    "source_refs": ["episodic/history/2026-09-08.md#..."],
    "source_hashes": ["sha256:..."],
    "extracted_at": "ISO-8601",
    "prompt_version": "context-harvest-v1",
    "provider": "antigravity",
    "model": "..."
  },
  "evidence": [
    {"type": "user_instruction", "ref": "...", "excerpt_hash": "sha256:..."}
  ],
  "freshness": {
    "effective_at": "ISO-8601",
    "review_after": null,
    "supersedes": []
  },
  "review": {
    "status": "proposed",
    "requires_human": true,
    "reasons": ["architectural decision extracted by LLM"]
  }
}
```

### 4.1 Record types

Support at least:

- `decision`: chosen direction with rationale and implications.
- `policy`: durable behavioral or safety rule.
- `fact`: externally or mechanically verifiable statement.
- `procedure`: trigger/action/constraints for repeatable work.
- `project_state`: current focus, blocker, milestone, or verified result.
- `observation`: potentially useful statement not yet durable enough for another type.
- `question`: unresolved issue requiring an answer.
- `lesson_candidate`: proposed reusable correction awaiting review.

Do not force every sentence into `fact`. When uncertain, use `observation` and preserve uncertainty explicitly.

### 4.2 Required fields by type

| Type | Required fields |
|---|---|
| decision | statement, rationale, implications, scope, provenance, evidence |
| policy | statement, rationale, scope, provenance, enforcement/behavioral implication |
| fact | statement/value, scope, provenance, at least one evidence reference or deterministic derivation |
| procedure | trigger, action, constraints, scope, provenance |
| project_state | statement, project, effective_at, provenance, verification status |
| observation | statement, provenance, uncertainty/review reason |
| question | question, why_it_matters, scope, provenance |
| lesson_candidate | statement, triggering failure/correction, scope, provenance |

An empty string, placeholder, or generic phrase such as “based on the journal” does not satisfy a required field.

### 4.3 Authority and epistemic status

Store separate fields instead of a score:

- `authority`: user_instruction, verified_system_output, source_document, agent_report, llm_inference.
- `verification`: verified, partially_verified, unverified, contradicted.
- `review_status`: proposed, accepted, edited, merged, rejected, superseded.
- `freshness_status`: fresh, possibly_stale, stale, timeless_until_superseded.

Never combine these into one numeric confidence value.

## 5. Storage and migration

### 5.1 Candidate table

Use a dedicated staging table rather than inserting LLM output directly into active facts:

```sql
CREATE TABLE IF NOT EXISTS gms_context_candidates (
    candidate_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    record_type TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    extractor_agent TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    prompt_version TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'proposed',
    review_rationale TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    merged_claim_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_fingerprint, canonical_key, content_hash)
);
```

Add indexes for review status, record type, canonical key, and creation time.

### 5.2 Run audit

Every nightly run records:

- run ID;
- source hashes and date range;
- providers attempted and failure reasons;
- selected provider/model;
- prompt/schema version;
- candidates proposed, rejected by validation, deduplicated, deferred, accepted automatically by deterministic rule, and awaiting review;
- explicit model unload result;
- graph/index rebuild outcomes;
- duration and terminal state.

Do not report `facts_promoted` when the outputs are only candidates. Use accurate counters.

### 5.3 Existing flat facts

Do not delete the six current values automatically.

Provide a one-time migration command that:

1. reads the source journal passages;
2. creates structured candidates linked to the flat records;
3. marks the originals as `legacy_flat_record` in migration metadata;
4. requires review before replacing decision/policy records;
5. can be re-run idempotently;
6. supports dry-run and produces a machine-readable report.

Ordinary technical facts may remain flat if they are self-contained and have provenance available elsewhere, but decisions and policies may not.

## 6. Harvesting pipeline

Replace the current `dict[str, str]` extraction contract.

### 6.1 Provider output

Providers return:

```json
{
  "schema_version": "gms-context-harvest-v1",
  "candidates": [/* typed envelopes */]
}
```

The parser must preserve nested JSON. The existing behavior in `_parse_json_facts` that converts every value with `str(v)` must not be used for typed candidates.

The Ollama provider must default to `qwen3:8b`, use low-temperature schema-constrained generation, bound output tokens/runtime, and unload explicitly. Provider preflight and telemetry must distinguish: model missing, Ollama unavailable, resource deferral, timeout, invalid structured output, and success.

### 6.2 Prompt requirements

The prompt must:

- distinguish decisions, facts, observations, procedures, project state, and questions;
- quote no more source text than needed;
- require source references and source hashes supplied by the orchestrator;
- forbid inventing rationale not present in evidence;
- emit `observation` or omit the candidate when rationale/authority is unavailable;
- preserve disagreement and supersession;
- avoid extracting secrets, credentials, transient command noise, or redundant test counters;
- prefer updates to existing canonical records rather than creating near-duplicate keys;
- explicitly state that agent identity does not determine truth.

### 6.3 Deterministic validation

Validate before database insertion:

- exact schema and enum membership;
- required fields by record type;
- allowed key format;
- project/scope consistency;
- source reference belongs to the processed batch;
- source hash matches;
- no secret patterns in any nested field;
- bounded field/list lengths;
- valid timestamps;
- no unknown top-level fields unless kept in a versioned extension map;
- rationale is not identical to statement;
- decision/policy has at least one actionable implication;
- no global trust/reliability score fields;
- canonical JSON hash reproducibility.

Reject individual candidates without discarding an otherwise valid batch. Persist rejection reason in the run audit, not in the active memory store.

### 6.4 Deduplication and matching

Before staging:

- exact dedupe by source fingerprint + key + content hash;
- canonical-key match against active facts/claims;
- semantic similarity may suggest a merge, but may not perform it automatically;
- label suggested action: create, update, merge, supersede, or duplicate;
- include the existing record and a field-level diff for review.

### 6.5 Promotion rules

- LLM-generated decisions, policies, lessons, and disputed facts always require review.
- A deterministic fact may auto-promote only when generated by a deterministic adapter and verified against an authoritative local source with a registered schema.
- Provider/agent history must not bypass review.
- The legacy alpha/beta/reputation table must not affect promotion.
- Every promotion records reviewer, rationale, source candidates, resulting claim ID, and before/after hashes.

## 7. Retire trust from runtime semantics

### 7.1 Dream Cycle

Remove `run_beta_binomial_trust_calibration()` from the default Dream Cycle path. Do not replace it with another global agent score.

If compatibility consumers still call the function:

- keep it behind an explicit legacy flag disabled by default;
- mark output deprecated;
- document known conceptual invalidity;
- prevent it from influencing candidate validation, review priority, or promotion.

### 7.2 Review priority

Rank review candidates using explainable fields:

1. user decision required;
2. conflict with accepted decision/policy;
3. security/privacy impact;
4. project state affecting active work;
5. source freshness/expiry;
6. number of affected tasks/context packets;
7. ordinary new observation.

Do not rank by agent reputation.

### 7.3 API compatibility

Legacy reputation fields may remain in existing responses until consumers migrate, but:

- new context APIs must not expose them;
- UI must not render them;
- deprecation must be documented;
- add tests proving promotion outcomes are invariant to reputation-table contents.

## 8. Mbrain review experience

Add **Harvest Review** within Review & Activity or Projects. Do not create another top-level page unless user testing shows it is necessary.

### 8.1 Queue summary

Show compact, actionable counts:

- decisions/policies needing review;
- proposed project-state updates;
- merge/supersede suggestions;
- validation failures;
- deferred observations;
- last run status and next scheduled run.

When empty, show one compact row. Do not devote the screen to a success illustration.

### 8.2 Candidate card

Display:

- record type and proposed key;
- statement;
- rationale;
- implications;
- project/scope;
- source references and timestamp;
- extractor/provider as provenance only;
- authority and verification status;
- existing canonical record;
- field-level diff;
- why review is required;
- affected tasks/context packets if known.

Actions:

- Accept.
- Edit and accept.
- Merge with existing.
- Mark superseded.
- Reject with rationale.
- Defer.
- Open source.

All mutations require reviewer identity, rationale for reject/edit/merge/supersede, idempotency protection, and audit history.

### 8.3 Structured rendering

Explore, Projects, search results, and context packets must render typed records as human-readable labeled sections. Raw JSON remains available behind a disclosure.

The list preview should prefer:

- decision/policy: statement + short rationale;
- fact: statement/value + evidence source;
- project state: state + effective time;
- question: question + why it matters.

## 9. Context packet integration

Update packet assembly so that:

- accepted typed decisions/policies are preferred over legacy flat summaries;
- proposed candidates are excluded by default;
- user may explicitly include a proposed candidate with a visible warning;
- every decision includes rationale, implications, scope, provenance, and source references;
- stale/superseded records are marked or excluded according to packet profile;
- packet hash changes when an included decision is reviewed or superseded;
- a context packet never represents an LLM proposal as canonical truth.

Add a **Why included?** explanation that cites explicit project/task linkage, authority, freshness, and relevance separately.

## 10. CLI, API, and MCP surface

Suggested CLI:

```text
brain harvest-status
brain harvest-candidates [--project P] [--type T] [--status proposed]
brain harvest-show <candidate-id>
brain harvest-review <candidate-id> --action accept|edit|merge|reject|defer --reviewer X --rationale "..."
brain harvest-migrate-flat --dry-run
brain harvest-run --dry-run
```

Suggested desktop API:

```text
GET  /api/harvest/status
GET  /api/harvest/candidates
GET  /api/harvest/candidates/{id}
POST /api/harvest/candidates/{id}/review
POST /api/harvest/migrate-flat/preview
```

MCP tools should share the same canonical implementation rather than duplicating logic.

Every read returns exact timestamps and source references. Every mutation takes reviewer/agent identity and an idempotency key.

## 11. Tests

### 11.1 Parser and schema

- Nested objects/lists survive provider parsing without stringification.
- Markdown fences and harmless surrounding text parse safely.
- Invalid JSON fails closed.
- Unknown schema version fails closed.
- Required fields vary correctly by record type.
- Empty/generic rationale is rejected for decisions/policies.
- Decision without implications is rejected.
- Source hash mismatch is rejected.
- Secret in any nested value is rejected/redacted according to policy.
- Synthetic trust/reliability fields are rejected.

### 11.2 Pipeline

- Mixed valid/invalid batch stages valid candidates and audits invalid ones.
- Provider fallback preserves the same typed contract.
- Re-running identical input creates no duplicate candidates.
- Model unload occurs after success, parse failure, timeout, and exception.
- Configured local-model availability is checked before work begins.
- A missing model fails or defers visibly and never triggers silent substitution.
- A local-only `qwen3:8b` run produces schema-valid candidates without Antigravity or Gemini.
- Runtime budget terminates safely.
- Global lock prevents concurrent Dream Cycle runs.
- A failed harvest does not rebuild graph/index unnecessarily.
- Candidate counts and telemetry labels are accurate.

### 11.3 Review and promotion

- Decision cannot auto-promote.
- Reputation values do not affect promotion.
- Accept/edit/merge/reject/defer are idempotent and audited.
- Reviewer rationale is required where specified.
- Conflict/supersession preserves historical claims.
- Candidate source/evidence remains linked after promotion.
- Stale review revision produces visible conflict rather than overwrite.

### 11.4 UI

- Empty queue is compact.
- Candidate rationale and source are visible without opening raw JSON.
- Field-level diff is correct.
- Keyboard actions never apply to the wrong filtered candidate.
- Test/mock/system sources can be filtered but provenance is never lost.
- No trust/reputation score appears.
- Partial API failure does not blank Review & Activity.

### 11.5 Context packets and migration

- Accepted typed record outranks legacy flat record.
- Proposed candidate excluded by default.
- Packet hash changes after accepted edit/supersession.
- Migration preview is idempotent and non-destructive.
- Existing six flat records yield candidates with correct source linkage.

### 11.6 Regression

- Existing 160-test baseline remains green.
- Projects, Explore, Graph, Concepts, search, task APIs, PPR, backup/restore, and Dream Cycle runtime remain functional.
- Desktop cold start and project navigation make no model/network call.
- `git diff --check` and all JS syntax checks pass.

## 12. Evaluation fixtures

Create a small checked-in corpus covering:

1. explicit user decision with rationale;
2. decision with no rationale;
3. technical fact derived from test output;
4. stale project-state update;
5. superseded decision;
6. two agents disagreeing;
7. secret embedded in nested evidence;
8. duplicate wording under different keys;
9. same key with meaningful update;
10. irrelevant conversational noise.

Measure:

- record-type accuracy;
- required-field completeness;
- source-reference validity;
- duplicate rate;
- unsafe auto-promotion count, which must be zero;
- rationale faithfulness judged against source fixture;
- context packet preference for accepted rich records.

Do not collapse these into a single opaque quality score.

## 13. Staged implementation

### Stage 0 — Baseline and contract

1. Read this entire spec and `SKILL.md`.
2. Run Brain start/project/index context.
3. Inspect and preserve the dirty working tree.
4. Re-run the full 160-test baseline, JS syntax, and diff checks.
5. Snapshot the six flat Dream Cycle records and their provenance.
6. Add typed schemas and deterministic validators with fixtures.
7. Record a rationale-rich Brain checkpoint.

### Stage 1 — Typed staging pipeline

1. Replace `dict[str, str]` parsing with typed candidate batches.
2. Update all provider prompts and parsers.
3. Add source fingerprints/hashes and run audit.
4. Stage candidates instead of direct promotion.
5. Add deduplication and existing-record diffs.
6. Prove model unload and runtime bounds across terminal paths.

### Stage 2 — Remove reputation control

1. Disable nightly global reputation calibration by default.
2. Remove reputation from promotion and review priority.
3. Add compatibility flag/documentation if required.
4. Add invariance tests using radically different reputation-table values.
5. Keep UI free of proxy scores.

### Stage 3 — Review and structured rendering

1. Implement candidate APIs/CLI/MCP.
2. Add Harvest Review UI.
3. Add audited accept/edit/merge/reject/defer flows.
4. Render typed records in Explore, Projects, and search.
5. Update context packet assembly.

### Stage 4 — Migration and live verification

1. Implement dry-run migration for six flat facts.
2. Review migration preview without destructive replacement.
3. Run a deterministic fake-provider end-to-end test.
4. Run one live Dream Cycle only after tests pass.
5. Run a separate local-only verification with `DREAM_PROVIDERS=ollama` and `DREAM_LLM_MODEL=qwen3:8b`.
6. Verify telemetry, candidate staging, no unsafe promotion, index/graph behavior, selected model identity, and explicit unload.
7. Do not approve candidates merely to make the demo look complete.

### Stage 5 — Handoff

1. Run the full test suite, JS syntax, diff checks, and retrieval benchmark.
2. Capture screenshots of queue, candidate rationale/diff, source evidence, structured Explore rendering, and context packet inclusion.
3. Update Brain using the new rationale-rich format.
4. Report exact changed files, schemas, migrations, tests, runtime evidence, limitations, and dirty-tree state.
5. Stop for Codex/user review.

## 14. Acceptance criteria

1. Provider output remains structured from generation through staging.
2. Decisions and policies lacking rationale/scope/implications cannot become candidates or active facts.
3. Every candidate has valid source references, hashes, extractor metadata, and review reason.
4. LLM-generated decisions/policies never auto-promote.
5. Candidate deduplication is deterministic and idempotent.
6. Review actions are revision-safe, idempotent, and audited.
7. Promotion is invariant to legacy reputation-table contents.
8. Default Dream Cycle does not run global reputation calibration.
9. UI contains no global trust/reliability/reputation proxy.
10. Explore and Projects render rationale-bearing records readably.
11. Context packets prefer accepted structured records and exclude proposals by default.
12. The six legacy flat facts have a safe, reviewable migration path.
13. Live Dream Cycle reports candidates staged—not facts promoted—unless deterministic promotion rules genuinely apply.
14. No secret leaves its allowed boundary or appears in candidate payloads/logs.
15. No model loads on Mbrain browse/open paths.
16. Existing product features and tests remain green.
17. Local-only harvesting is proven with installed `qwen3:8b`; no configured default references a missing model.

## 15. Non-goals

- Live multi-agent process orchestration.
- Renaming the SQLite database file.
- Deleting legacy tables without a consumer audit.
- Automatically accepting migrated facts.
- Replacing local retrieval architecture.
- Improving PPR or benchmark ranking algorithms in this pass.
- Cloud transmission of memory content.
- A single context/agent/project quality score.
- Cosmetic redesign unrelated to Harvest Review and structured rendering.

## 16. Ready-to-paste Antigravity prompt

```text
Implement Mbrain Pass 5 from:
/Users/mihirdeshpande/projects/global-memory/docs/MBRAIN_PASS_5_CONTEXT_HARVESTING_SPEC.md

Read the entire spec and /Users/mihirdeshpande/projects/global-memory/SKILL.md before acting. Use Brain start-context, project context, and relevant index queries. Preserve the intentionally dirty shared working tree and all icon assets. Do not reset, clean, commit, or rewrite unrelated work.

Current independently verified state: 160/160 tests pass, desktop JavaScript syntax and git diff formatting are clean, and a live Dream Cycle completed in 51.19 seconds with exit code 0. Project Context, deterministic context packets, cross-view search, graph clustering, entity merge, task API parity, WAL hardening, PPR retrieval, and retrieval benchmarks exist. The verified defect is semantic: Dream Cycle promoted six flat string facts that do not satisfy the rationale-first Context Engineering Contract. Dream Cycle also retains legacy global reputation calibration internally after global trust was retired from the product. The successful run used Antigravity. Installed Ollama models are qwen3:8b, qwen2.5-coder:7b, and qwen3-embedding:0.6b; several configured defaults currently reference missing models.

Make harvesting typed, evidence-linked, staged, reviewable, and rationale-first. LLM extraction proposes candidates; it does not create truth. Disable global reputation calibration by default and prove reputation cannot influence promotion. Standardize local harvesting and concept enrichment on installed qwen3:8b; keep qwen3-embedding:0.6b for embeddings; validate availability explicitly; and prove a local-only run. Add a compact Harvest Review workflow, structured rendering, context-packet integration, deterministic validation/deduplication, safe migration preview, and comprehensive tests. Run live verification only after deterministic tests pass. Record rationale-rich Brain checkpoints after each stage. Stop for review when acceptance criteria are met; do not begin unrelated work.
```

## 17. Required completion report

Antigravity must provide:

- stage-by-stage completion status;
- exact files and schemas changed;
- migration/dry-run output for the six legacy records;
- provider prompt/schema version;
- validation and rejection examples;
- proof that reputation values do not affect promotion;
- screenshots of review and structured rendering;
- full tests, JS checks, diff checks, and benchmark output;
- live Dream Cycle telemetry showing candidate counts and unload state;
- explicit list of anything still using legacy trust/reputation storage;
- `git status --short`, separating pre-existing from new changes;
- known limitations and recommended review focus.
