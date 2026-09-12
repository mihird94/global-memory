# Mbrain Pass 8 — Project Intelligence and Agent Continuity

## Mission

Turn Mbrain from a memory administration interface into an operational context system that helps a new agent resume real work correctly.

The product-level acceptance test is:

> Give a fresh agent only an Mbrain-generated resumption bundle for a real project. The agent must correctly identify the goal, current truth, binding decisions, constraints, completed work, unresolved issues, relevant artifacts, verification state, and next action without rereading the entire repository or conversation history.

This pass prioritizes workflow depth over feature count. Do not add decorative scores, generic dashboards, or panels that merely expose database rows.

Repository: `/Users/mihirdeshpande/projects/global-memory`

Read first:

- `docs/GMS_MEMORY_CONVENTIONS_V1.md`
- `docs/MBRAIN_PASS_7_MEMORY_LIFECYCLE_AND_RETRIEVAL_SPEC.md`
- `SKILL.md`
- current `~/memories/projects/global-memory/` bank

Do not commit.

## Honest starting state

Pass 7 created important primitives, but they are not yet a complete intelligence system:

- `tools/memory_lifecycle.py` centralizes audited lifecycle transitions.
- `tools/memory_authority.py` distinguishes authority and provenance roles.
- `tools/memory_convention_audit.py` inventories flat memory and fixture warnings.
- `tools/memory_aliases.py` previews aliases and collisions.
- `tools/context_retrieval_planner.py` defines retrieval lanes, but retrieval remains shallow and mostly lexical.
- `tools/context_packet.py` emits deterministic packet manifests.
- `tools/consolidation_policy.py` attaches non-promoting proposed operations to nightly candidates.
- Mbrain has a Memory Quality workbench and Projects is the default route.
- Task resume bundles exist, but they do not yet demonstrate reliable continuation of real work.
- The baseline is 208 passing Python tests, clean desktop JavaScript syntax, and clean diff formatting.

Live read-only baseline at the end of Pass 7:

- 90 legacy flat facts;
- zero accepted structured active records;
- 11 pending AI candidates;
- 18 suspected fixture-origin warning claims;
- one unresolved AlphaOS canonical-key collision;
- `car_stickers_status` remains an opaque status needing context;
- no live cleanup, candidate review, bulk migration, or collision resolution was performed.

Do not describe existing lane names as “real hybrid retrieval” unless each lane actually obtains and ranks evidence from its declared source.

## Non-negotiable boundaries

1. Preserve every current uncommitted change and icon asset.
2. Tests, fixtures, previews, and evaluations use temporary memory roots only.
3. Do not accept, reject, defer, merge, or supersede live candidates.
4. Do not delete or modify the 18 warning claims.
5. Do not resolve the AlphaOS collision.
6. Do not rewrite or bulk-stage the 90 legacy facts.
7. Do not invent rationale, authorship, source evidence, timestamps, task outcomes, or agent success.
8. Do not download a model or change the installed model inventory.
9. Do not change launchd jobs or schedules.
10. Normal desktop launch, navigation, browsing, and search must not load an LLM.
11. No external CDN, telemetry, cloud database, or mandatory network dependency.
12. No global agent trust, confidence, reputation, utility, health, or composite quality score.
13. No automatic agent dispatch. Resumption produces a bundle; the user chooses where to send it.
14. Do not create a branch, commit, push, PR, or release.

## Product hierarchy

The primary navigation and information architecture should express this order:

```text
Projects
  → Project Briefing
  → Current Work
  → Decisions
  → Timeline
  → Evidence & Knowledge
  → Resume with Context

Action Inbox
  → Blocking contradictions
  → Required human decisions
  → Stale operational truth
  → Evidence failures
  → Candidate reviews
  → Memory repairs

Explore / Graph / Memory Quality
  → supporting investigative tools
```

Projects is the operational home. Explore, Graph, and Memory Quality remain useful but secondary.

## Stage 0 — Baseline and evidence capture

Before editing:

1. Capture `git status --short` and `git diff --stat`.
2. Hash the live SQLite database and semantic fact files.
3. Run the complete test suite.
4. Run desktop JavaScript syntax checks and `git diff --check`.
5. Capture read-only outputs from:
   - `memoryctl convention-audit`;
   - `memoryctl harvest-status`;
   - `memoryctl aliases`;
   - one Small, Standard, and Deep context packet;
   - one project task-resume record if available.
