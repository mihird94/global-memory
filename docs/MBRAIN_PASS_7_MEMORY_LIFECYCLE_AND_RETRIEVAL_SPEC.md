# Mbrain Pass 7 — Memory Lifecycle, Curation, and Retrieval Intelligence

## Mission

Implement `docs/GMS_MEMORY_CONVENTIONS_V1.md` as enforceable product behavior across storage, migration, retrieval, context packets, nightly consolidation, CLI/API, and Mbrain.

This pass must convert GMS from “many flat facts plus a candidate queue” into a trustworthy context lifecycle. A future agent should receive the right current project context, understand where it came from, see contradictions and uncertainty, and know which memories were user-stated, system-verified, document-derived, AI-inferred, or imported legacy.

This is not a bulk migration pass. Do not fabricate rationale, impersonate Mihir, silently merge memories, or accept/delete live records without explicit approval.

## Verified starting state

Repository: `/Users/mihirdeshpande/projects/global-memory`

Canonical conventions: `docs/GMS_MEMORY_CONVENTIONS_V1.md`

Baseline verified by Codex on 2026-09-09:

- 199/199 Python tests pass in about 7.5 seconds.
- Desktop JavaScript syntax and `git diff --check` are clean.
- 90 active semantic facts are legacy flat values.
- Zero active facts use an accepted `gms-context-record-v1` envelope.
- Six evidence-linked candidates are pending review; four are decisions/policies.
- Confirmed pollution count is zero.
- Convention warnings include 18 likely fixture-origin claims, one canonical-key collision, and one status-only fact.
- Collision: `alphaos.swing.plugin_version` versus `alphaos_swing_plugin_version`.
- Opaque status: `car_stickers_status = active`.
- The live model baseline is installed `qwen3:8b`; `qwen3.5:9b` is not installed.
- The model evaluator correctly reports `insufficient_evidence` without comparable generated outputs.
- Nightly schedule is 03:10 local time.

Preserve all current uncommitted work, including icon assets. Do not commit.

## Non-negotiable safety boundaries

1. Tests and previews use temporary `MEMORY_ROOT` and databases only.
2. `--dry-run` and preview endpoints perform zero durable writes.
3. Do not accept/reject/defer/merge the six live candidates.
4. Do not delete the 18 warning-only fixture claims during implementation.
5. Do not merge the AlphaOS version-key collision in live data.
6. Do not rewrite all 90 flat facts.
7. Do not install or pull an Ollama model.
8. Do not modify launchd configuration.
9. Do not create commits, branches, pushes, or PRs.
10. Every potential live mutation must be separately previewable and require an explicit `--apply` or confirmed UI action.

## Stage 0 — Baseline and live-root guard

Before editing:

- Capture `git status --short` and current diff statistics.
- Run all 199 tests, desktop syntax checks, and `git diff --check`.
- Capture read-only outputs of `memoryctl pollution-audit`, `harvest-status`, and candidate source verification.
- Hash the live database and semantic fact files before tests. Prove that the test suite leaves them unchanged.
- Record exact baseline counts; never use hard-coded “199” in product code.

Add a reusable test guard that fails if any test resolves `MEMORY_ROOT` to the actual user home Brain. Apply it across all suites, not only Dream Cycle tests.

## Stage 1 — Canonical lifecycle and operation engine

Create one authoritative lifecycle module used by CLI, MCP, API, Dream Cycle, migrations, and the desktop. Avoid duplicating transition rules.

### Required lifecycle states

```text
proposed → accepted → superseded → archived
         ↘ rejected
         ↘ deferred → proposed
```

Support explicit operations:

- `add`
- `reinforce`
- `merge`
- `supersede`
- `contradict`
- `noop`
- `archive`
- `restore`

### Transition contract

Each transition must record:

- record/candidate identifier;
- canonical key;
- prior and next state;
- operation;
- actor identity and actor kind;
- rationale;
- original and resulting content hashes;
- effective/event/recorded timestamps;
- source/evidence references;
- related/superseded record IDs;
- append-only audit timestamp.

Reject illegal transitions centrally. Use optimistic concurrency hashes. Repeating the same transition request must be idempotent.

Never overload SQLite `confidence` as authority or acceptance. Treat any required legacy confidence column as compatibility-only and exclude it from ranking, UI, and lifecycle decisions.

## Stage 2 — Authority and provenance enforcement

Implement and validate the five canonical authority classes:

- `user_instruction`
- `verified_system_output`
- `source_document`
- `llm_inference`
- `imported_legacy`

Add explicit provenance roles:

- `author` — originator of the underlying statement when known;
- `extractor` — process/agent that transformed the source;
- `reviewed_by` — registered identity approving a transition;
- `observed_agents` — attribution only.

