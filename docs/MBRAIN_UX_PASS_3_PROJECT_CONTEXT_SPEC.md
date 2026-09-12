# Mbrain UX Pass 3 — Project Context Workspace

Status: implementation handoff for Antigravity
Authoritative repository: `/Users/mihirdeshpande/projects/global-memory`
Date: 2026-09-08
Do not commit unless Mihir explicitly asks.

## 1. Mission

Build a first-class **Projects** view that makes Mbrain useful for context engineering across Codex, Antigravity, Gemini, terminal agents, scheduled workers, and future harnesses.

The view must answer, for any project:

1. What is this project trying to achieve?
2. What is true now, and when was that state last changed?
3. What decisions were made, why, and what do they imply?
4. What work is active, blocked, waiting for review, or complete?
5. Which agents contributed recently, and what exactly did they change?
6. What evidence supports the claimed state?
7. What context should the next agent receive to resume useful work?

This is not a folder browser, generic dashboard, agent leaderboard, chat archive, or project-management clone. It is a compact control surface for reconstructing and transferring correct working context.

## 2. Where the system is now

Read this section before modifying code. Confirm it against the working tree and Brain rather than assuming it remains current.

### Implemented and verified

- Explore is a clickable master/detail memory workspace.
- Explore defaults to recent activity and supports newest recorded, oldest recorded, and name sorting.
- Memories are grouped into sticky time buckets and show first-recorded versus last-changed timestamps.
- Graph is local-first and Obsidian-inspired, with search, focus, neighbor navigation, filters, physics presets, saved views, and evidence inspectors.
- Concepts has entity browsing, quality/review categories, aliases, and cross-view navigation.
- Daily Notes uses **Process into Memory**; the rejected phrase must not return.
- Review & Activity is now a provenance-oriented page. The user-facing global agent trust model has been retired.
- Durable memory policy now requires rationale, implications, scope, and provenance rather than status-only facts.
- Current automated baseline: **119 tests pass**. Re-run rather than quoting this number as current after edits.

### Current product decisions

1. **No global agent trust score.** Do not display trust, reliability, confidence, reputation, quality, or health as a synthetic agent-level percentage/tier/rank.
2. Agent summaries remain descriptive: identity, harness, project/task, recency, contributions, disputes, review outcomes, and task-scoped verification.
3. Decisions must include rationale. A value such as `retired`, `done`, or `active` is not sufficient context by itself.
4. Heavy LLM concept work belongs in a bounded nightly batch. Opening or browsing Mbrain must not load a model.
5. Mbrain is local-first and must work offline.
6. Mac and mini-PC activity must eventually appear in one coherent project view; host identity is an explicit dimension.

### Existing canonical data and primitives

- Project memory banks: `~/memories/projects/<project>/`
  - `projectBrief.md`
  - `systemPatterns.md`
  - `techContext.md`
  - `activeContext.md`
  - `progress.md`
- Initialized projects currently include `global-memory` and `demo-proj`.
- `brain project-list`, `brain project-get`, and `brain project-update` already operate on those banks.
- SQLite already contains:
  - `gms_tasks`
  - `gms_task_checkpoints`
  - `gms_handoffs`
- CLI/MCP primitives already exist for task create, claim, checkpoint, handoff, resume, complete, and project state.
- At this handoff, `brain project-state global-memory` reports zero durable tasks. Empty task state must therefore be handled gracefully and must not dominate the UI.
- `AppState` already coordinates selected memories/entities and cross-view navigation.

### Known incomplete work from Pass 2

Do not obscure these gaps with UI claims:

- Concept enrichment has scaffolding but no proven production enqueue path.
- The launchd plist exists in the working tree but is not proven installed.
- No complete enrichment status/review surface exists.
- Dream Cycle still lacks the specified global lock, RAM floor, runtime budget, and complete structured-output validation.
- Component clustering is exposed but not fully functional.
- Mission Control, context packets, agent-instance registry, and cross-agent inbox remain specification-level, not production-complete.

### Working-tree warning

The repository is intentionally dirty and contains work from Mihir, Antigravity, and Codex, including desktop icon assets. Preserve all unrelated changes. Do not reset, clean, replace icons, or commit without explicit instruction. Inspect `git status --short` before and after each stage.