6. Inspect every Pass 7 module and identify declared lanes or metrics that are placeholders rather than genuine retrieval.
7. Record baseline latency and retrieved item sources for at least five realistic project questions.

Do not hard-code test counts or live data counts into product code.

## Stage 1 — Project Briefing as the core product

Create one coherent Project Briefing engine shared by desktop, CLI, API, and MCP.

### Questions the briefing must answer

Every briefing must make these answers visible without opening raw JSON:

1. What is this project trying to achieve?
2. What is the current verified state?
3. What changed recently?
4. What work is active, blocked, or awaiting review?
5. Which decisions and constraints bind the next action, and why?
6. Which procedures should the next agent follow?
7. What evidence supports the briefing?
8. Which contradictions, stale facts, or unanswered questions may change the action?
9. What should the next agent do first?
10. How will completion be verified?

### Briefing sections

The canonical briefing schema must include:

```json
{
  "schema_version": "gms-project-briefing-v1",
  "project_id": "...",
  "generated_at": "...",
  "as_of": null,
  "goal": {"statement": "...", "source_refs": []},
  "current_truth": [],
  "active_work": [],
  "binding_decisions": [],
  "constraints": [],
  "procedures": [],
  "recent_changes": [],
  "blocking_issues": [],
  "open_questions": [],
  "artifacts": [],
  "verification": [],
  "next_action": {"statement": "...", "rationale": "...", "acceptance_criteria": []},
  "inclusion_manifest": [],
  "omission_manifest": [],
  "packet_hash": "sha256:..."
}
```

Each included item must retain record ID, lifecycle state, authority, author/extractor/reviewer separation, scope, effective time, source validity, retrieval lane, component rank, and inclusion reason.

### Truth constraints

- “Current truth” may not include proposed AI candidates.
- A proposed candidate may appear only in a separately labeled “Awaiting review” section.
- A stale operational fact must be labeled stale and cannot drive the next action without revalidation.
- Superseded records are excluded from current truth but available in history.
- Blocking contradictions must appear even when they rank below the normal token cutoff.
- If the system cannot infer a next action from explicit task/handoff state, say `Next action unavailable` and list what is missing.
- AI may summarize cited rationale but may not create rationale absent from the source.

### UI

Replace the current Projects overview with an answer-first briefing:

- a compact top strip for objective, state, last meaningful change, and next action;
- a prominent `Resume with Context` action;
- blocking issues before general recent activity;
- binding decisions displayed with rationale and implications;
- active tasks grouped by doing, blocked, awaiting review, and unclaimed;
- source disclosure on every card;
- an “As of” control for historical reconstruction;
- no placeholder cards when data is absent—use explicit missing-context prompts.

## Stage 2 — Genuine hybrid retrieval

Replace the shallow lane implementation with real independently executed retrieval lanes.

### Query interpretation

Build a deterministic query plan containing:

- task intent: lookup, explanation, decision, procedure, resume, debugging, historical, comparison;
- project and workstream;
- entities and canonical aliases;
- requested effective time or current-time default;
- required record types;
- assurance requirement;
- token budget;
- required lanes;
- mandatory contradiction and task-state checks.

Use an LLM only as an optional nightly/offline enrichment source. Interactive query planning must work deterministically without loading a model.

### Real retrieval lanes

Each enabled lane must run and report its own candidates and latency:

1. Exact canonical key and alias lookup.
2. Lexical BM25 over structured records and project banks.
3. Vector search over indexed episodic and semantic chunks.
4. Active project decisions and constraints.
5. Procedures applicable to project, environment, and trigger.
6. Open tasks, checkpoints, and handoffs.
7. Contradictions, disputes, stale records, and unresolved questions.
8. Recent project-scoped episodes.
9. Knowledge-graph neighbors and bounded multi-hop paths.
10. File/artifact evidence explicitly linked from tasks and decisions.

Do not list a lane as used when it returned no candidates.

### Candidate normalization

Normalize all lane results into one retrieval-item contract before fusion. Keep component scores separate:

- exact-match flag;
- BM25 rank;
- vector rank and similarity;
- graph path length;
- task-state priority;
- authority class;
- source-validity state;
- lifecycle state;
- effective-time match;
- freshness state;
- project/scope match;
- contradiction flag;
- redundancy group.

Do not collapse these into a universal confidence score.

### Fusion and diversity

