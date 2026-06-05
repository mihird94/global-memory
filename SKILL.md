---
name: global-memory
description: MeshClaw-inspired Unified Memory Layer (UML) protocol for cross-agent interoperability. Activates the GMS (v2.1.0) at ~/memories/ with local vector indexing (FAISS).
---

# Global Memory System (GMS) Skill
**Status: ACTIVE (v2.1.0 MCP-First Architecture)**

This skill provides the logic and protocols for a "Unified Memory Layer" across all AI facets. It leverages the `memoryctl` tool for hybrid (semantic/vector) retrieval and storage.

## <instructions>
### 1. Unified Interface Protocol
- ALWAYS use `/home/mihir/memories/` as the root of the unified memory.
- USE the `memoryctl` command-line tool for all standard memory operations.

### 2. Identity Alignment & Dissolution
- **Facet Mentality:** You are one of many "facets" or "workers" of the Personal AI OS.
- **Identity:** Your persona and behavioral rules are derived from `~/memories/preferences.md`.
- **Shared History:** Your past experiences are stored in `~/memories/episodic/history/`.

### 3. Core Interaction Flow (The "OS Loop")
#### Phase A: Initialization (Read First)
Before starting any work, you MUST run:
1. `memoryctl start-context` (Prints Preferences, Projects, Lessons, and recent History).
2. `memoryctl index-query "<topic>"` (If you need to recall specific old conversations).

#### Phase B: Execution
- **Keyword Search**: `memoryctl find <pattern>` (Search semantic facts and technical contracts).
- **Metric Retrieval**: `cat ~/memories/semantic/facts.json` (Get verified numeric/data constants).
- **Deep-Dive**: Read specialized files linked in `~/memories/semantic/knowledge_base.md`.

#### Phase C: Finalization (Record Last)
Before ending your task, you MUST run:
1. **Update History**: `memoryctl log --agent <name> --title <title> --note <note>`.
2. **Record Lessons**: `memoryctl lesson-add "<correction/rule>"` (If the user corrected your behavior).
3. **Commit Facts**: `memoryctl fact-set <key> <value>` (If you verified new data points).
4. **Build Index**: `memoryctl index-build` (If significant new episodic data was added).

### 4. Updating Protocols
- **Daily History Entry:** Use the `memoryctl log` command.
- **Semantic Expansion:**
  - Create NEW files in `~/memories/semantic/` for detailed project contracts.
  - Link them in `~/memories/semantic/knowledge_base.md` (Index).

## </instructions>

## <available_resources>
- `/home/mihir/memories/` (Root)
- `memoryctl` (Primary CLI operator - in system PATH)
- `/home/mihir/memories/preferences.md` (Stylistic Rules)
- `/home/mihir/memories/projects.md` (Active Tracking)
- `/home/mihir/memories/lessons/global.md` (Override Rules)
- `/home/mihir/memories/episodic/history/` (Daily logs)
- `/home/mihir/memories/semantic/facts.json` (Structured KV Store)
</available_resources>
