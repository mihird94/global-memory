---
name: global-memory
description: Unified Memory Layer (UML) protocol for cross-agent interoperability. Activates GMS (v2.2.0) with 10-lane hybrid retrieval, in-process FastEmbed ONNX dense fallback, pre-edit risk guards (file-context), automatic error learning (learn-error), and 3/3 adversarial defenses at ~/memories/.
---

# Global Memory System (GMS) Skill
**Status: ACTIVE (v2.2.0 Multi-Agent Epistemic OS)**

This skill provides the logic and protocols for a "Unified Memory Layer" across all AI facets. It leverages the `memoryctl` tool for hybrid (semantic/vector) retrieval and storage.

## <instructions>
### 1. Unified Interface Protocol & Dual-Tier Architecture
- **Unified Root:** ALWAYS use `${MEMORY_ROOT:-$HOME/memories}` as the memory root.
- **Primary CLI:** Use the `brain` command-line operator (`~/.local/bin/brain`) for all memory operations (`memoryctl` remains a backward-compatible alias).
- **Dual-Tier Operating Protocol:**
  - **Tier 1 (Terminal & Mobile Read Layer):** Direct `brain` CLI + Local Ollama execution (`brain latest`, `brain project-get`, `brain synthesize`, `brain audit`). Provides instant mobile (Termius) and SSH status checks with zero API cost and zero agent session overhead.
  - **Tier 2 (Interactive Reasoning Layer):** Gemini CLI, Codex, and Antigravity for deep development, refactoring, and trading execution, reading/updating Brain as the persistent context layer.

### 2. Identity Alignment & Dissolution
- **Facet Mentality:** You are one of many "facets" or "workers" of the Personal AI OS.
- **Identity:** Your persona and behavioral rules are derived from `${MEMORY_ROOT:-$HOME/memories}/preferences.md`.
- **Shared History:** Your past experiences are stored in `${MEMORY_ROOT:-$HOME/memories}/episodic/history/`.