## 3. Product model

### 3.1 Project is a context boundary

A project is a durable scope that connects:

- project memory-bank documents;
- tasks, checkpoints, and handoffs;
- decisions with rationale;
- semantic, operational, procedural, and episodic memories;
- entities and graph relationships;
- agents, harnesses, hosts, and activity;
- artifacts, files, commits, tests, and external evidence;
- open questions and required human decisions.

Do not infer project membership solely from substring matching. Membership needs an explicit source when available and a clearly labeled inferred source otherwise.

### 3.2 Required provenance labels

Every assembled item must expose enough metadata to distinguish:

- `explicit`: directly project-tagged or stored in the project bank;
- `linked`: connected through a task, checkpoint, handoff, decision, artifact, or graph edge;
- `inferred`: selected by bounded retrieval/name/path matching;
- `global`: intentionally inherited operating context.

Inferred content must never silently appear as authoritative project truth.

### 3.3 No aggregate project score

Do not create project health, context quality, completion, confidence, or readiness scores. Show explainable component states instead:

- stale active context;
- missing rationale;
- open blocker;
- unverified completion;
- dirty working tree;
- stale checkpoint;
- unresolved decision;
- missing project brief;
- nightly worker failure;
- context packet invalidated.

## 4. Navigation and information architecture

Add a top-level sidebar item named **Projects**, positioned after Exploration and before Review & Activity.

Recommended icon: folder or stacked workspace glyph consistent with the existing visual language. Avoid emoji that visually dominates text.

Projects opens a responsive master/detail workspace:

```text
+--------------------+--------------------------------------+--------------------------+
| PROJECTS           | PROJECT WORKSPACE                    | CONTEXT / INSPECTOR      |
| Search             | global-memory                        | selected item            |
| Recent first       | purpose · current focus · freshness  | provenance               |
|                    |                                      | rationale                |
| global-memory      | Needs attention                      | evidence links           |
| demo-proj          | Current state                        | related items            |
|                    | Decisions                            | open in Explore/Graph     |
|                    | Work and handoffs                    |                          |
|                    | Recent activity                      |                          |
|                    | Relevant knowledge                   |                          |
+--------------------+--------------------------------------+--------------------------+
```

At narrower widths, collapse the inspector into a drawer and keep the project list accessible through a selector. Never require horizontal page scrolling for normal use.

## 5. Project list

### Required behavior

- Discover project names from project memory-bank directories and distinct non-empty `gms_tasks.project` values.
- Merge duplicates deterministically.
- Default sort: most recently changed project context or task activity.
- Other sorts: name, needs attention, recently created if a reliable creation timestamp exists.
- Search project name, stated goal, current focus, and known repository path.
- Persist selected project and sort locally through existing app state/preferences.
- Selecting a project must update the center workspace without a full app reload.

### Project-row content

- Project name.
- One-line purpose from `projectBrief.md`, if meaningful.
- Relative last activity timestamp with exact timestamp in tooltip.
- Explainable attention chips such as `2 open tasks`, `1 stale checkpoint`, or `missing brief`.
- Do not show empty zero badges everywhere.

### Empty and malformed banks

The current `global-memory` project bank contains scaffold placeholders in several sections. Treat placeholder-only documents as missing content, not as real project descriptions. Detect common scaffold lines such as `[Core goals and project scope]` without hard-coding the UI to this one repository.

When content is missing, show one concise remediation action: **Add project brief** or **Open project context**, not a large empty illustration.

## 6. Project workspace

### 6.1 Header

Show:

- project name;
- useful purpose sentence;
- last meaningful change;
- optional repository path/host if explicitly known;
- actions: **Build context packet**, **Copy resume brief**, and overflow menu.

Do not claim a repository link unless verified. Do not infer the current repository path for every project.

### 6.2 Needs attention

This is first only when non-empty. Aggregate:

- tasks blocked or waiting for review;
- expired task leases;
- handoffs awaiting acknowledgement;
- decisions/questions needing user input;
- stale project current-state context;
- claimed completion lacking verification references;
- contradictory active facts or decisions explicitly linked to the project;
- failed scheduled jobs linked to the project.