Rules:

- An extractor cannot become author by default.
- AI tools cannot assign `author=mihir` unless the source is an authenticated user action.
- `llm_inference` decisions/policies always require human review.
- `imported_legacy` cannot claim `verification=verified` without a valid source.
- Deterministic system facts can auto-promote only through an allow-listed verifier that records command/API/file evidence and observation time.
- Unknown authority is visible and excluded from high-assurance context packets.

Provide validation errors that are understandable in CLI and UI.

## Stage 3 — Flat-memory migration workbench

Build a generic migration planner for the 90 flat semantic facts. It must never invent context.

### Classification

For each flat fact, classify deterministically where possible:

- user preference/safety constraint;
- project decision;
- procedure;
- operational/system fact;
- personal reference fact;
- time-sensitive observation;
- opaque status;
- duplicate/alias candidate;
- suspected fixture/test data;
- unknown.

Classification output is a proposal, not active truth.

### Migration readiness

Each row exposes:

- current key/value;
- proposed dotted canonical key;
- proposed record type and authority;
- source/provenance availability;
- whether rationale is required and present;
- freshness/revalidation need;
- duplicate/collision candidates;
- risk tier;
- recommended operation;
- blockers;
- field-level preview.

Risk tiers:

- High: preferences, policies, safety, identity, financial/trading rules, destructive permissions.
- Medium: active project decisions, procedures, infrastructure state.
- Low: deterministic reference facts with clear provenance.

High and medium records always require deliberate review. Do not mass-select them by default.

### Batch behavior

- Preview supports filters and exports deterministic JSON.
- Batch staging may stage candidates but cannot accept them.
- Every staged candidate retains the untouched legacy source until accepted.
- Acceptance supersedes the legacy key; rollback restores it.
- Missing evidence yields `imported_legacy` and `unverified`, never fabricated rationale.
- Provide progress counts: untouched, proposed, ready, blocked, staged, accepted, superseded, archived.

## Stage 4 — Fixture-warning adjudication

The current audit reports 18 likely fixture-origin claims:

- one `DreamCycle-mock-provider` claim;
- nine `agent_test` claims;
- eight `agent_1` claims, including superseded versions.

Extend the audit into an adjudication preview that explains *why* each is suspicious using independent signals:

- known fixture agent;
- generic test key/value;
- source reference into test files;
- timestamp cluster matching test execution;
- absent semantic source;
- mock provider name.

Do not delete based solely on an agent name. Require at least two signals or an exact fixture fingerprint.

Provide:

- `memoryctl convention-audit`
- `memoryctl convention-cleanup --dry-run` as default
- `memoryctl convention-cleanup --apply --reviewer <id> --rationale <text>`

Apply must delete only exact previewed IDs under optimistic snapshot/hash protection and record an audit event. This pass must implement and test the mechanism but must not apply it to the live Brain.

## Stage 5 — Canonical key and alias registry

Create an alias/canonical-key registry rather than relying on string normalization during every query.

Requirements:

- Lowercase dotted keys are canonical.
- Legacy underscore keys can resolve as aliases.
- Aliases are versioned and auditable.
- Alias resolution cannot merge values by itself.
- Collision detection compares value, scope, authority, freshness, and provenance.
- Collisions produce `merge`, `supersede`, `contradict`, or `keep_separate` proposals.
- `alphaos.swing.plugin_version` and `alphaos_swing_plugin_version` must appear in preview with their different values and provenance. Do not resolve it automatically.
- `server_url` and `server_url@staging` demonstrate scope separation; normalization must not collapse environment-qualified facts.

Add CLI/API/UI views for aliases and collisions, with reverse lookup from an alias to its canonical record.

## Stage 6 — Retrieval planner and context assembly

Implement retrieval as a deterministic multi-lane plan instead of a single blended similarity list.

### Query planning

Resolve:

- task intent;
- project/domain;
- entities and aliases;
- requested/effective time;
- required memory types;
- assurance level;
- token budget.

### Retrieval lanes

Retrieve separately from:

1. exact lexical/canonical-key matches;
2. active project decisions and constraints;
3. applicable procedures;
4. verified fresh facts;
5. open tasks/checkpoints/handoffs;
6. unresolved contradictions/questions;
7. recent episodic events;
8. graph neighbors/multi-hop evidence;
9. semantic-vector candidates.

Fuse with deterministic rank features. Embedding similarity is only one signal.

### Required filters and ranking signals

- lifecycle state;
- authority;
- source validity;
- effective-time match;
- freshness/review horizon;
- project/scope applicability;
- contradiction/supersession state;
- exact key/entity match;
- retrieval lane;
- redundancy/diversity.

