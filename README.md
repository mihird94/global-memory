# Global Memory System

GMS is a local-first memory system for multi-agent workflows. It exposes the same memory substrate through an MCP server, a Python CLI, and an SSH-friendly terminal UI.

This repository is the project home for the current `v2.1.x` line.

## What It Does

- Stores typed memory across `semantic`, `operational`, `procedural`, and episodic layers
- Applies trust-gated writes with quarantine, reviewer weighting, and claim history
- Consolidates episodic activity through a nightly Dream Cycle
- Supports semantic retrieval, claim inspection, drift reporting, calibration reporting, and retention pruning
- Provides an SSH-friendly curses TUI for day-to-day operations

## Main Entry Points

- CLI wrapper: `tools/memoryctl`
- CLI module: `tools/memoryctl.py`
- MCP server: `tools/memory_mcp_server.py`
- Dream Cycle: `tools/dream_cycle.py`
- TUI: `memoryctl tui`
- Eval harness: `tools/gms_eval.py`

## Repository Docs

- [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md): implemented architecture and data flow
- [ROADMAP.md](ROADMAP.md): roadmap, research-derived direction, and remaining work
- [PROJECT_MIGRATION_PLAN.md](PROJECT_MIGRATION_PLAN.md): move from global skills to project scope
- [research/README.md](research/README.md): research corpus index
- [SKILL.md](SKILL.md): skill-facing usage contract for agents

## Requirements

- Python 3.11+ recommended
- Optional local virtualenv at `.venv/`
- Optional Ollama endpoint for embeddings and Dream Cycle fallback LLM work
- A writable memory root, defaulting to `~/memories`

Important environment variables:

- `MEMORY_ROOT`: override memory storage root
- `OLLAMA_URL`: override local Ollama endpoint
- `MEMORY_EMBED_MODEL`: override embedding model
- `MEMORYCTL_PATH`: override the CLI path used by the MCP server

## Installation

Use the wrapper directly from the repo:

```bash
cd /path/to/global-memory
tools/memoryctl --help
```

The wrapper prefers `.venv/bin/python` when present and falls back to `python3`.

If you want `memoryctl` on your shell `PATH`, symlink the wrapper:

```bash
ln -sf /path/to/global-memory/tools/memoryctl ~/.local/bin/memoryctl
```

## MCP Usage

Codex and other MCP-capable agents can register the server at `tools/memory_mcp_server.py`.

Example `~/.codex/config.toml` shape:

```toml
[[mcp_servers]]
name = "memory"
command = ["/path/to/global-memory/.venv/bin/python", "/path/to/global-memory/tools/memory_mcp_server.py"]
```

Core MCP tools:

- `mem_session_start`
- `mem_session_end`
- `mem_judge`
- `mem_save_fact`
- `mem_log_event`
- `mem_add_lesson`
- `mem_search`
- `mem_context`
- `mem_get_facts`
- `mem_stats`

## CLI Usage

Show the command surface:

```bash
tools/memoryctl --help
```

Common commands:

```bash
tools/memoryctl start-context
tools/memoryctl find trust
tools/memoryctl log --agent Codex --title "Docs update" --note "Added README and system design documentation."
tools/memoryctl fact-set gms_repo_path "/path/to/global-memory"
tools/memoryctl trust-list
tools/memoryctl quarantine-list
tools/memoryctl claims-list --limit 20
tools/memoryctl drift-status
tools/memoryctl calibration-report
tools/memoryctl retention-report
```

Quarantine workflow:

```bash
tools/memoryctl quarantine-review-add --key semantic:deploy_policy --agent-id worker --reviewer-id reviewer --rating endorse --rationale "Matches observed behavior."
tools/memoryctl quarantine-recommendation --key semantic:deploy_policy --agent-id worker
tools/memoryctl quarantine-resolve --key semantic:deploy_policy --agent-id worker --action promote --agent operator
```

## Terminal UI

Launch:

```bash
tools/memoryctl tui
```

Keyboard:

- `Tab`, `h`, `l`, or arrow keys: switch tabs
- `j` and `k`: move selection
- `Enter`: open selected detail view
- `r`: refresh
- `f`: set a filter
- `c`: clear the active filter
- `q` or `Esc`: back out or quit

Quarantine actions:

- `p`: promote
- `d`: discard
- `e`: endorse
- `x`: reject
- `a`: abstain

Mouse:

- Left-click tabs to switch views
- Left-click list rows in `Quarantine` and `Claims`
- Left-click in detail view to return

If you run inside `tmux`, enable mouse passthrough:

```bash
tmux set -g mouse on
```

## Memory Layout

Default layout under `MEMORY_ROOT`:

```text
semantic/
operational/
procedural/
episodic/history/
lessons/
gms_trust.sqlite
```

High-level storage model:

- `facts.json` files hold current typed fact state
- `gms_trust.sqlite` holds trust, claims, provenance, quarantine, procedures, and graph relations
- episodic markdown files preserve activity history

## Dream Cycle

The Dream Cycle is the nightly consolidation job:

- Reads recent episodic material
- Extracts durable facts through a bounded provider cascade
- Routes new facts through the trust gate instead of writing directly
- Optionally rebuilds the embedding index
- Produces retention and calibration signals

The repo expects this to run from cron rather than manual invocation during normal use.

## Evaluation

Run the full test suite:

```bash
python3 -m unittest discover -s tests -v
```

Run the deterministic eval harness:

```bash
python3 tools/gms_eval.py
```

## Current Status

The architectural core is in place:

- trust-gated write path
- typed routing
- versioned claims
- reviewer-weighted quarantine
- semantic drift reporting
- Dawid-Skene-style calibration
- retention pruning
- curses TUI

The remaining work is mostly operator-surface refinement and deeper benchmark coverage. See [ROADMAP.md](ROADMAP.md).
