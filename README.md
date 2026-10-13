# Brain — Central Memory & Knowledge System

**Brain** (formerly Global Memory System / GMS) is the local-first, zero-cloud central memory and knowledge engine for multi-agent workflows in the Personal AI OS (Mihir-OS).

It exposes a unified memory substrate through stdio MCP server (`brain_*` / `mem_*`), the single-syllable `brain` CLI operator, and an SSH-friendly terminal UI.

---

## Key Capabilities

- **Sub-5ms Temporal Knowledge Graph RAG:** Local SQLite graph substrate (`gms_entities` & `gms_relationships`) with `valid_from` / `valid_to` edge timestamps and NetworkX 1-hop & 2-hop topological traversal.
- **LightRAG Dual-Level Retrieval:** Supports Low-Level (exact entity-relation triples), High-Level (thematic vector RRF), and Hybrid retrieval.
- **Instant Memory Timeline (`brain latest`):** Fetch recent log milestones and claim updates instantly without guessing dates.
- **Cline Memory Bank Projects (`brain project-*`):** Standardized, structured project memory banks (`projectBrief.md`, `systemPatterns.md`, `techContext.md`, `activeContext.md`, `progress.md`) stored under `~/memories/projects/<project>/`.
- **Per-Day Episodic Journal Logs:** Per-day markdown history files in `~/memories/episodic/history/YYYY-MM-DD.md` with nightly automated Dream Cycle consolidation (03:00 cron).
- **Trust-Gated Claim Ledger:** Versioned claim provenance, Jøsang-style Beta reputation, and reviewer-weighted quarantine resolution.

---

## Main Entry Points

- **Primary CLI:** `brain` (symlinked via `~/.local/bin/brain` $\to$ `tools/memoryctl.py`)
- **Backward Compatible CLI Alias:** `memoryctl`
- **MCP Server:** `tools/memory_mcp_server.py` (Exposes `brain_*` and `mem_*` stdio JSON-RPC 2.0 tools)
- **Dream Cycle:** `tools/dream_cycle.py` (03:00 cron consolidation)
- **Terminal UI:** `brain tui`
- **Eval Harness:** `tools/gms_eval.py`

Experimental promotion mechanisms and benchmark studies live in the optional
[research workspace](research_harness/README.md). The memory runtime does not
import research code. Run product tests with `.venv/bin/python -m pytest` and
research tests separately with `PYTHONPATH=.:tools .venv/bin/python -m pytest research_harness/tests`.

---

## Quick Start Commands

```bash
# 1. Start-up context bundle
brain start-context

# 2. Sub-5ms Knowledge Graph topology lookup
brain graph-show Codex

# 3. LightRAG search (Low-level entity triples + High-level RRF)
brain index-query "Optimus execution contract"

# 4. Instant memory timeline
brain latest --limit 10

# 5. Project Memory Bank management (Cline style)
brain project-init alphaos
brain project-get alphaos --section active
brain project-update alphaos --section active --content "Completed milestone X"

# 6. Log an episodic milestone
brain log --agent "Antigravity" --title "Deployed Brain Engine" --note "Verified sub-5ms graph lookups."
```

---

## MCP Tools Reference (`brain_*` & `mem_*`)

The local server exposes 59 capabilities under both prefixes (118 registered
names). The aliases have identical schemas and convention-aware descriptions.

- `brain_session_start` / `mem_session_start`: Load complete context bundle on session start.
- `brain_search` / `mem_search`: LightRAG dual-level search (`mode="low"`, `"high"`, `"hybrid"`).
- `brain_graph_query` / `mem_graph_query`: Query Knowledge Graph 1-hop & 2-hop Mermaid topology.
- `brain_graph_extract` / `mem_graph_extract`: Extract `(Subject -> Predicate -> Object)` triples from text.
- `brain_latest` / `mem_latest`: Instant timeline lookup of recent milestones and claims.
- `brain_project` / `mem_project`: Manage Cline Memory Bank style project documentation.
- `brain_save_typed` / `mem_save_typed`: Save typed memory facts (semantic, operational, procedural).
- `brain_log_event` / `mem_log_event`: Append episodic milestone entry.
- `brain_context_packet` / `mem_context_packet`: Build a conflict/time-aware, evidence-labeled context packet for agent resumption.
- `brain_curation` / `mem_curation`: Preview/apply audited system curation and owner contests.
- `brain_memory_quality` / `mem_memory_quality`: Run convention, pollution, and candidate-source integrity audits.
- `brain_memory_repair` / `mem_memory_repair`: Analyze evidence and preview/apply guarded legacy-memory repair.
- `brain_lifecycle` / `mem_lifecycle`: Inspect history or preview/apply audited lifecycle transitions.
- `brain_aliases` / `mem_aliases`: Resolve keys and preview/apply recoverable canonical collision consolidation.
- `brain_project_timeline` / `mem_project_timeline`: Read unified evidence-linked project activity.

---

## Repository Documentation

- [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md): Implemented architecture, database schemas, and data flow.
- [ROADMAP.md](ROADMAP.md): Product roadmap and research benchmarks.
- [SKILL.md](SKILL.md): Skill-facing usage contract for agents.
