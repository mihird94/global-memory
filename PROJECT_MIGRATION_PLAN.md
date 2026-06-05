# GMS Project Migration Plan

Date: 2026-06-04

Status:
- Repo move completed to `/home/mihir/projects/global-memory`
- Backward-compatible symlink left at `/home/mihir/global_skills/global-memory`
- Codex and Gemini MCP registrations updated to the new project path
- Direct CLI fallback preserved through the existing `memoryctl` wrapper

## Goal

Move GMS from:

- `/home/mihir/projects/global-memory`

to a project-scoped location, most likely:

- `/home/mihir/projects/global-memory`

without breaking MCP registration, local tooling, automation, or path-bearing documentation.

## Why This Should Be A Separate Migration

The current roadmap work changed runtime behavior, tests, and tooling. The repo move touches external registries and machine-local paths, so it should not be mixed with feature work.

## Confirmed Path-Bearing Surfaces

### Runtime / Tooling

- [tools/memory_mcp_server.py](/home/mihir/projects/global-memory/tools/memory_mcp_server.py:18)
  - Example MCP installation snippets hardcode the current repo path.
  - `MEMORYCTL_PATH` defaults to the current repo path.

- [tools/dream_cycle.py](/home/mihir/projects/global-memory/tools/dream_cycle.py:15)
  - Cron example hardcodes the current repo path.
  - Internal `memoryctl` path also hardcodes the current repo path.

- [tools/generate_research.py](/home/mihir/projects/global-memory/tools/generate_research.py:5)
  - Research directory path is hardcoded to the current repo.

- [tools/memoryctl](/home/mihir/projects/global-memory/tools/memoryctl:1)
  - Wrapper script is repo-relative and should survive the move if preserved as-is.

### External Agent Config

- `~/.gemini/settings.json`
  - Current memory MCP registration points at the old repo path.

- `~/.codex/config.toml`
  - Contains both:
    - a trusted project entry for `/home/mihir/projects/global-memory`
    - the memory MCP server registration pointing at the old repo path

- `~/.gemini/config/projects/*.json`
  - Multiple cached Gemini project records point at the old folder URI.

### Agent Steering / Fallback Protocols

- [SKILL.md](/home/mihir/projects/global-memory/SKILL.md:1)
  - Uses `memoryctl` as the fallback CLI contract.

- `~/.codex/AGENTS.md`
- `~/.gemini/GEMINI.md`
- `~/projects/optimus-musings-main/AGENTS.md`
  - These rely on `memoryctl start-context`, `memoryctl log`, and `memoryctl fact-set` behavior remaining stable after the move.

### Antigravity / Scratch References

- `~/.gemini/antigravity-cli/...`
  - Contains prior generated plans and scratch files with old absolute repo paths.
  - These are not core runtime dependencies, but they will become stale after the move.

### Generated Docs / Research Links

- `research/papers/*.md`
  - Many files embed `file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py`.

- [research/README.md](/home/mihir/projects/global-memory/research/README.md:1)
  - Should be regenerated or rewritten consistently if repo location becomes part of links.

### Delegation / Internal Notes

- `ANTIGRAVITY_PHASE*.md`
  - These contain the current repo path and can either be updated or archived after migration.

## Recommended Migration Sequence

1. Stabilize current accepted phases in-place.
2. Replace internal code hardcodes with repo-relative derivation where possible.
3. Move the repo to `/home/mihir/projects/global-memory`.
4. Update external config files:
   - `~/.gemini/settings.json`
   - `~/.codex/config.toml`
   - any cron or launcher entries
5. Regenerate or rewrite generated research/doc links.
6. Run full validations from the new location.
7. Log the migration into GMS memory and update user-facing setup docs.

## Code Changes To Prefer Before The Move

Reduce path fragility first:

- Derive repo root from `__file__` in Python tools.
- Derive sibling tool paths relative to the current script.
- Keep env var overrides for paths that may differ by machine.
- Avoid hardcoded absolute paths in generated markdown when repo-relative links will do.

## Backward Compatibility Requirements

The move should preserve both access paths:

- MCP-first operation through Codex and Gemini registrations
- direct CLI fallback through `memoryctl` and Python entrypoints

Required compatibility checks:

- `memoryctl start-context`
- `memoryctl log`
- `memoryctl fact-set`
- direct execution of:
  - `<repo>/tools/memory_mcp_server.py`
  - `<repo>/tools/dream_cycle.py`
  - `<repo>/tools/gms_eval.py`

Preferred migration safety net:

- keep `memoryctl` callable from PATH exactly as before
- avoid changing `MEMORY_ROOT`
- update configs before removing the old repo path
- if needed, leave a temporary compatibility shim or symlink at the old location until all agent configs are refreshed

## Acceptance Criteria For The Move

- MCP server starts from the new path.
- `memoryctl` wrapper still works.
- Dream Cycle still resolves `memoryctl` correctly.
- Test suite still passes.
- Evaluation harness still passes.
- Agent docs no longer tell users to use the old path.

## Remaining Cleanup

The migration is live, but some non-runtime artifacts still contain old-path references:

- cached Gemini chat transcripts
- historical Antigravity scratch outputs
- older generated notes outside this repo

These do not block runtime behavior, but they can be cleaned up later if desired.