Each card must state:

- what needs attention;
- why it matters;
- affected task/context;
- responsible agent/host if known;
- concrete next action;
- evidence or source link.

When empty, render one compact inline row: **Nothing currently requires a decision.**

### 6.3 Current state

Render `activeContext.md` as a readable state summary, not raw Markdown in a code block.

Extract and display:

- current focus;
- latest substantive update;
- constraints/do-not-touch boundaries;
- known gaps;
- verification state;
- last updated time and source path.

Provide **View source** and **Edit context**. Editing must preview the exact append/replace operation and preserve existing text by default.

### 6.4 Decisions and rationale

Show accepted and proposed project decisions as first-class cards. A decision card contains:

- question/decision;
- status: proposed, accepted, superseded, rejected;
- rationale;
- implications;
- scope;
- author/participants;
- effective date;
- evidence/source references;
- superseding decision when applicable.

For the current codebase, extract structured decision-shaped facts when they contain fields such as `decision`, `rationale`, `implications`, `scope`, or `provenance`. Also recognize clearly headed decision sections in the project bank, but label parser-derived records as inferred until explicitly registered.

Never render only `status: retired` when a structured rationale is available. Nested structured values should be formatted as labeled sections, not escaped JSON blobs.

### 6.5 Work, checkpoints, and handoffs

Use the existing task primitives rather than inventing frontend-only tasks.

Initial UI may use compact grouped lists instead of a full Kanban board:

- In progress.
- Needs review / handed off.
- Open.
- Completed recently.

Task card fields:

- title and objective;
- status and revision;
- owner agent;
- lease expiry/freshness;
- latest checkpoint label/time;
- latest handoff sender, recipient, next action, and acknowledgement;
- artifacts and verification summary when the task is opened.

Empty task state is normal. Show **No durable tasks recorded for this project** with a small explanation that agent work will appear after using the task/checkpoint protocol. Do not fabricate tasks from git changes or daily notes.

Task detail must use the resume bundle endpoint so checkpoint state and handoff context are inspectable.

### 6.6 Recent agent activity

Show a project-filtered, reverse-chronological timeline of meaningful deltas:

- project-bank update;
- task claim/checkpoint/handoff/completion;
- durable decision created or superseded;
- project-scoped fact promoted/retracted;
- artifact or verification result recorded;
- nightly consolidation outcome.

Collapse noisy repeated events. Clearly distinguish:

- agent-reported claim;
- independently verified test/file evidence;
- human decision;
- scheduled-system activity.

Do not show global agent trust, reliability, reputation, confidence, or rankings.

### 6.7 Relevant knowledge

Provide tabs or compact sections for:

- Memories.
- Concepts/entities.
- Files/artifacts.
- Graph neighborhood.

Every included result needs a **Why here?** explanation based on explicit/linked/inferred/global provenance.

Cross-view actions:

- memory → Explore inspector;
- entity → Concepts inspector;
- entity/relationship → Graph focus;
- task → task detail;
- source file → local file view when available.

Do not load the full graph or run an LLM when the project opens. Fetch heavy evidence lazily.

## 7. Context packet workflow

The primary project action is **Build context packet**. Implement a useful deterministic v1; do not wait for a perfect agent registry.

### 7.1 Packet profiles

- **Small:** objective, current state, constraints, active decisions, acceptance criteria/next action, essential files.
- **Standard:** Small plus recent checkpoints/handoff, relevant memories, known gaps, verification state, and selected graph context.
- **Deep:** Standard plus bounded historical evidence, alternatives considered, and broader architecture context.

### 7.2 Builder UI

The builder must show:

- target agent/harness label entered or selected by the user;
- project and optional task;
- profile;
- included sections with per-section toggles;
- reason each section/item was included;
- source freshness;
- estimated character/token budget;
- exact Markdown preview;
- JSON preview;
- copy/export actions.

For this pass, support copy/export to file. Do not claim direct Antigravity/Codex delivery unless a real supported adapter exists.

### 7.3 Packet requirements