### 3. Core Interaction Flow (The "OS Loop")
#### Phase A: Initialization (Read First)
Before starting any work, you MUST run:
1. `memoryctl start-context` (Prints Preferences, Projects, Lessons, and recent History).
2. `mem_project(action="get", project="<name>")` or `memoryctl project-get <project>` (Reads the project's memory bank context).
3. `memoryctl index-query "<topic>"` (If you need to recall specific old conversations).

#### Phase B: Execution
- **Instant Memory Timeline**: `mem_latest` (MCP) or `memoryctl latest` (CLI) — Fetch recent milestones and fact updates without guessing dates.
- **Project Memory Bank (Cline Style)**: `mem_project` (MCP) or `memoryctl project-get/update` (CLI) — Manage structured project documentation (`projectBrief.md`, `systemPatterns.md`, `techContext.md`, `activeContext.md`, `progress.md`).
- **LightRAG Search**: `mem_search` (MCP tool) or `memoryctl index-query "<query>"` (Hybrid vector + graph retrieval).
  - Mode `"low"`: 1-hop & 2-hop entity-relationship triples.
  - Mode `"high"`: Thematic vector chunks.
  - Mode `"hybrid"`: Combined entity triples + vector RRF.
- **Knowledge Graph Traversal**:
  - MCP: `mem_graph_query` (Returns Mermaid diagrams) or `mem_graph_extract` (Extracts triples).
  - CLI: `memoryctl graph-query <entity>` (JSON) or `memoryctl graph-show <entity>` (ASCII tree topology).
- **Keyword Search**: `memoryctl find <pattern>` (Search semantic facts and technical contracts).
- **Autonomous Context Curation**: `memoryctl harvest-status` (queue summary), `memoryctl harvest-curate` (preview system decisions), `memoryctl harvest-curate --apply` (evidence-gated promotion/rejection), and `memoryctl harvest-contest <id> --rationale "..." --apply` (owner contest and prior-value restoration). Manual `harvest-review` remains available for exceptional edits.
- **Project Briefing & Continuity**:
  - Structured Briefing: `memoryctl project-briefing --project <name>` (Answers the 10 operational questions).
  - Briefing Explanation: `memoryctl project-briefing explain --project <name>` (Human/agent narrative).
  - Resumption Bundle: `memoryctl task-resume build --project <name> --format [antigravity|codex|gemini]` (Prompt package).
  - Morning Briefing: `memoryctl morning-briefing get --project <name>` (Overnight changes, blockers, next action).
  - Resumption Benchmark: `memoryctl eval-resumption run` (Deterministic 10-scenario continuity benchmark).
- **Decision Intelligence & Action Inbox**:
  - Decisions: `memoryctl decision list --project <name>`, `memoryctl decision impact --decision-id <id>`
  - Action Inbox: `memoryctl action-inbox list --project <name>`, `memoryctl action-inbox preview --inbox-id <id>` (Zero durable writes preview).
  - Memory Repair: `memoryctl memory-repair analyze --key <key>`, `memoryctl memory-repair evidence --key <key>`.
- **Coding Agent Developer Guards & Learning**:
  - File Pre-Edit Guard: `mem_file_context` / `brain_file_context` or `memoryctl file-context <file_path> [--project <name>]` (Pre-flight gotchas, constraints, and past bug lessons before editing a file).
  - Error Trace Crystallization: `mem_learn_error` / `brain_learn_error` or `memoryctl learn-error "<trace>" [--command <cmd>]` (Automatically crystallize terminal, compiler, or test error traces into reusable procedural rules).
- **MCP-Native Context Governance**:
  - Context packet: `mem_context_packet` / `brain_context_packet`.
  - System curation and owner contest: `mem_curation` / `brain_curation`.
  - Quality, repair, and lifecycle: `mem_memory_quality`, `mem_memory_repair`, `mem_lifecycle` (or `brain_*` aliases).
  - Canonical aliases and project history: `mem_aliases`, `mem_project_timeline` (or `brain_*` aliases).
  - Mutation-capable actions preview by default and require an explicit `*_apply` action plus the tool-specific actor, rationale, evidence, and concurrency guard.
- **Metric Retrieval**: `cat ${MEMORY_ROOT:-$HOME/memories}/semantic/facts.json` (Get verified numeric/data constants).
- **Deep-Dive**: Read specialized files linked in `${MEMORY_ROOT:-$HOME/memories}/semantic/knowledge_base.md`.

#### Context Engineering Contract
GMS exists to help the next agent reconstruct the right working context, not merely to record that something happened.

- Never store a bare status such as `done`, `retired`, `active`, or `blocked` when the rationale affects future decisions.
- For durable decisions, record: **decision/status**, **rationale**, **implications**, **scope**, and **provenance**. Add supporting evidence, alternatives rejected, or a review condition when they materially change how the memory should be used.
- Write the explanation at the semantic layer where it will be retrieved. A detailed episodic log does not make an opaque semantic fact self-explanatory.
- Prefer a compact structured object for machine-consumed facts, for example:
  `{"status":"retired","rationale":"...","implications":["..."],"scope":"...","provenance":{"agent":"Codex","date":"YYYY-MM-DD"}}`
- Keep claims inspectable rather than collapsing context into synthetic confidence or global agent-trust scores. Preserve source, recency, disputes, and task-scoped outcomes as separate dimensions.
- Before finalizing, ask: **Could an agent encountering only this fact understand why it is true, when it applies, and what to do differently?** If not, enrich it or link it to the authoritative project or semantic note.
- Follow the canonical lifecycle, authority, naming, evidence, consolidation, retrieval, freshness, and evaluation rules in `docs/GMS_MEMORY_CONVENTIONS_V1.md`.
- Use lowercase dotted canonical keys. Treat underscore/dotted collisions as merge candidates rather than independent truths.
- Keep source event, AI interpretation, and accepted memory distinct. `extractor` is not `author`; an AI may not impersonate the user or invent missing rationale.
- Default posture is **system decides, owner may contest**. Schema-valid candidates with resolvable source evidence may become active through the audited system curator. Every decision must preserve its rationale, evidence-integrity warnings, resulting claim, and superseded claim so a later owner contest can restore prior truth. Missing sources, malformed context, unresolved destructive authority, and policies superseded by a newer owner instruction fail closed.
- Retrieval must be conflict-aware and time-aware: include active decisions, relevant procedures, freshness, supersession, and unresolved contradictions—not only nearest semantic chunks.
- Static fixtures validate contracts only. Attribute quality metrics to an LLM only when that model actually generated the evaluated outputs.

#### Episodic Writing Contract
Write an episode when work changes what a future agent needs to know: a verified milestone, material external-state change, user correction, failed approach with a reusable lesson, decision event, handoff, deployment, or newly discovered blocker. Do not create episodes for routine reads, unchanged monitoring, speculative thoughts, duplicate progress narration, or bare statuses.

Every useful episode should state: **project/task**, **what changed**, **why it matters**, **actor**, **event/observation time**, **evidence or verification**, **resulting state**, **remaining uncertainty/blockers**, and **next action**. Link claim, decision, task, artifact, or source references when available.

Episodes are append-only event evidence, not the current semantic truth. If an event establishes or changes a durable decision, policy, procedure, preference, or project state, update the appropriate structured semantic/project record separately and link the episode. Do not rely on a journal entry to supply rationale that the retrieved semantic record lacks.

#### Phase C: Finalization (Record Last)
Before ending your task, you MUST run:
1. **Update Project Memory Bank**: `mem_project(action="update", project="<name>", section="active", content="...")` or `memoryctl project-update <project> --section active --content "..."`.
2. **Update History**: `memoryctl log --agent <name> --title <title> --note <note>`. Follow the Episodic Writing Contract: log only material context changes, and include why, evidence, resulting state, uncertainty, and next action—not only an activity/status statement.
3. **Record Lessons**: `memoryctl lesson-add "<correction/rule>"` (If the user corrected your behavior).
4. **Commit Facts**: `memoryctl fact-set <key> <value>` (If you verified new data points). For decisions or policies, use the Context Engineering Contract above; do not write status-only values.
5. **Build Index & Graph**: `memoryctl index-build && memoryctl graph-build` (If new episodic data or relationships were added).

### 4. Updating Protocols
- **Daily History Entry:** Use the `memoryctl log` command.
- **Semantic Expansion:**
  - Create NEW files in `${MEMORY_ROOT:-$HOME/memories}/semantic/` for detailed project contracts.
  - Link them in `${MEMORY_ROOT:-$HOME/memories}/semantic/knowledge_base.md` (Index).

## </instructions>

## <available_resources>
- `${MEMORY_ROOT:-$HOME/memories}/` (Root)
- `memoryctl` (Primary CLI operator - in system PATH)
- `memory_mcp_server.py` (Stdio MCP server providing mem_search, mem_graph_query, mem_graph_extract)
- `${MEMORY_ROOT:-$HOME/memories}/preferences.md` (Stylistic Rules)
- `${MEMORY_ROOT:-$HOME/memories}/projects.md` (Active Tracking)
- `${MEMORY_ROOT:-$HOME/memories}/lessons/global.md` (Override Rules)
- `${MEMORY_ROOT:-$HOME/memories}/episodic/history/` (Daily logs)
- `${MEMORY_ROOT:-$HOME/memories}/semantic/facts.json` (Structured KV Store)
- `${MEMORY_ROOT:-$HOME/memories}/gms_trust.sqlite` (GMS Claims, Task Checkpoints, & gms_entities/gms_relationships Graph Tables)
</available_resources>