Do not compute a universal confidence score. Return the dimensions and an inclusion reason.

### Context packet output

Every packet item must expose:

- record ID/key and statement;
- why it was included;
- authority and lifecycle status;
- scope and effective time;
- source link/hash status;
- contradiction/supersession warning;
- token estimate;
- originating lane and component rank.

Small/Standard/Deep packets should allocate budgets by lane, prevent one source or namespace from dominating, and always include a blocking contradiction that could change the action.

Proposed candidates are excluded by default. A clearly labeled review/debug mode may include them separately, never mixed with active truth.

## Stage 7 — Context quality and memory workbench UI

Make Projects the main route for agent context and add a Memory Quality workbench accessible from Projects, Explore, and Review & Activity.

### Memory Quality overview

Show objective counts:

- structured active records;
- legacy flat records;
- pending AI candidates;
- invalid/missing evidence;
- stale/review-due records;
- unresolved contradictions;
- key collisions;
- suspected fixtures awaiting adjudication;
- status-only facts;
- migration progress by risk tier.

No synthetic health score or percentage grade.

### Human versus AI curation

Every memory card visibly labels:

- User stated
- System verified
- Document extracted
- AI inferred
- Legacy imported

Show author, extractor, reviewer, and source separately. Never use “by Mihir” merely because Mihir reviewed an AI extraction.

### Workbench interactions

- filter by project, authority, record type, state, age, source validity, and risk;
- inspect source excerpt beside the proposed record;
- preview add/merge/supersede/contradict/archive;
- compare canonical and legacy values;
- open related project/task/evidence/graph views;
- keyboard navigation and accessible buttons;
- no raw JSON as the primary presentation, though raw disclosure remains available.

### Opaque memory repair

`car_stickers_status = active` must appear as “needs context,” with prompts for rationale, scope, implication, source, effective time, and next review. Do not invent or modify its value.

## Stage 8 — Nightly consolidation policy

Dream Cycle must emit an explicit proposed operation for every candidate: add, reinforce, merge, supersede, contradict, noop, or archive.

Before suggesting an operation, compare:

- canonical key and aliases;
- entity identity;
- polarity;
- scope/environment;
- effective time;
- authority;
- current active value;
- source overlap;
- semantic similarity.

Rules:

- Similarity alone never authorizes merge.
- Contradictions remain represented until reviewed.
- Reinforcement appends evidence without replacing original provenance.
- Supersession closes temporal validity of the prior record.
- Noop records a compact dedupe reason in runtime telemetry but does not create durable semantic clutter.
- Archive suggestions require a rationale and restoration path.
- Unload the local model on all success/error/timeout paths.

Keep nightly LLM batching. No LLM loads on desktop start, navigation, search, capture, or review.

## Stage 9 — Task-scoped learning and cross-agent handoffs

Convert agent activity into useful task memory without global reputation.

Checkpoint/handoff records should include:

- goal and intended outcome;
- progress completed;
- remaining work;
- files changed;
- commands/tests and results;
- assumptions;
- blockers/unresolved questions;
- evidence/source links;
- next recommended action;
- acceptance criteria;
- producer and intended consumer;
- context packet hash.

Repeated successful approaches may create procedure candidates. Repeated verified failures or user corrections may create lesson candidates. One ambiguous event is insufficient for a universal rule.

Add a “Resume with context” output for Codex, Antigravity, Gemini CLI, and generic terminal agents. It produces a prompt/JSON bundle but does not dispatch agents automatically.

## Stage 10 — Evaluation suite

Add checked-in, deterministic evaluations for:

### Lifecycle

- legal/illegal transitions;
- idempotency;
- optimistic concurrency;
- audit immutability;
- archive/restore;
- supersession chain traversal.

### Migration

- missing rationale/evidence;
- risk classification;
- batch staging without promotion;
- rollback;
- legacy preservation;
- fixture-warning multi-signal adjudication;
- alias collision preview.

### Retrieval

- exact canonical key lookup;
- underscore alias resolution;
- environment/scope separation;
- temporal “what was true then?” questions;
- current superseded truth;
- contradiction inclusion;
- procedure retrieval;
- project-context resumption;
- multi-hop graph retrieval;
- irrelevant-memory resistance;
- source/namespace diversity;
- Small/Standard/Deep budget compliance.

### AI curation

- extractor is not author;
- LLM decisions never auto-promote;
- unsupported rationale rejected or downgraded;
- candidate operation classification;
- actual generated-output metrics clearly separated from schema-fixture metrics.

### Safety

- entire test suite leaves live Brain hashes unchanged;
- previews produce zero writes;
- no model auto-download;
- local model unload on every terminal path;
- desktop browsing triggers no LLM request.

