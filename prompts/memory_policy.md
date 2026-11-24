# Brain (GM v3.2) — Cross-Harness Memory Policy

All harnesses (**Antigravity, Claude Code, Codex, Gemini CLI, OpenCode**) share one local memory store at `~/memories` (plain Markdown truth + SQLite chunk FTS5 + Ollama `qwen3-embedding:0.6b` + ONNX `jina-reranker-v1-turbo-en` cross-encoder reranking) via the 6-tool `brain` MCP server and `brain` (or `gm`) CLI.

## 1. Retrieval Protocol (Progressive Disclosure L1 → L2 → L3)
1. **L1 Bootstrap:** Call `brain_context(project?, cwd?)` once at session start (skip if already injected by a `SessionStart` hook).
2. **L2 Search:** Call `brain_search(query, project?, bucket?, since?, until?)` (`bucket="fact"` for evergreen facts/decisions/lessons/projects, `"episode"` for daily logs; optional `YYYY-MM-DD` temporal filters) before assuming user preferences, architecture, or prior decisions.
3. **L3 Full Read:** Call `brain_read(id)` only when a snippet needs full Markdown context.
4. **Confidence & Abstention Gate:**
   - ONNX cross-encoder confidence tiers: `high` (`>= 0.25`), `medium` (`0.15–0.25`), `low` (`< 0.15`).
   - When top confidence is `< 0.25` or no high-confidence hit is returned, **abstain or verify directly** (read code/files or ask) — never treat weak matches as ground truth.

## 2. Mandatory Checkpoint Triggers (When to Store)
Before delivering your final response, check whether any of these happened in the turn. If yes, call `brain_store` or `brain_project` **immediately without asking permission** (writes are pre-approved and take ~1ms):
- **Non-trivial bug / root cause resolved** → `brain_store(kind="lesson", title=..., project=..., source=..., author=...)` (failure mode + verified fix).
- **Architecture / workflow decision or user correction** → `brain_store(kind="decision", title=..., project=..., source=..., author=...)` (choice + why + tradeoff).
- **Feature or project milestone completed** → `brain_project(name, update)` (living status, architecture, next steps) + concise `kind="episode"` if notable.
- **User preference, IP, path, or config stated** → `brain_store(content=<value>, kind="fact", subject=..., predicate=..., source="user")` (3-part notation; auto-supersedes prior value).
- **End-of-turn habit:** Mention what you stored in 1 short line when applicable. Never dump raw chat logs, transient stack traces, or unverified guesses.

## 3. Write Paths & Hygiene
- **Fact headlines:** The Facts view includes fact, decision, lesson, project, and profile records. Each displays a one-line headline. Supply `headline` when a `kind="fact"` body or mutable fact value exceeds 400 characters. Brain derives a headline for the other records when omitted.
- **Mutable atomic facts (3-part notation):** Pass `subject` + `predicate` with `content` as the value:
  `brain_store(content="192.0.2.10", kind="fact", subject="minipc", predicate="tailscale_ip")`
  *(CLI: `brain store "192.0.2.10" --subject minipc --predicate tailscale_ip`)*
  Updating the same `(subject, predicate)` **auto-supersedes** the prior value cleanly.
- **Provenance:** Include `source` (e.g. `"user"`, commit hash, file path) and `author` (e.g. `"antigravity"`, `"codex"`, `"claude-code"`) when known.
- **Prune stale/wrong entries:** `brain_forget(id)` archives reversibly to `~/memories/_archive_v3/`.
- **Never reindex after writes:** Do **not** run `brain reindex` or `gm reindex` after storing a memory — single-item FTS5 indexing happens in ~1ms and Ollama embeddings run automatically in a detached background worker.

## 4. Epistemic Classes
Distinguish epistemic status before writing or citing memory:
| Class | Definition | Memory Rule |
| :--- | :--- | :--- |
| **`verified`** | Directly observed in code, command output, tests, or explicit user statement. | Safe to store as `fact` (3-part or note), `decision`, or `lesson`. |
| **`decision`** | Confirmed design, workflow, or strategy choice with rationale. | Store as `kind="decision"`; supersede explicitly if reversed. |
| **`lesson`** | Confirmed root cause + preventive rule from a real failure/review. | Store as `kind="lesson"`; keep evergreen. |
| **`hypothesis`** | Unverified inference, draft proposal, or open question. | **Never** store as `kind="fact"`. If recorded in an `episode`, prefix `[hypothesis]`. |
| **`superseded`** | Replaced or outdated state. | Overwrite via `(subject, predicate)` or archive via `brain_forget(id)`. |

## 5. Boundary & CLI
- **Agent handoffs:** Use `brain board assign` for work briefs, `brain board list --for <session>` to find work, and `brain board post` for progress and review. Participating sessions use the same Brain home.
- **Static repo rules** (build/test commands, style) belong in repo `AGENTS.md`; **dynamic cross-session memory** belongs in `brain`.
- **CLI equivalents:** `brain context`, `brain search "<q>"`, `brain read <id>`, `brain store "<text>"`, `brain project [name]`, `brain doctor`, `brain stats` (`gm` works identically).
