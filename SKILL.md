---
name: global-memory
description: Shared multi-harness local memory (`brain` / GM v3.2) stored as plain Markdown in ~/memories with SQLite chunk FTS5, Ollama embeddings, and ONNX cross-encoder reranking. Use across Antigravity, Claude Code, Codex, Gemini CLI, and OpenCode.
---

# Brain (GM v3.2)

Plain Markdown in `~/memories` + SQLite chunk FTS5 + Ollama embeddings + ONNX cross-encoder reranking. Shared across all local coding harnesses.

## 6 Tools (Progressive Disclosure)

1. **`brain_context(project?, cwd?)`** — L1 bootstrap (~300 tokens): profile summary, active project state, recent titles. Call once at session start if not already injected by a hook.
2. **`brain_search(query, project?, kind?, bucket?, since?, until?, limit?)`** — L2 hybrid + ONNX reranked search (`bucket="fact" | "episode"`, optional `YYYY-MM-DD` date filters). Respect `<0.25` low-confidence warnings.
3. **`brain_read(id_or_path)`** — L3 full read: load full Markdown only when a snippet is relevant.
4. **`brain_store(content, title?, kind?, project?, tags?, subject?, predicate?, headline?)`** — Save one verified fact, decision, lesson, or milestone. Provide both `subject` and `predicate` for a mutable fact. Provide a one-line `headline` for a fact over 400 characters. Search updates on save.
5. **`brain_project(name?, update?)`** — List projects, read living project state, or overwrite it cleanly.
6. **`brain_forget(id_or_path)`** — Reversibly archive stale or superseded memories.

## Rules
- **Cross-harness handoffs:** Use `brain board assign`, `brain board list --for <session>`, `brain board read <id>`, and `brain board post <id>` when agents share the same Brain home. Post progress and review decisions in the assignment thread.
- **Curate, don't hoard:** Only store verified facts, decisions, root-cause lessons, or concise milestones. Never store `hypothesis` as `fact`.
- **Keep static repo rules in `AGENTS.md`**, dynamic cross-session memory in `brain`.
- **CLI equivalents:** `brain context`, `brain search "<q>"`, `brain read <id>`, `brain store "<text>"`, `brain doctor`, `brain stats` (`gm` works identically).