- Use deterministic reciprocal-rank fusion or another tested rank-fusion method.
- Apply lifecycle, scope, time, and source-validity gates before final selection.
- Reserve budget for current task state, decisions, procedures, and blocking conflicts.
- Enforce per-source and per-namespace caps.
- Deduplicate repeated facts across `facts.json`, claims, project Markdown, and episodes while preserving all distinct provenance references.
- Prefer authoritative current records over older semantically similar text.
- Always include a blocking contradiction that can change the action.
- Explain why a higher-scoring item was omitted when caps, staleness, supersession, or invalid evidence caused exclusion.

### Temporal retrieval

Support both:

- “What is true now?”
- “What was believed/effective at timestamp T?”

Recorded time and effective time are separate. Historical retrieval must traverse supersession chains and must not leak later truth into an earlier `as_of` briefing.

### Graph retrieval

- Seed entities through exact names, aliases, and project-linked entities.
- Traverse at most the requested hop count.
- Return the evidence path, not only the terminal node.
- Filter invalid or expired edges by `as_of`.
- Prevent generic hubs from dominating results.
- Graph results must link back to source records or be labeled unsupported.

## Stage 3 — Unified project timeline

Create a normalized timeline service rather than assembling unrelated UI lists.

### Event types

- authenticated user instruction or correction;
- project-bank change;
- decision proposed, accepted, superseded, or archived;
- task created, claimed, checkpointed, handed off, blocked, resumed, or completed;
- source file or linked artifact changed;
- command/test/benchmark observation;
- candidate extracted or reviewed;
- contradiction detected or resolved;
- nightly consolidation result;
- memory repair or migration event.

### Timeline event schema

Every event includes:

- stable event ID and type;
- project/task/entity scope;
- event time, effective time, and recorded time;
- concise title and material change summary;
- producer and authority;
- source/evidence references;
- related records and artifacts;
- resulting state;
- whether the event changed actionable context.

### Timeline behavior

- Default sort is newest meaningful activity.
- Filter by event type, agent, task, artifact, decision, and date.
- Group repeated low-value telemetry rather than flooding the stream.
- Expand an event to show before/after and evidence.
- Navigate from event to task, decision, source, graph entity, or memory review.
- Historical briefing links to the exact timeline boundary used.

## Stage 4 — Decision intelligence

Add a first-class decision service and view.

### Decision contract

A decision requires:

- standalone decision statement;
- rationale supported by source;
- implications and behavioral constraints;
- scope and environment;
- alternatives considered or explicitly unavailable;
- assumptions;
- evidence;
- author, extractor, reviewer, and authority;
- effective time;
- review condition/date;
- lifecycle and supersession chain;
- affected tasks, artifacts, entities, and procedures.

### Decision UI and queries

Support:

- “Why is the system this way?”
- “What decision governs this file/task?”
- “What changes if this decision is superseded?”
- “Which decisions lack rationale or evidence?”
- “Which decisions conflict?”

Show decisions as readable cards. Raw JSON is secondary disclosure. Reviewing an AI-extracted decision must never relabel it as authored by Mihir.

## Stage 5 — Current Work and agent continuity

Create a project-scoped work control plane without global agent reputation.

### Work board

Show:

- current task and owner;
- task goal and intended outcome;
- revision and lease state;
- last checkpoint;
- completed work;
- remaining work;
- files changed;
- commands/tests and outcomes;
- assumptions;
- blockers and unresolved questions;
- acceptance criteria;
- latest handoff and intended consumer;
- context-packet hash;
- stale or conflicting parallel work.

### Objective outcome signals

Track only task-scoped observable outcomes:

- completed and verified;
- completed but unverified;
- blocked;
- reverted;
- corrected by user;
- superseded by another task;
- abandoned/stale lease;
- conflicting artifact edits.

Do not infer a universal agent ranking from these events.

### Resume with Context

Generate formats for:

- Codex;
- Antigravity;
- Gemini CLI;
- generic terminal/JSON consumer.

Every bundle includes:

- goal and acceptance criteria;
- current project briefing;
- checkpoint and handoff;
- decisions and constraints;
- relevant procedures;
- changed files and artifacts;
- commands/tests and exact results;
- assumptions and blockers;
- unresolved conflicts/questions;
- next action;
- source manifest;
- omission manifest;
- deterministic packet hash.

The generated prompt should tell the receiving agent what to inspect first and explicitly distinguish verified state from proposed/inferred context.

Never dispatch automatically.

## Stage 6 — Action Inbox

Replace passive “Review & Activity” behavior with a consequence-ranked Action Inbox.

### Inbox categories in priority order

