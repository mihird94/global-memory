"""Idempotent multi-harness installer and health doctor for Brain (GM v3.2)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .facts import backfill_headlines
from .index import index_stats
from .retrieval import embed_model, ollama_available, rerank_model
from .store import atomic_write_text, gm_home

SKILL_CONTENT = """---
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
"""


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _bin_paths() -> tuple[Path, Path, Path, Path]:
    venv_bin = _repo_root() / ".venv" / "bin"
    return venv_bin / "brain", venv_bin / "brain-mcp", venv_bin / "gm", venv_bin / "memoryctl"


def _patch_json_mcp(path: Path, brain_mcp_bin: Path, remove_legacy: bool = True) -> str:
    if not path.exists():
        return f"skipped (missing): {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.setdefault("mcpServers", {})
    if remove_legacy:
        for legacy_key in ("gms", "gm", "memory-server"):
            if legacy_key in servers:
                del servers[legacy_key]
    servers["brain"] = {
        "command": str(brain_mcp_bin),
        "args": [],
    }
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")
    return f"wired: {path}"


def _patch_codex_toml(path: Path, brain_mcp_bin: Path) -> str:
    if not path.exists():
        return f"skipped (missing): {path}"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?ms)^\[mcp_servers\.(?:gms?|brain)(?:\.[^\]]+)?\]\n.*?(?=^\[|\Z)"
    )
    cleaned = pattern.sub("", text).rstrip() + "\n\n"
    block = (
        "[mcp_servers.brain]\n"
        f'command = "{brain_mcp_bin}"\n'
        "args = []\n\n"
        "[mcp_servers.brain.tools.brain_context]\n"
        'approval_mode = "approve"\n\n'
        "[mcp_servers.brain.tools.brain_search]\n"
        'approval_mode = "approve"\n\n'
        "[mcp_servers.brain.tools.brain_read]\n"
        'approval_mode = "approve"\n\n'
        "[mcp_servers.brain.tools.brain_store]\n"
        'approval_mode = "approve"\n\n'
        "[mcp_servers.brain.tools.brain_project]\n"
        'approval_mode = "approve"\n'
    )
    atomic_write_text(path, cleaned + block)
    return f"wired: {path}"


def _patch_claude_hooks(settings_path: Path, brain_bin: Path) -> str:
    if not settings_path.parent.exists():
        return f"skipped (missing dir): {settings_path}"
    data: dict[str, Any] = {}
    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = data.setdefault("hooks", {})

    def _ensure_hook(event: str, matcher: str, cmd: str) -> None:
        entries = hooks.setdefault(event, [])
        # Replace any older gm context/flush-prompt hook cleanly
        filtered = [
            e for e in entries
            if not (isinstance(e, dict) and any(("context --hook claude" in h.get("command", "") or "flush-prompt --hook claude" in h.get("command", "")) for h in e.get("hooks", [])))
        ]
        entry: dict[str, Any] = {"hooks": [{"type": "command", "command": cmd}]}
        if matcher:
            entry["matcher"] = matcher
        filtered.append(entry)
        hooks[event] = filtered

    _ensure_hook("SessionStart", "startup", f"{brain_bin} context --hook claude")
    _ensure_hook("PreCompact", "", f"{brain_bin} flush-prompt --hook claude")

    perms = data.setdefault("permissions", {})
    allow = [
        p for p in perms.setdefault("allow", [])
        if not (isinstance(p, str) and p.startswith("mcp__gm__"))
    ]
    for tool in (
        "mcp__brain__brain_context",
        "mcp__brain__brain_search",
        "mcp__brain__brain_read",
        "mcp__brain__brain_store",
        "mcp__brain__brain_project",
    ):
        if tool not in allow:
            allow.append(tool)
    perms["allow"] = allow

    atomic_write_text(settings_path, json.dumps(data, indent=2) + "\n")
    return f"wired SessionStart + PreCompact hooks & permissions: {settings_path}"


def _patch_antigravity_permissions(config_path: Path) -> str:
    if not config_path.exists():
        return f"skipped (missing): {config_path}"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    allow = (
        data.setdefault("userSettings", {})
        .setdefault("globalPermissionGrants", {})
        .setdefault("allow", [])
    )
    allow = [
        entry for entry in allow
        if not (isinstance(entry, str) and (entry.startswith("mcp(gms/") or entry.startswith("mcp(gm/")))
    ]
    for tool in ("brain_context", "brain_search", "brain_read", "brain_store", "brain_project", "brain_forget"):
        grant = f"mcp(brain/{tool})"
        if grant not in allow:
            allow.append(grant)
    data["userSettings"]["globalPermissionGrants"]["allow"] = allow
    atomic_write_text(config_path, json.dumps(data, indent=2) + "\n")
    return f"wired Antigravity UI/IDE grants: {config_path}"


def _patch_opencode(path: Path, brain_mcp_bin: Path) -> str:
    if not path.exists():
        return f"skipped (missing): {path}"
    raw = path.read_text(encoding="utf-8")
    stripped = re.sub(r"(?m)^\s*//.*$", "", raw)
    try:
        data = json.loads(stripped)
    except Exception:
        return f"skipped (non-JSON comments): {path}"
    mcp = data.setdefault("mcp", {})
    for legacy_key in ("gms", "gm"):
        if legacy_key in mcp:
            del mcp[legacy_key]
    mcp["brain"] = {
        "type": "local",
        "command": [str(brain_mcp_bin)],
        "enabled": True,
    }
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")
    return f"wired: {path}"


def _ensure_symlink(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    dst.symlink_to(src)
    return f"linked: {dst} -> {src}"


def _load_policy_prompt() -> str:
    p = _repo_root() / "prompts" / "memory_policy.md"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return SKILL_CONTENT.strip()


def _upsert_managed_block(path: Path, body: str) -> str:
    start_tag = "<!-- GM_POLICY_START -->"
    end_tag = "<!-- GM_POLICY_END -->"
    block = f"{start_tag}\n{body.strip()}\n{end_tag}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        atomic_write_text(path, block + "\n")
        return f"created steering: {path}"
    raw = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"(?ms){re.escape(start_tag)}.*?{re.escape(end_tag)}")
    if pattern.search(raw):
        updated = pattern.sub(lambda _: block, raw)
    else:
        legacy = re.compile(r"(?ms)^## Global Memory[^\n]*\n.*?(?=^## |\Z)")
        if legacy.search(raw):
            updated = legacy.sub(lambda _: block + "\n\n", raw)
        else:
            updated = raw.rstrip() + "\n\n" + block + "\n"
    atomic_write_text(path, updated.rstrip() + "\n")
    return f"synced steering: {path}"


def _sync_steering_files() -> list[str]:
    home = Path.home()
    policy = _load_policy_prompt()
    out: list[str] = []

    for codex_doc in (home / ".codex" / "AGENTS.md", home / ".codex" / "CODEX.md"):
        if codex_doc.parent.exists():
            atomic_write_text(codex_doc, policy + "\n")
            out.append(f"synced steering: {codex_doc}")

    for managed_doc in (
        home / ".gemini" / "GEMINI.md",
        home / ".claude" / "CLAUDE.md",
        home / ".config" / "opencode" / "AGENTS.md",
    ):
        if managed_doc.parent.exists():
            out.append(_upsert_managed_block(managed_doc, policy))

    return out


def install_harnesses() -> list[str]:
    home = Path.home()
    brain_bin, brain_mcp_bin, gm_bin, memctl_bin = _bin_paths()
    local_brain = home / ".local" / "bin" / "brain"
    local_gm = home / ".local" / "bin" / "gm"
    local_memctl = home / ".local" / "bin" / "memoryctl"
    results: list[str] = []

    results.append(_ensure_symlink(brain_bin, local_brain))
    results.append(_ensure_symlink(gm_bin, local_gm))
    results.append(_ensure_symlink(memctl_bin, local_memctl))

    for p in (
        home / ".gemini" / "antigravity" / "mcp_config.json",
        home / ".gemini" / "config" / "mcp_config.json",
        home / ".gemini" / "settings.json",
    ):
        results.append(_patch_json_mcp(p, brain_mcp_bin))
    results.append(_patch_antigravity_permissions(home / ".gemini" / "config" / "config.json"))

    results.append(_patch_json_mcp(home / ".claude.json", brain_mcp_bin))
    results.append(_patch_claude_hooks(home / ".claude" / "settings.json", local_brain))

    results.append(_patch_codex_toml(home / ".codex" / "config.toml", brain_mcp_bin))
    results.append(_patch_opencode(home / ".config" / "opencode" / "opencode.jsonc", brain_mcp_bin))

    skill_path = home / ".gemini" / "config" / "skills" / "global-memory" / "SKILL.md"
    if skill_path.parent.exists():
        atomic_write_text(skill_path, SKILL_CONTENT)
        results.append(f"updated skill: {skill_path}")

    results.extend(_sync_steering_files())
    return results


def doctor(root: Path | None = None) -> dict[str, Any]:
    home = Path.home()
    root = gm_home(root)
    _, brain_mcp_bin, _, _ = _bin_paths()

    checks: dict[str, str] = {}
    checks["gm_home"] = f"ok ({root})" if root.exists() else f"missing ({root})"
    health = backfill_headlines(root, dry_run=True)
    missing = health["missing_headlines"]
    checked = health["writable_facts"]
    checks["fact_headlines"] = f"{checked - missing}/{checked} stored, {health['read_only_facts']} read-only sources"
    if missing:
        checks["fact_headlines"] += " (run `brain backfill-headlines` to fill the missing headlines)"
    empty = health["empty_facts"]
    partial = health["incomplete_identities"]
    checks["fact_health"] = f"{empty} empty facts, {partial} incomplete mutable identities" if empty or partial else "ok"
    stats = index_stats(root)
    if (root / ".gm" / "index.sqlite").exists():
        checks["index_db"] = f"ok ({stats['facts']} facts, {stats['episodes']} episodes, {stats['chunks']} chunks)"
    else:
        checks["index_db"] = "missing (run `brain reindex`)"
    if ollama_available():
        checks["ollama_embed"] = f"ok ({embed_model()}, {stats['embedded']}/{stats['chunks']} chunks embedded)"
    else:
        checks["ollama_embed"] = f"offline ({embed_model()} — FTS5 fallback active)"
    checks["onnx_reranker"] = f"ok ({rerank_model()})"
    checks["brain_mcp_bin"] = "ok" if brain_mcp_bin.exists() else f"missing ({brain_mcp_bin})"
    checks["cli_symlink"] = "ok (brain, gm)" if (home / ".local" / "bin" / "brain").exists() else "missing"

    for label, p in (
        ("antigravity_mcp", home / ".gemini" / "antigravity" / "mcp_config.json"),
        ("gemini_config_mcp", home / ".gemini" / "config" / "mcp_config.json"),
        ("gemini_cli_mcp", home / ".gemini" / "settings.json"),
        ("claude_code_mcp", home / ".claude.json"),
    ):
        if not p.exists():
            checks[label] = "not installed"
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            servers = d.get("mcpServers", {})
            if "brain" in servers and "gms" not in servers and "gm" not in servers:
                checks[label] = "ok (brain)"
            else:
                checks[label] = f"stale ({list(servers.keys())})"
        except Exception as exc:
            checks[label] = f"error ({exc})"

    codex = home / ".codex" / "config.toml"
    if codex.exists():
        txt = codex.read_text(encoding="utf-8")
        checks["codex_mcp"] = "ok (brain)" if "[mcp_servers.brain]" in txt and "[mcp_servers.gms]" not in txt else "stale/unwired"

    opencode = home / ".config" / "opencode" / "opencode.jsonc"
    if opencode.exists():
        txt = opencode.read_text(encoding="utf-8")
        checks["opencode_mcp"] = "ok (brain)" if '"brain"' in txt else "not wired"

    claude_settings = home / ".claude" / "settings.json"
    if claude_settings.exists():
        txt = claude_settings.read_text(encoding="utf-8")
        checks["claude_session_hook"] = "ok" if "context --hook claude" in txt else "not wired"
        checks["claude_precompact_hook"] = "ok" if "flush-prompt --hook claude" in txt else "not wired"

    old_plists = list((home / "Library" / "LaunchAgents").glob("com.user.gms-*.plist*"))
    checks["legacy_daemons"] = "clean" if not old_plists else f"found {len(old_plists)} old plists"

    return checks