```json
{
  "packet_version": "gms-context-v1",
  "packet_id": "ctx_<stable-id>",
  "created_at": "ISO-8601",
  "project": "global-memory",
  "task_id": null,
  "target": {"agent": "Antigravity", "harness": "Antigravity IDE", "host": "local"},
  "objective": "...",
  "current_state": "...",
  "decisions": [{"decision": "...", "rationale": "...", "source_ref": "..."}],
  "constraints": ["..."],
  "known_gaps": ["..."],
  "recent_work": ["..."],
  "verification": ["..."],
  "files": ["..."],
  "relevant_memories": ["..."],
  "open_questions": ["..."],
  "excluded": ["..."],
  "source_refs": ["..."],
  "freshness": {"status": "fresh|possibly_stale|stale", "reasons": ["..."]},
  "budget": {"profile": "standard", "estimated_tokens": 0},
  "content_hash": "sha256:..."
}
```

Hash canonical JSON with stable key ordering. Repeated builds from identical source revisions and options must produce identical content hashes even if packet IDs differ.

### 7.4 Context-selection rules

- Begin with the selected project, never unrestricted global retrieval.
- Include global preferences/lessons only when routing policy marks them applicable.
- Rank by explicit membership, task linkage, authority, freshness, then semantic relevance.
- Deduplicate repeated summaries.
- Preserve conflicting statements and label the conflict; do not let summarization silently choose one.
- Exclude secrets and cross-project personal context by default.
- A rationale-bearing authoritative decision outranks an episodic mention of the same decision.
- Avoid status-only facts when a richer record or source exists.
- Mbrain open/render paths must not call Ollama. Optional synthesis may be a separately invoked, cached nightly enhancement; deterministic assembly must always work.

## 8. Backend/API contract

Implement canonical APIs in `tools/gms_desktop_api.py`, expose them through HTTP, Electron main/preload, and tests. Suggested interface:

```text
GET  /api/projects
GET  /api/projects/{project_id}
GET  /api/projects/{project_id}/activity?limit=50&before=<cursor>
GET  /api/projects/{project_id}/knowledge?kind=memories|entities|artifacts&limit=...
GET  /api/tasks/{task_id}/resume
POST /api/context-packets/preview
POST /api/context-packets/export
```

### `GET /api/projects`

Return compact list rows only:

```json
{
  "projects": [{
    "project_id": "global-memory",
    "name": "global-memory",
    "purpose": "...",
    "purpose_status": "present|missing|placeholder",
    "last_activity_at": "...",
    "counts": {"open_tasks": 0, "blocked": 0, "pending_handoffs": 0},
    "attention": []
  }]
}
```

### `GET /api/projects/{project_id}`

Return:

- parsed memory-bank sections plus raw/source metadata;
- component freshness;
- task summary from canonical SQLite primitives;
- decisions with provenance classification;
- attention items;
- recent meaningful activity;
- known repository/host metadata only when explicit.

Path safety is mandatory. Resolve project IDs against discovered allowed project directories; reject traversal and arbitrary filesystem paths.

### Project timestamps

Use the newest reliable timestamp across memory-bank file mtimes and project task/checkpoint/handoff activity. Return exact ISO timestamps. Relative labels belong in the frontend.

### Parsing Markdown

Keep a tolerant deterministic parser. Preserve raw Markdown and source ranges. Never use an LLM during request handling. A malformed section must degrade locally rather than making the entire project unavailable.

### Compatibility

- Reuse existing `mem_project`, `mem_project_state`, and task-resume semantics where possible.
- Do not duplicate tasks into a second desktop-only store.
- Keep existing CLI/MCP behavior working.
- Do not rename or destructively migrate legacy reputation tables in this pass.

## 9. Frontend implementation

Recommended files:

- `desktop/src/views/projects_view.js`
- `desktop/src/project_context.js` for pure parsing/presentation helpers if useful
- existing `desktop/src/app_state.js` for selection state
- `desktop/src/styles.css`
- `desktop/src/index.html`
- `desktop/src/app.js`
- `desktop/preload.js`
- `desktop/main.js`

Keep helper functions pure where possible so they can be tested without Electron.

### Interaction requirements