1. Blocking contradiction affecting active work.
2. Human decision required for an active task.
3. Invalid or missing evidence on actionable context.
4. Stale operational fact used by an active workflow.
5. Broken task handoff or expired lease.
6. Proposed decision/policy awaiting review.
7. Alias collision affecting retrieved truth.
8. Opaque status record needing repair.
9. Lower-impact candidate review.

### Every inbox item answers

- What happened?
- Why does it matter now?
- Which project/task/action is affected?
- What evidence supports the warning?
- What changes if the user accepts, rejects, repairs, or defers it?
- Is the action reversible?

### Interactions

- preview before any mutation;
- compare current/proposed/source side by side;
- accept/edit/merge/supersede/contradict/defer/archive only through existing audited lifecycle paths;
- registered reviewer plus substantive rationale;
- optimistic content/snapshot hash;
- keyboard accessible actions;
- append-only audit history;
- undo only through an explicit compensating lifecycle event, never audit deletion.

Do not create a priority score whose meaning cannot be explained. Use ordered rules and visible reasons.

## Stage 7 — Source-grounded memory repair

Build a repair workflow for incomplete records such as `car_stickers_status = active`.

### Repair process

1. Find exact and related source events, project notes, tasks, claims, and artifact references.
2. Display candidate evidence excerpts with hashes and dates.
3. Identify missing fields: rationale, scope, implications, source, effective time, review horizon.
4. Separate deterministic recovery from AI-inferred suggestions.
5. If evidence is insufficient, generate concise questions for the user instead of filling fields.
6. Produce a structured candidate; never alter the legacy value until reviewed.

### Labels

- Recovered from source
- Suggested by AI
- User supplied
- Still unknown

An LLM may batch-propose repairs during the nightly run. Interactive browsing and evidence search must work without loading it.

## Stage 8 — Useful nightly consolidation and morning briefing

Upgrade Dream Cycle from candidate staging telemetry into project-aware consolidation.

### Nightly inputs

- new episodic notes and user instructions;
- agent task/checkpoint/handoff events;
- project-bank changes;
- linked repository artifacts and verification logs;
- active structured truth and unresolved conflicts;
- candidate queue and prior consolidation outcomes.

### Required phases

1. Acquire lock and resource guard.
2. Detect projects changed since the prior successful run.
3. Batch source material by project and task.
4. Run deterministic extraction first.
5. Optionally run the configured local model or Antigravity provider in bounded batches.
6. Validate provenance and classify every candidate operation.
7. Stage candidates only; never promote decisions or policies.
8. Refresh project timelines and deterministic briefing caches from accepted truth.
9. Produce a morning briefing for each changed project.
10. Write machine-readable telemetry.
11. Explicitly unload the local model on success, error, timeout, parse failure, and cancellation.

### Morning briefing

For each changed project show:

- meaningful changes since the previous run;
- active tasks and blockers;
- decisions proposed or changed;
- contradictions or stale facts requiring action;
- candidates awaiting review;
- suggested first action for the day with provenance;
- links to the Project Briefing and Action Inbox.

“Five candidates staged” is telemetry, not the user-facing morning briefing.

### Model policy

- Keep the installed baseline; do not download another model.
- Record provider, actual model, prompt version, duration, outputs evaluated, parse result, memory/load observation, and unload result.
- Never attribute fixture-schema metrics to a model.
- If the provider is unavailable, complete deterministic phases and report degraded mode honestly.

## Stage 9 — Real-world resumption evaluation

Create a checked-in evaluation corpus derived from sanitized real project histories, not only synthetic key lookups.

### Evaluation scenarios

At minimum include:

1. Resume Mbrain after Pass 7 and identify unfinished work.
2. Explain why global agent trust was retired.
3. Recover the current Dream Cycle schedule and distinguish it from stale values.
4. Identify the AlphaOS plugin-version collision without resolving it.
5. Resume a task from checkpoint and handoff with files/tests/next action.
6. Answer a historical “what was true then?” question.
7. Retrieve a procedure applicable to a particular environment.
8. Surface a blocking contradiction despite lower semantic similarity.
9. Ignore irrelevant high-similarity memories from another project.
10. Explain why an opaque status cannot be safely acted on.

### Ground truth

Each scenario defines:

- required facts/records;
- prohibited stale or proposed records;
- required contradiction/question;
- required source citations;
- expected next action;
- maximum token budget;
- project and temporal scope.

### Metrics by class

Report separately:

- exact-key accuracy;
- current-truth accuracy;
- temporal accuracy;
- decision/rationale faithfulness;
- procedure applicability;
- contradiction recall;
- project isolation;
- source citation validity;
- resume completeness;
- irrelevant-memory rate;
- token compression ratio;
- latency by retrieval lane and total.

Do not hide weak classes behind one aggregate.

### Agent continuation trial

Add a reproducible, non-dispatching trial harness:

1. Build a bundle for a held-out project task.
2. Score whether a fresh evaluator can identify required state and next action from the bundle alone.
3. Compare with a lexical-only baseline and with the complete raw source context.
4. Record missing information and unsafe hallucinations.
5. Do not claim downstream agent success unless an actual generated answer was evaluated.

Static fixtures validate schemas and deterministic retrieval. Model-quality claims require actual model outputs.

## Stage 10 — API, CLI, MCP, and caching

Use shared modules rather than duplicating business logic.

### Required typed interfaces

- `project-briefing generate|get|explain`
- `project-timeline list|event`
- `decision list|get|impact`
- `retrieval-plan inspect|execute`
- `context-packet build|verify`
- `task-resume build|verify`
- `action-inbox list|preview|apply`
- `memory-repair evidence|questions|stage`
- `morning-briefing list|get`
- `eval-resumption run|report`

Expose equivalent versioned API routes and MCP tools where appropriate.

### Caching rules

- Cache only deterministic outputs keyed by source snapshot hash, project, as-of time, profile, and planner version.
- A candidate review, task checkpoint, project-bank update, lifecycle transition, or source change invalidates affected cache entries.
- Never serve a cache whose source snapshot differs from the manifest.
- Cache writes are atomic.
- Normal UI navigation may read cached briefings but may not initiate LLM inference.

## Stage 11 — UX quality bar

### Project Briefing

- readable at a glance;
- important blockers above chronology;
- one clear primary action;
- expandable provenance rather than raw JSON walls;
- links among tasks, decisions, evidence, timeline, and graph;
- visible current/as-of mode;
- empty states that state exactly what context is missing.

### Timeline

- compact grouped stream;
- obvious event type and consequence;
- before/after disclosure;
- filters retain state when navigating back.

### Action Inbox

- ordered by explicit consequence rules;
- affected action/project shown prominently;
- preview and rationale before mutation;
- no “clean/healthy/100% trusted” celebration screen.

### Accessibility and robustness

- semantic buttons and headings;
- keyboard navigation and visible focus;
- screen-reader labels for icon actions;
- no horizontal overflow at supported window widths;
- loading, empty, degraded, and error states;
- request cancellation or stale-response guards when changing projects rapidly;
- source excerpts and long keys wrap safely.

## Suggested implementation ownership

Prefer clear modules such as:

- `tools/project_briefing.py`
- `tools/project_timeline.py`
- `tools/decision_intelligence.py`
- `tools/action_inbox.py`
- `tools/memory_repair.py`
- `tools/resumption_eval.py`
- strengthen `tools/context_retrieval_planner.py`
- strengthen `tools/context_packet.py`
- extend `tools/consolidation_policy.py` and `tools/dream_cycle.py`
- extend `tools/memoryctl.py`, `tools/memory_mcp_server.py`, and `tools/gms_desktop_api.py`
- focused desktop view modules rather than expanding one monolithic file.

This layout is guidance. Preserve compatibility and use the existing shared lifecycle/authority/alias modules.

## Required tests

### Project briefing

- required section completeness;
- truthful missing-data behavior;
- candidate exclusion;
- contradiction inclusion;
- deterministic hash;
- Small/Standard/Deep budgets;
- source and omission manifests;
- historical as-of reconstruction.

### Retrieval

- every declared lane actually executes;
- lane latency and candidate counts are honest;
- exact alias lookup;
- BM25 and vector contributions;
- graph path evidence;
- task/handoff retrieval;
- temporal state and supersession;
- contradiction recall;
- source and namespace diversity;
- project isolation;
- stale/invalid-source gating;
- deterministic fusion and tie-breaking.

### Timeline and decisions

- stable event IDs;
- time normalization;
- deduplication/grouping;
- before/after representation;
- rationale fidelity;
- decision impact links;
- supersession-chain traversal.

### Agent continuity

- complete handoff schema;
- prompt variants remain semantically equivalent;
- packet hash verification;
- missing checkpoint behavior;
- expired lease detection;
- conflicting artifact detection;
- no automatic dispatch.

### Inbox and repair