Report retrieval metrics by question class: exact, semantic, temporal, multi-hop, contradiction, procedure, and project resume. Do not hide weak classes behind one aggregate score.

## Suggested implementation layout

Use existing modules where appropriate, but prefer clear ownership:

- `tools/memory_lifecycle.py` — operations, transitions, audit contracts.
- `tools/memory_authority.py` — authority/provenance validation.
- `tools/memory_convention_audit.py` — flat-memory and fixture-warning analysis.
- `tools/memory_aliases.py` — canonical keys, aliases, collisions.
- `tools/context_retrieval_planner.py` — multi-lane planning/fusion.
- `tools/context_packet.py` — deterministic packet assembly/manifests.
- Extend `tools/schemas.py`, `tools/memory_mcp_server.py`, `tools/memoryctl.py`, and `tools/gms_desktop_api.py` through these shared modules rather than duplicating logic.
- Add a focused desktop view/module for Memory Quality instead of expanding `steering.js` indefinitely.

This layout is guidance, not a requirement; preserve backward compatibility and avoid unnecessary rewrites.

## API and CLI requirements

Add versioned, typed interfaces for:

- lifecycle transition preview/apply/history;
- authority/provenance validation;
- convention audit and cleanup preview/apply;
- migration inventory/stage/rollback;
- alias list/resolve/collision preview;
- retrieval plan inspection;
- context packet generation with inclusion manifest;
- structured/flat/stale/source-invalid counts;
- task resume bundles.

All mutation routes require registered identity, substantive rationale where relevant, expected content/snapshot hash, and append-only audit output.

## Acceptance criteria

Pass 7 is complete only when:

1. The canonical convention is enforced through shared code, not documentation alone.
2. Source events, candidates, active records, and superseded/archive history remain distinct.
3. Authority and author/extractor/reviewer roles cannot be conflated.
4. A generic migration preview covers all 90 flat facts without inventing rationale.
5. High/medium-risk memory cannot be bulk-promoted.
6. The 18 fixture warnings have evidence-based adjudication previews but remain untouched live.
7. The AlphaOS key collision is surfaced with both values and remains unresolved live.
8. Context retrieval is lane-aware, temporal, conflict-aware, source-diverse, and explainable.
9. Proposed AI memories remain excluded from normal context packets.
10. Project resume bundles contain task state, decisions, procedures, evidence, and next actions.
11. Mbrain clearly distinguishes user-stated, verified, document-derived, inferred, and legacy memory.
12. No global trust/confidence/health score reappears.
13. The complete test suite passes and tests leave the live Brain byte-for-byte unchanged.
14. Desktop JavaScript syntax and `git diff --check` are clean.
15. No live cleanup, review decision, bulk migration, model download, launchd mutation, or git commit occurred.

## Required verification

```bash
PYTHONPATH=.:tools pytest tests/ -q
find desktop -name '*.js' -exec node --check {} \;
git diff --check
```

Also provide:

- live Brain hash before/after tests;
- read-only convention audit before/after;
- migration preview counts by type/risk/readiness;
- alias/collision preview;
- retrieval evaluation by question class;
- example Small/Standard/Deep packet manifests;
- model-load/unload observation;
- `git status --short`.

## Required Antigravity handoff

Return an outcome-first report containing:

1. baseline and final state;
2. exact files added/changed;
3. architecture and compatibility decisions with rationale;
4. lifecycle transition table;
5. migration workbench behavior and preview counts;
6. fixture-warning adjudication results;
7. alias collision results;
8. retrieval-plan examples and class-level metrics;
9. UI walkthrough by view and action;
10. live-root immutability proof;
11. all verification outputs;
12. limitations and deferred work;
13. confirmation that no forbidden live action or commit occurred.

Stop and report if implementation would require accepting, deleting, merging, or rewriting live memory. Do not infer that authority from this specification.

## Ready-to-paste Antigravity prompt

```text
Implement Mbrain Pass 7 in /Users/mihirdeshpande/projects/global-memory by following docs/MBRAIN_PASS_7_MEMORY_LIFECYCLE_AND_RETRIEVAL_SPEC.md completely. Read docs/GMS_MEMORY_CONVENTIONS_V1.md first. Preserve all existing uncommitted work and icons. Start by proving the 199-test baseline and live-Brain test isolation. Implement shared lifecycle, authority, migration-preview, alias/collision, multi-lane retrieval, context-packet, task-resume, evaluation, API/CLI, and Memory Quality UI behavior. Do not accept/reject the six live candidates, delete the 18 warning claims, resolve the AlphaOS collision, rewrite the 90 flat facts, install a model, alter launchd, or commit. Run all required checks and return the complete evidence-backed handoff.
```