- Project rows and all knowledge cards are keyboard accessible.
- Preserve selected project on navigation away/back.
- Escape untrusted text before inserting HTML.
- Render trusted formatting through a controlled Markdown renderer or small allowlist; never inject raw stored HTML.
- Provide loading, partial-error, empty, and stale states at section level.
- One failed subsection must not blank the whole project page.
- Avoid inline styles for the new view; use named CSS classes.

## 10. Rationale-first memory rendering

Improve the Explore/project inspector for structured decision facts as part of this pass:

- Detect objects containing `decision`, `rationale`, `implications`, `scope`, `provenance`, `evidence`, or `review_condition`.
- Render these as labeled human-readable sections.
- Keep **Raw JSON** available behind a disclosure.
- Highlight missing rationale on decision-shaped facts.
- Display embedded agent/date provenance when file-level provenance is only `system`.
- Prefer the embedded provenance label while still showing the storage source separately.

This directly fixes the observed failure where `mbrain.agent_trust_ui` appeared as only `retired` and the source author appeared as `system` even though the decision came from a user correction recorded by Codex.

## 11. Tests

Add deterministic coverage for at least:

### Backend

- project discovery from memory banks;
- task-only project discovery;
- duplicate merge;
- placeholder brief detection;
- last-activity ordering;
- missing/malformed bank sections;
- project ID traversal rejection;
- empty task state;
- task/checkpoint/handoff aggregation;
- structured decision extraction with rationale;
- explicit versus linked versus inferred provenance labels;
- context packet deterministic hash;
- Small/Standard/Deep inclusion boundaries;
- cross-project exclusion;
- secret-reference redaction;
- conflict preservation;
- no Ollama/network calls while listing/opening projects.

### Frontend/pure helpers

- project sort/search;
- selected-project persistence;
- relative time formatting;
- structured decision rendering;
- compact empty states;
- safe escaping;
- context builder toggles and budget updates;
- cross-view navigation payloads.

### Regression

- Existing Explore recency behavior remains intact.
- Review & Activity still has no global agent score/tier.
- Graph/Concept selection state remains intact.
- Daily Notes terminology remains **Process into Memory**.
- Existing task/MCP/CLI concurrency tests continue to pass.

## 12. Performance and privacy budgets

- Project list response target: under 150 ms for 100 local project banks after warm filesystem cache.
- Initial project detail target: under 300 ms without graph expansion.
- Paginate activity and knowledge lists.
- Lazy-load graph neighbors and full task resume bundles.
- Cache parsed project-bank files keyed by path, mtime, and size.
- Never send project content to a network service during display, search, or deterministic packet assembly.
- Never include credentials; use secret names/references only.
- Log packet exports with hash and destination label, not secret content.

## 13. Staged execution

### Stage 0 — Audit and fixtures

1. Read this entire specification and `SKILL.md`.
2. Run `brain start-context`, `brain project-get global-memory`, and relevant index queries.
3. Inspect `git status --short`; preserve all current changes.
4. Run the full test baseline and JS syntax checks.
5. Create temporary test fixtures for complete, placeholder, malformed, and task-only projects.
6. Record an evidence-rich Brain checkpoint with rationale and current findings.

### Stage 1 — Read-only Project View P0

1. Implement project discovery and safe project-detail APIs.
2. Add sidebar navigation and master/detail workspace.
3. Render project brief/current state/progress with compact empty states.
4. Aggregate existing tasks, checkpoints, and handoffs read-only.
5. Add recent project activity.
6. Add tests and verify offline behavior.

### Stage 2 — Decisions and relevant knowledge

1. Extract/display rationale-first project decisions.
2. Add project-scoped memories/entities/artifacts with **Why here?** provenance.
3. Add cross-view navigation.
4. Improve structured fact rendering in Explore.
5. Add tests for provenance and cross-project boundaries.

### Stage 3 — Deterministic context packets

1. Implement Small/Standard/Deep deterministic assembly.
2. Add preview, inclusion controls, freshness, budget, canonical hash, copy, and export.
3. Add Antigravity IDE prompt/file format, but no automatic GUI delivery.
4. Add privacy/redaction and reproducibility tests.

### Stage 4 — Hardening and handoff