- explicit consequence ordering;
- preview performs zero writes;
- optimistic concurrency;
- registered reviewer and rationale requirements;
- opaque-status repair never invents context;
- inferred fields remain labeled;
- rollback/compensating event behavior.

### Nightly and safety

- deterministic phases run without provider;
- every candidate has an explicit operation;
- no auto-promotion;
- model unload on every terminal path;
- no model download;
- no interactive UI model load;
- test suite leaves live Brain byte-for-byte unchanged;
- no live mutation from evaluation.

## Acceptance criteria

Pass 8 is complete only when all are true:

1. A Project Briefing answers the ten operational questions with source-backed content.
2. Projects remains the default operational route.
3. Each declared retrieval lane really executes and reports candidates/latency honestly.
4. Retrieval combines exact, BM25, vector, graph, task, temporal, contradiction, procedure, episode, and artifact evidence.
5. Current truth excludes proposed, stale-actionable, superseded, and invalid-source records by default.
6. Historical briefings respect effective time and supersession boundaries.
7. The unified timeline connects instructions, work, decisions, artifacts, verification, and memory lifecycle.
8. Decisions expose rationale, implications, alternatives, assumptions, evidence, and impact.
9. Resume bundles contain enough verified context for a fresh agent to name the correct next action and acceptance criteria.
10. The Action Inbox explains consequence and reversibility for every item.
11. Opaque-memory repair separates recovered evidence, AI suggestion, user input, and unknown fields.
12. Nightly consolidation produces project morning briefings, not only candidate counts.
13. Evaluation reports class-level results and includes a real held-out resumption scenario.
14. No global trust/confidence/health score appears.
15. Full tests pass, JavaScript syntax is clean, diff formatting is clean, and live Brain hashes are unchanged by tests.
16. No forbidden live review, cleanup, migration, collision resolution, model download, launchd mutation, or git commit occurred.

## Required verification evidence

Return:

- baseline and final `git status --short`;
- exact files added/changed during Pass 8;
- complete test output;
- desktop JavaScript syntax result;
- `git diff --check` result;
- live Brain hashes before and after the test suite;
- live read-only convention audit before and after;
- retrieval trace for each lane with candidate count and latency;
- five realistic query plans and inclusion/omission manifests;
- Small/Standard/Deep packet examples and hashes;
- one current and one historical Project Briefing;
- one unified timeline example;
- one decision-impact example;
- one Action Inbox ordering example;
- `car_stickers_status` repair preview showing no invented fields;
- morning briefing example from a temporary fixture root;
- resumption evaluation by question class;
- explicit model load/unload observation;
- confirmation that no forbidden action or commit occurred.

## Required Antigravity execution discipline

1. Read the full specification and conventions before editing.
2. Create an implementation plan mapped one-to-one to stages and acceptance criteria.
3. Audit existing Pass 7 code; reuse sound primitives and replace shallow behavior.
4. Work in bounded vertical slices: backend contract, tests, API/CLI/MCP, then UI.
5. Run focused tests after each slice.
6. Do not pause after merely creating a plan unless a genuine safety blocker exists.
7. Do not report a lane, metric, model evaluation, or downstream outcome that was not actually executed.
8. Finish with an evidence-backed gap analysis. If an acceptance criterion is incomplete, label it incomplete rather than calling the pass done.

## Ready-to-paste Antigravity prompt

```text
Implement Mbrain Pass 8 in /Users/mihirdeshpande/projects/global-memory by following docs/MBRAIN_PASS_8_PROJECT_INTELLIGENCE_AND_AGENT_CONTINUITY_SPEC.md completely. Read docs/GMS_MEMORY_CONVENTIONS_V1.md, docs/MBRAIN_PASS_7_MEMORY_LIFECYCLE_AND_RETRIEVAL_SPEC.md, SKILL.md, and the current global-memory Brain project bank first. Preserve every uncommitted change and icon asset. The goal is not another dashboard: make Project Briefing and Resume with Context genuinely capable of continuing real work. Replace shallow lane declarations with actually executed exact/BM25/vector/graph/task/temporal/conflict/procedure/episode/artifact retrieval; add the unified timeline, decision intelligence, consequence-ranked Action Inbox, source-grounded repair, useful nightly morning briefing, and real resumption evaluation. Do not accept/reject live candidates, delete warning claims, resolve collisions, rewrite or bulk-stage legacy facts, download models, modify launchd, dispatch agents, commit, push, or create a PR. Prove live-root immutability and return every required artifact and verification result. If anything remains incomplete, report it explicitly instead of calling the pass complete.
```