1. Run full tests, JS checks, and `git diff --check`.
2. Test production memory data without mutating it.
3. Perform visual QA at wide and narrow desktop sizes.
4. Verify app open/project browsing performs no LLM/network call.
5. Update README and Brain with rationale-rich progress.
6. Stop and provide an exact review handoff; do not begin unrelated Mission Control or nightly-enrichment work.

## 14. Acceptance criteria

1. Projects is a top-level working view, not a static list.
2. It discovers all initialized and task-linked projects safely.
3. Default ordering is recent meaningful activity.
4. Selecting a project reveals purpose, current state, rationale-bearing decisions, work/handoffs, activity, and relevant knowledge.
5. Placeholder/missing content is labeled honestly.
6. Empty task state consumes minimal space.
7. Every assembled knowledge item explains why it belongs to the project.
8. No global agent/project trust, reliability, confidence, reputation, quality, or health score appears.
9. Structured decisions render rationale and provenance prominently.
10. Small/Standard/Deep context packets can be previewed and copied/exported as Markdown and JSON.
11. Packets are deterministic, hashed, freshness-aware, scoped, and redact secrets.
12. Antigravity can resume the next task from the exported Standard packet without reading the full prior conversation.
13. Mac/mini-PC host identity can be represented without duplicating the same logical project.
14. Existing task concurrency/revision semantics remain canonical.
15. Existing functionality and the full automated suite remain green.

## 15. Explicit non-goals for this pass

- Full Mission Control with live process control.
- GUI scraping or automation of Antigravity.
- Directly sending prompts to unsupported harness APIs.
- Replacing SQLite or the project memory-bank files.
- A full Kanban/task editor if it jeopardizes the core read/context workflow.
- Automatic cross-project context leakage.
- LLM summarization on project open.
- Automatic decision making or conflict resolution.
- Global agent or project scoring.
- Destructive migration of legacy reputation storage.
- Completing unrelated nightly concept-enrichment gaps.

## 16. Antigravity execution prompt

Copy the following into Antigravity:

```text
Implement Mbrain UX Pass 3 from:
/Users/mihirdeshpande/projects/global-memory/docs/MBRAIN_UX_PASS_3_PROJECT_CONTEXT_SPEC.md

You are continuing an intentionally dirty shared working tree. Read the entire spec and /Users/mihirdeshpande/projects/global-memory/SKILL.md before acting. Run Brain start/project/index context, inspect git status, and run the current test baseline. Preserve all user, Antigravity, and Codex changes, especially desktop icon assets. Do not reset, clean, commit, or rewrite unrelated files.

Where we are: Explore recency/master-detail, the Obsidian-like Graph, Concepts review/navigation, Daily Notes terminology, and provenance-oriented Review & Activity are implemented. Global agent trust has been retired from the product. Durable decisions must include rationale, implications, scope, and provenance. The last verified baseline was 119 passing tests, but verify it yourself. Multi-agent Mission Control and context packets are not yet implemented. Project task/checkpoint/handoff primitives already exist in SQLite/MCP/CLI, while global-memory currently has no durable task records. Nightly concept enrichment remains incomplete and is out of scope for this pass.

Implement the pass in Stages 0–4. Prioritize a useful read-only Project View and deterministic context-packet workflow. Do not add synthetic trust/reliability/health scores. Do not load an LLM or call the network when Mbrain opens or a project is viewed. Use canonical existing project/task stores, show rationale and provenance, explain why retrieved context is included, and preserve privacy/project boundaries.

After every stage, run relevant tests and record a rationale-rich Brain checkpoint. At completion, stop for review and report: exact files changed, APIs/schema changes, screenshots or visual QA, test commands/results, performance observations, known limitations, working-tree status, and recommended review focus. Do not start the next pass automatically.
```

## 17. Required completion report

Antigravity's handoff must contain:

- stage-by-stage status;
- changed files and why each changed;
- API contracts added/changed;
- any schema migration and rollback/compatibility notes;
- screenshots of project list, populated project, empty task state, structured decision, and packet preview;
- full test and syntax-check results;
- evidence that project browsing made no LLM/network request;
- performance measurements and fixture size;
- privacy/path-traversal checks;
- unresolved limitations;
- exact Brain records written;
- `git status --short` with unrelated pre-existing changes distinguished from this pass.
