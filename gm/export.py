"""Default-deny Personal -> External bundle export pipeline with local ONNX screening & SHA-256 pinning."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .index import _chunk_markdown, _make_snippet
from .screening import PrivacyScreener, SCANNER_VERSION, DeterministicScreener, DEFAULT_DENYLIST_TERMS, HARD_BLOCK_ENTITIES
from .store import (
    atomic_write_text,
    save_memory,
    iter_markdown_files,
    load_config,
    load_item,
    parse_frontmatter,
    render_frontmatter,
)
from .validation import normalize_project_slug

ALLOWED_EXPORT_KINDS: tuple[str, ...] = ("project", "decision", "lesson", "fact")
FORBIDDEN_KINDS = frozenset({"journal", "episode", "profile"})
SENSITIVE_PROJECTS = frozenset({"alphaos", "alpha-signal", "simplifi-finance-agent", "learning-os"})

SAFE_PROFILE_TEMPLATE = """# External Agent Profile (Sanitized)

- Prefer concise, verifiable engineering changes and minimal diffs.
- Never assume credentials, internal hosts, or private user data are in scope.
- Verify behavior directly against tests and primary workspace files.
"""

BUNDLE_INDEX_SQL = """
DROP TABLE IF EXISTS chunks_fts;
DROP TABLE IF EXISTS chunks;
DROP TABLE IF EXISTS docs;

CREATE TABLE docs (
    id TEXT PRIMARY KEY,
    rel_path TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',
    approved_at TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL
);

CREATE TABLE chunks (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT UNIQUE NOT NULL,
    doc_id TEXT NOT NULL,
    chunk_idx INTEGER NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    heading,
    text,
    content='chunks',
    content_rowid='rowid',
    tokenize='porter unicode61'
);
"""


def exports_root() -> Path:
    env = os.environ.get("BRAIN_EXPORTS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / "brain-exports").resolve()


def resolve_bundle_dir(name_or_path: str) -> Path:
    raw = name_or_path.strip()
    if not raw or "\0" in raw or raw in (".", ".."):
        raise ValueError("Provide a valid bundle name or directory path.")
    p = Path(raw).expanduser()
    if p.is_absolute() or "/" in raw or "\\" in raw:
        return p.resolve()
    if ".." in p.parts:
        raise ValueError("Bundle name cannot contain '..'.")
    return (exports_root() / raw).resolve()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_note_path(bundle_dir: Path, doc_id: str) -> Path:
    if not doc_id or "\0" in doc_id or doc_id.startswith("/") or "\\" in doc_id:
        raise ValueError(f"Invalid doc_id: {doc_id!r}")
    safe_id = doc_id.replace(":", "__")
    parts = Path(safe_id).parts
    if not parts or any(pt in ("", ".", "..") for pt in parts):
        raise ValueError(f"Unsafe doc_id path components: {doc_id!r}")
    notes_root = (bundle_dir / "notes").resolve()
    candidate = bundle_dir / "notes" / f"{safe_id}.md"
    cur = bundle_dir / "notes"
    for pt in parts[:-1]:
        cur = cur / pt
        if cur.is_symlink():
            raise ValueError(f"Symlink component rejected: {cur}")
    if candidate.is_symlink():
        raise ValueError(f"Symlink note rejected: {candidate}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(notes_root):
        raise ValueError(f"Path escape rejected for {doc_id!r}")
    return candidate


def _resolve_source_path(gm_root: Path, rel_path: str) -> Path | None:
    prefix, sep, relative = rel_path.partition(":")
    if sep:
        for entry in load_config(gm_root).get("extra_roots", []):
            base = Path(entry).expanduser().resolve()
            if base.name == prefix:
                cand = (base / relative).resolve()
                if cand.is_relative_to(base) and cand.is_file():
                    return cand
        return None
    root_res = gm_root.resolve()
    cand = (root_res / rel_path).resolve()
    if cand.is_relative_to(root_res) and cand.is_file():
        return cand
    return None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


_CACHE_REQUIRED_KEYS = frozenset(
    {"action", "entity_types", "hard_block_rules", "p_post_scrub", "chunks", "latency_ms", "scrubbed_body"}
)


def _screen_cache_path(gm_root: Path) -> Path:
    return gm_root / ".gm" / "screen_cache.json"


def _load_screen_cache(gm_root: Path) -> dict[str, dict[str, Any]]:
    path = _screen_cache_path(gm_root)
    if not path.exists() or path.is_symlink():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_screen_cache(gm_root: Path, cache: dict[str, dict[str, Any]]) -> None:
    try:
        atomic_write_text(_screen_cache_path(gm_root), json.dumps(cache, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _screen_with_cache(
    raw: str,
    source_sha: str,
    sc: PrivacyScreener,
    cache: dict[str, dict[str, Any]],
    *, strip_frontmatter: bool = True,
) -> tuple[dict[str, Any], bool]:
    key = f"{source_sha}:{sc.rules_hash}" + ("" if strip_frontmatter else ":raw")
    cached = cache.get(key)
    if isinstance(cached, dict) and _CACHE_REQUIRED_KEYS <= set(cached.keys()):
        return cached, False
    res = sc.screen_markdown(raw, strip_frontmatter=strip_frontmatter)
    entry = {
        "action": res.action,
        "entity_types": res.entity_types,
        "hard_block_rules": res.hard_block_rules,
        "p_post_scrub": res.p_post_scrub,
        "chunks": res.chunks,
        "latency_ms": res.latency_ms,
        "scrubbed_body": res.scrubbed_body,
    }
    cache[key] = entry
    return entry, True


def _rebuild_bundle_index(bundle_dir: Path, manifest: dict[str, Any]) -> int:
    db_path = bundle_dir / "index.sqlite"
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(BUNDLE_INDEX_SQL)
        total_chunks = 0
        with conn:
            for doc_id, meta in sorted(manifest.get("entries", {}).items()):
                note_path = _safe_note_path(bundle_dir, doc_id)
                if not note_path.exists():
                    continue
                raw = note_path.read_text(encoding="utf-8")
                if _sha256_bytes(raw.encode("utf-8")) != meta.get("exported_sha256"):
                    continue
                _, body = parse_frontmatter(raw)
                title = str(meta.get("title") or doc_id)
                conn.execute(
                    "INSERT INTO docs(id, rel_path, kind, title, project, approved_at, body) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        doc_id,
                        meta.get("exported_rel_path", f"notes/{doc_id.replace(':', '__')}.md"),
                        meta.get("kind", "fact"),
                        title,
                        meta.get("project", ""),
                        meta.get("approved_at", ""),
                        body,
                    ),
                )
                for idx, (heading, chunk_text) in enumerate(_chunk_markdown(title, body)):
                    chunk_id = f"{doc_id}#c{idx}"
                    cur = conn.execute(
                        "INSERT INTO chunks(chunk_id, doc_id, chunk_idx, heading, text) VALUES (?, ?, ?, ?, ?)",
                        (chunk_id, doc_id, idx, heading, chunk_text),
                    )
                    conn.execute(
                        "INSERT INTO chunks_fts(rowid, heading, text) VALUES (?, ?, ?)",
                        (cur.lastrowid, heading, chunk_text),
                    )
                    total_chunks += 1
        return total_chunks
    finally:
        conn.close()


def _validated_bundle_cfg(
    bundle_dir: Path,
    *,
    projects: list[str] | tuple[str, ...],
    allow_kinds: tuple[str, ...],
    threshold: float,
    extra_denylist: tuple[str, ...],
    allow_sensitive_project: bool,
    include_unprojected: bool,
    include_readonly_roots: bool,
    manual_include_ids: tuple[str, ...],
    allow_proposals: bool = True,
    created_at: str | None = None,
) -> dict[str, Any]:
    norm_projects = sorted({normalize_project_slug(str(p)) for p in projects if str(p).strip()} - {""})
    manual_clean = sorted({str(d).strip() for d in manual_include_ids if str(d).strip()})
    if not norm_projects and not (include_unprojected or include_readonly_roots or manual_clean):
        raise ValueError(
            "Specify at least one opted-in --projects slug or enable unprojected/read-only scope (default-deny refuses exporting everything)."
        )
    blocked_proj = [p for p in norm_projects if p in SENSITIVE_PROJECTS]
    if blocked_proj and not allow_sensitive_project:
        raise ValueError(
            f"Refusing sensitive project(s) {blocked_proj} by default policy. Confirm allow_sensitive_project only intentionally."
        )

    kinds_clean = tuple(dict.fromkeys(str(k).strip() for k in allow_kinds if str(k).strip()))
    if not kinds_clean or any(k not in ALLOWED_EXPORT_KINDS for k in kinds_clean):
        raise ValueError(f"allow_kinds must be a non-empty subset of {ALLOWED_EXPORT_KINDS}; forbidden: {sorted(FORBIDDEN_KINDS)}")
    if not (0.05 <= float(threshold) <= 0.99):
        raise ValueError("threshold must be between 0.05 and 0.99.")

    return {
        "bundle_name": bundle_dir.name,
        "created_at": created_at or _now_iso(),
        "updated_at": _now_iso(),
        "projects": norm_projects,
        "allow_kinds": list(kinds_clean),
        "threshold": round(float(threshold), 3),
        "extra_denylist": [str(t).strip() for t in extra_denylist if str(t).strip()],
        "excluded_kinds": sorted(FORBIDDEN_KINDS),
        "exclude_readonly_extra_roots": not bool(include_readonly_roots),
        "include_readonly_roots": bool(include_readonly_roots),
        "include_unprojected": bool(include_unprojected),
        "allow_sensitive_project": bool(allow_sensitive_project),
        "manual_include_ids": manual_clean,
        "allow_proposals": bool(allow_proposals),
    }


def init_bundle(
    bundle_dir: Path,
    *,
    projects: list[str] = (),
    allow_kinds: tuple[str, ...] = ALLOWED_EXPORT_KINDS,
    threshold: float = 0.50,
    extra_denylist: tuple[str, ...] = (),
    allow_sensitive_project: bool = False,
    include_unprojected: bool = False,
    include_readonly_roots: bool = False,
    manual_include_ids: tuple[str, ...] = (),
    allow_proposals: bool = True,
) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    cfg = _validated_bundle_cfg(
        bundle_dir,
        projects=projects,
        allow_kinds=allow_kinds,
        threshold=threshold,
        extra_denylist=extra_denylist,
        allow_sensitive_project=allow_sensitive_project,
        include_unprojected=include_unprojected,
        include_readonly_roots=include_readonly_roots,
        manual_include_ids=manual_include_ids,
        allow_proposals=allow_proposals,
    )
    (bundle_dir / "notes").mkdir(parents=True, exist_ok=True)
    _save_json(bundle_dir / "bundle_config.json", cfg)

    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        manifest = {"manifest_version": 1, "updated_at": _now_iso(), "entries": {}}
        _save_json(manifest_path, manifest)
    else:
        manifest = _load_json(manifest_path)

    profile_path = bundle_dir / "safe_profile.md"
    if not profile_path.exists():
        atomic_write_text(profile_path, SAFE_PROFILE_TEMPLATE)

    chunks_n = _rebuild_bundle_index(bundle_dir, manifest)
    return {
        "bundle_dir": str(bundle_dir),
        "projects": cfg["projects"],
        "allow_kinds": cfg["allow_kinds"],
        "threshold": cfg["threshold"],
        "include_unprojected": cfg["include_unprojected"],
        "include_readonly_roots": cfg["include_readonly_roots"],
        "approved_count": len(manifest.get("entries", {})),
        "indexed_chunks": chunks_n,
    }


def update_bundle_config(
    bundle_dir: Path,
    *,
    projects: list[str] | None = None,
    allow_kinds: tuple[str, ...] | None = None,
    threshold: float | None = None,
    extra_denylist: tuple[str, ...] | None = None,
    allow_sensitive_project: bool | None = None,
    include_unprojected: bool | None = None,
    include_readonly_roots: bool | None = None,
    manual_include_ids: tuple[str, ...] | None = None,
    allow_proposals: bool | None = None,
) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    cfg_p = bundle_dir / "bundle_config.json"
    if not cfg_p.exists():
        raise FileNotFoundError(f"Bundle not initialized at {bundle_dir}")
    cur = _load_json(cfg_p)
    inc_ro_cur = bool(cur.get("include_readonly_roots", not cur.get("exclude_readonly_extra_roots", True)))
    merged = _validated_bundle_cfg(
        bundle_dir,
        projects=cur.get("projects", []) if projects is None else projects,
        allow_kinds=tuple(cur.get("allow_kinds", ALLOWED_EXPORT_KINDS)) if allow_kinds is None else tuple(allow_kinds),
        threshold=float(cur.get("threshold", 0.50)) if threshold is None else float(threshold),
        extra_denylist=tuple(cur.get("extra_denylist", ())) if extra_denylist is None else tuple(extra_denylist),
        allow_sensitive_project=bool(cur.get("allow_sensitive_project", False))
        if allow_sensitive_project is None
        else bool(allow_sensitive_project),
        include_unprojected=bool(cur.get("include_unprojected", False))
        if include_unprojected is None
        else bool(include_unprojected),
        include_readonly_roots=inc_ro_cur if include_readonly_roots is None else bool(include_readonly_roots),
        manual_include_ids=tuple(cur.get("manual_include_ids", ())) if manual_include_ids is None else tuple(manual_include_ids),
        allow_proposals=cur.get("allow_proposals", True) if allow_proposals is None else allow_proposals,
        created_at=cur.get("created_at"),
    )
    _save_json(cfg_p, merged)
    return merged


def _item_in_bundle_scope(item: Any, readonly: bool, cfg: dict[str, Any]) -> tuple[bool, str]:
    if item.kind in FORBIDDEN_KINDS:
        return False, "private_kinds"
    if item.id in set(cfg.get("manual_include_ids", ())):
        return True, "included"
    allow_kinds = set(cfg.get("allow_kinds", ALLOWED_EXPORT_KINDS)) & set(ALLOWED_EXPORT_KINDS)
    if item.kind not in allow_kinds:
        return False, "disallowed_kinds"
    inc_ro = bool(cfg.get("include_readonly_roots", not cfg.get("exclude_readonly_extra_roots", True)))
    if readonly:
        return (True, "included") if inc_ro else (False, "readonly_roots")
    norm_proj = normalize_project_slug(item.project) if item.project else ""
    if not norm_proj:
        return (True, "included") if bool(cfg.get("include_unprojected", False)) else (False, "unprojected")
    allowed_projects = {normalize_project_slug(p) for p in cfg.get("projects", []) if p}
    return (True, "included") if norm_proj in allowed_projects else (False, "other_projects")


def store_scope_inventory(gm_root: Path, bundle_dir: Path | None = None) -> dict[str, Any]:
    """Fast metadata-only inventory of all notes in gm_root and why notes match or skip bundle scope."""
    cfg: dict[str, Any] | None = None
    allowed_projects: set[str] = set()
    if bundle_dir is not None and (bundle_dir.resolve() / "bundle_config.json").exists():
        cfg = _load_json(bundle_dir.resolve() / "bundle_config.json")
        allowed_projects = {normalize_project_slug(p) for p in cfg.get("projects", []) if p}

    total_notes = 0
    proj_counts: dict[str, int] = {}
    unprojected_count = 0
    readonly_count = 0
    excluded_private_count = 0
    coverage = {
        "total_notes": 0,
        "eligible_in_scope": 0,
        "other_projects": 0,
        "unprojected": 0,
        "readonly_roots": 0,
        "private_kinds": 0,
        "disallowed_kinds": 0,
    }

    for path, base_root, readonly, prefix in iter_markdown_files(gm_root):
        raw = path.read_text(encoding="utf-8", errors="replace")
        item = load_item(path, base_root, readonly=readonly, prefix=prefix, raw=raw)
        total_notes += 1
        if cfg is not None:
            coverage["total_notes"] += 1
            ok, reason = _item_in_bundle_scope(item, readonly, cfg)
            if ok:
                coverage["eligible_in_scope"] += 1
            else:
                coverage[reason] = coverage.get(reason, 0) + 1

        if item.kind in FORBIDDEN_KINDS:
            excluded_private_count += 1
            continue
        if readonly:
            readonly_count += 1
            continue
        slug = normalize_project_slug(item.project) if item.project else ""
        if not slug:
            unprojected_count += 1
        else:
            proj_counts[slug] = proj_counts.get(slug, 0) + 1

    projects = [
        {
            "slug": slug,
            "count": count,
            "sensitive": slug in SENSITIVE_PROJECTS,
            "in_bundle": slug in allowed_projects,
        }
        for slug, count in sorted(proj_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    out: dict[str, Any] = {
        "total_notes": total_notes,
        "projects": projects,
        "unprojected_count": unprojected_count,
        "readonly_count": readonly_count,
        "excluded_private_count": excluded_private_count,
    }
    if cfg is not None:
        out["coverage"] = coverage
    return out


def _diff_preview(orig_body: str, scrubbed_body: str, max_lines: int = 24) -> str:
    if orig_body.strip() == scrubbed_body.strip():
        return ""
    lines = list(
        difflib.unified_diff(
            orig_body.strip().splitlines(),
            scrubbed_body.strip().splitlines(),
            fromfile="source_body",
            tofile="scrubbed_body",
            lineterm="",
            n=1,
        )
    )
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["... (truncated)"]
    return "\n".join(lines)


def stage_bundle(
    gm_root: Path,
    bundle_dir: Path,
    *,
    screener: PrivacyScreener | None = None,
) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    cfg = _load_json(bundle_dir / "bundle_config.json")
    sc = screener or PrivacyScreener(
        threshold=float(cfg.get("threshold", 0.50)),
        extra_denylist=tuple(cfg.get("extra_denylist", ())),
        strict=True,
    )
    cache = _load_screen_cache(gm_root)
    cache_dirty = False

    staged_items: dict[str, Any] = {}
    counts = {"allow": 0, "redact_and_review": 0, "block": 0}
    skipped_breakdown = {
        "other_projects": 0,
        "unprojected": 0,
        "readonly_roots": 0,
        "private_kinds": 0,
        "disallowed_kinds": 0,
    }
    total_store_notes = 0

    for path, base_root, readonly, prefix in iter_markdown_files(gm_root):
        total_store_notes += 1
        raw = path.read_text(encoding="utf-8", errors="replace")
        item = load_item(path, base_root, readonly=readonly, prefix=prefix, raw=raw)
        ok, reason = _item_in_bundle_scope(item, readonly, cfg)
        if not ok:
            skipped_breakdown[reason] = skipped_breakdown.get(reason, 0) + 1
            continue

        source_sha = _sha256_bytes(raw.encode("utf-8"))
        scr, missed = _screen_with_cache(raw, source_sha, sc, cache)
        cache_dirty = cache_dirty or missed
        counts[scr["action"]] += 1
        staged_items[item.id] = {
            "source_id": item.id,
            "rel_path": item.rel_path,
            "kind": item.kind,
            "project": item.project,
            "title": item.title,
            "readonly": readonly,
            "source_sha256": source_sha,
            "action": scr["action"],
            "entity_types": scr["entity_types"],
            "hard_block_rules": scr["hard_block_rules"],
            "p_post_scrub": scr["p_post_scrub"],
            "chunks": scr["chunks"],
            "latency_ms": scr["latency_ms"],
            "scrubbed_body": scr["scrubbed_body"],
            "diff_preview": _diff_preview(item.body, scr["scrubbed_body"]),
        }

    if cache_dirty:
        _save_screen_cache(gm_root, cache)

    skipped_structural = sum(skipped_breakdown.values())
    staged_payload = {
        "staged_at": _now_iso(),
        "scanner_version": SCANNER_VERSION,
        "rules_hash": sc.rules_hash,
        "total_store_notes": total_store_notes,
        "skipped_breakdown": skipped_breakdown,
        "counts": counts,
        "items": staged_items,
    }
    _save_json(bundle_dir / "staged.json", staged_payload)
    return {
        "bundle_dir": str(bundle_dir),
        "candidates": len(staged_items),
        "total_store_notes": total_store_notes,
        "skipped_structural": skipped_structural,
        "skipped_breakdown": skipped_breakdown,
        "counts": counts,
        "rules_hash": sc.rules_hash,
        "items": [
            {
                "id": k,
                "kind": v["kind"],
                "project": v["project"],
                "title": v["title"],
                "action": v["action"],
                "entity_types": v["entity_types"],
                "p_post_scrub": v["p_post_scrub"],
            }
            for k, v in sorted(staged_items.items())
        ],
    }


def approve_bundle(
    gm_root: Path,
    bundle_dir: Path,
    *,
    doc_ids: list[str] = (),
    all_clean: bool = False,
    allow_redacted: bool = False,
    force_blocked: bool = False,
    screener: PrivacyScreener | None = None,
) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    staged_path = bundle_dir / "staged.json"
    if not staged_path.exists():
        raise FileNotFoundError("No staged.json found. Run `brain export stage <bundle>` first.")
    staged = _load_json(staged_path)
    items = staged.get("items", {})
    cfg = _load_json(bundle_dir / "bundle_config.json")
    sc = screener or PrivacyScreener(
        threshold=float(cfg.get("threshold", 0.50)),
        extra_denylist=tuple(cfg.get("extra_denylist", ())),
        strict=True,
    )

    if doc_ids:
        selected = list(dict.fromkeys(doc_ids))
    elif all_clean:
        selected = sorted(k for k, v in items.items() if v["action"] == "allow")
    else:
        raise ValueError("Provide explicit doc IDs or pass --all-clean.")

    manifest = _load_json(bundle_dir / "manifest.json")
    entries = manifest.setdefault("entries", {})
    approved_now: list[str] = []

    for doc_id in selected:
        if doc_id not in items:
            raise KeyError(f"Staged doc_id not found: {doc_id}")
        entry = items[doc_id]
        src_path = _resolve_source_path(gm_root, entry["rel_path"])
        if src_path is None:
            raise FileNotFoundError(f"Source file missing for {doc_id}: {entry['rel_path']}")
        live_sha = _sha256_bytes(src_path.read_bytes())
        if live_sha != entry["source_sha256"]:
            raise ValueError(f"Source drift detected for {doc_id} since staging; re-run `brain export stage`.")

        act = entry["action"]
        if act == "redact_and_review" and not allow_redacted:
            raise ValueError(f"{doc_id} requires redaction review (entities={entry['entity_types']}); pass --allow-redacted after review.")
        if act == "block" and not force_blocked:
            raise ValueError(f"{doc_id} is BLOCKED (rules={entry['hard_block_rules']}, p={entry['p_post_scrub']}); pass --force-blocked only if verified safe.")

        body_to_write = str(entry["scrubbed_body"]).strip()
        # Post-redaction fail-closed L1 verification
        rescan_hits = sc.deterministic_rescan(body_to_write)
        if rescan_hits and not force_blocked:
            rules = sorted({h.rule for h in rescan_hits})
            raise ValueError(f"Fail-closed post-redaction rescan detected remaining hard-block patterns on {doc_id}: {rules}")

        approved_at = _now_iso()
        fm = render_frontmatter(
            {
                "id": doc_id,
                "kind": entry["kind"],
                "project": entry["project"],
                "title": entry["title"],
                "approved_at": approved_at,
                "source_sha256": entry["source_sha256"],
            }
        )
        exported_text = fm + body_to_write + "\n"
        out_path = _safe_note_path(bundle_dir, doc_id)
        atomic_write_text(out_path, exported_text)
        exported_sha = _sha256_bytes(exported_text.encode("utf-8"))

        entries[doc_id] = {
            "source_id": doc_id,
            "source_rel_path": entry["rel_path"],
            "exported_rel_path": f"notes/{doc_id.replace(':', '__')}.md",
            "kind": entry["kind"],
            "project": entry["project"],
            "title": entry["title"],
            "action": act,
            "source_sha256": entry["source_sha256"],
            "exported_sha256": exported_sha,
            "approved_at": approved_at,
            "scanner_version": staged.get("scanner_version", SCANNER_VERSION),
            "rules_hash": staged.get("rules_hash", sc.rules_hash),
        }
        approved_now.append(doc_id)

    if approved_now:
        manifest["manifest_version"] = int(manifest.get("manifest_version", 1)) + 1
        manifest["updated_at"] = _now_iso()
        _save_json(bundle_dir / "manifest.json", manifest)
    chunks_n = _rebuild_bundle_index(bundle_dir, manifest)
    return {
        "bundle_dir": str(bundle_dir),
        "approved": approved_now,
        "manifest_version": manifest["manifest_version"],
        "total_exported": len(entries),
        "indexed_chunks": chunks_n,
    }


def bundle_status(gm_root: Path, bundle_dir: Path) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    manifest = _load_json(bundle_dir / "manifest.json")
    cfg = _load_json(bundle_dir / "bundle_config.json")
    staged_path = bundle_dir / "staged.json"
    staged_counts = _load_json(staged_path).get("counts", {}) if staged_path.exists() else {}

    rows: list[dict[str, Any]] = []
    for doc_id, meta in sorted(manifest.get("entries", {}).items()):
        try:
            exp_path = _safe_note_path(bundle_dir, doc_id)
        except ValueError:
            exp_state = "invalid_path"
            exp_path = None
        if exp_path is None or not exp_path.exists():
            exp_state = "missing_export"
        else:
            exp_sha = _sha256_bytes(exp_path.read_bytes())
            exp_state = "ok" if exp_sha == meta.get("exported_sha256") else "tampered_export"

        src_path = _resolve_source_path(gm_root, meta["source_rel_path"])
        if src_path is None:
            src_state = "missing_source"
        else:
            src_sha = _sha256_bytes(src_path.read_bytes())
            src_state = "ok" if src_sha == meta.get("source_sha256") else "drifted"

        rows.append(
            {
                "id": doc_id,
                "kind": meta.get("kind", ""),
                "project": meta.get("project", ""),
                "export_state": exp_state,
                "source_state": src_state,
            }
        )

    return {
        "bundle_dir": str(bundle_dir),
        "projects": cfg.get("projects", []),
        "manifest_version": manifest.get("manifest_version", 1),
        "approved_count": len(rows),
        "staged_counts": staged_counts,
        "entries": rows,
    }


def revoke_bundle(bundle_dir: Path, *, doc_ids: list[str] = (), revoke_all: bool = False) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    manifest = _load_json(bundle_dir / "manifest.json")
    entries = manifest.get("entries", {})
    targets = list(entries.keys()) if revoke_all else list(dict.fromkeys(doc_ids))
    if not targets and not revoke_all:
        raise ValueError("Specify doc IDs or --all to revoke.")

    revoked: list[str] = []
    for doc_id in targets:
        if doc_id not in entries:
            continue
        try:
            note_path = _safe_note_path(bundle_dir, doc_id)
            if note_path.exists():
                note_path.unlink()
        except ValueError:
            pass
        del entries[doc_id]
        revoked.append(doc_id)

    if revoked:
        manifest["manifest_version"] = int(manifest.get("manifest_version", 1)) + 1
        manifest["updated_at"] = _now_iso()
        _save_json(bundle_dir / "manifest.json", manifest)
    chunks_n = _rebuild_bundle_index(bundle_dir, manifest)
    return {
        "bundle_dir": str(bundle_dir),
        "revoked": revoked,
        "manifest_version": manifest.get("manifest_version", 1),
        "remaining_exported": len(entries),
        "indexed_chunks": chunks_n,
    }


def wire_external_harness(
    bundle_dir: Path,
    *,
    harness: str,
    safe_mcp_bin: Path | None = None,
    disconnect: bool = False,
) -> str:
    bundle_dir = bundle_dir.resolve()
    if not disconnect and not (bundle_dir / "manifest.json").exists():
        raise FileNotFoundError(f"Bundle not initialized at {bundle_dir} (missing manifest.json).")
    bin_path = safe_mcp_bin or (Path(__file__).resolve().parent.parent / ".venv" / "bin" / "brain-safe-mcp")

    home = Path.home()
    if harness == "pi":
        cfg_path = home / ".pi" / "agent" / "mcp.json"
        data = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        servers = data.setdefault("mcpServers", {})
        for legacy in ("brain", "brain-safe", "gm", "gms", "memory-server"):
            servers.pop(legacy, None)
        if not disconnect:
            servers["brain-safe"] = {
                "command": str(bin_path),
                "args": ["--bundle", str(bundle_dir)],
                "exposure": "direct",
            }
        atomic_write_text(cfg_path, json.dumps(data, indent=2) + "\n")
        return f"{'disconnected' if disconnect else 'wired brain-safe'}: {cfg_path}"

    if harness == "opencode":
        cfg_path = home / ".config" / "opencode" / "opencode.jsonc"
        if cfg_path.exists():
            raw = cfg_path.read_text(encoding="utf-8")
            stripped = re.sub(r"(?m)^\s*//.*$", "", raw)
            data = json.loads(stripped)
        else:
            data = {"$schema": "https://opencode.ai/config.json"}
        mcp = data.setdefault("mcp", {})
        for legacy in ("brain", "brain-safe", "gm", "gms", "memory-server"):
            mcp.pop(legacy, None)
        if not disconnect:
            mcp["brain-safe"] = {
                "type": "local",
                "command": [str(bin_path), "--bundle", str(bundle_dir)],
                "enabled": True,
            }
        atomic_write_text(cfg_path, json.dumps(data, indent=2) + "\n")
        return f"{'disconnected' if disconnect else 'wired brain-safe'}: {cfg_path}"

    raise ValueError(f"Unsupported external harness: {harness!r} (expected 'pi' or 'opencode').")


def _extract_bundle_arg(args: list[str]) -> str:
    for idx, tok in enumerate(args):
        if tok == "--bundle" and idx + 1 < len(args):
            return str(args[idx + 1])
        if tok.startswith("--bundle="):
            return str(tok.split("=", 1)[1])
    return ""


def external_harness_status(bundle_dir: Path | None = None) -> dict[str, dict[str, str]]:
    """Inspect Pi & OpenCode MCP configs for unrestricted exposure or active brain-safe bundle."""
    home = Path.home()
    target = str(bundle_dir.resolve()) if bundle_dir is not None else ""
    out: dict[str, dict[str, str]] = {}

    def _classify(entry: Any, cmd_str: str, args: list[str]) -> dict[str, str]:
        if "brain-safe-mcp" in cmd_str or (isinstance(entry, dict) and "brain-safe" in str(entry)):
            b = _extract_bundle_arg([str(x) for x in args])
            b_res = str(Path(b).expanduser().resolve()) if b else ""
            if target and b_res == target:
                return {"state": "wired_this", "bundle": b_res}
            return {"state": "wired_other" if target else "wired", "bundle": b_res}
        if "brain-mcp" in cmd_str:
            return {"state": "exposed_unrestricted", "bundle": ""}
        return {"state": "disconnected", "bundle": ""}

    pi_cfg = home / ".pi" / "agent" / "mcp.json"
    if not pi_cfg.exists():
        out["pi"] = {"state": "missing_config", "bundle": ""}
    else:
        try:
            data = json.loads(pi_cfg.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            if "brain" in servers or "gm" in servers or "gms" in servers:
                out["pi"] = {"state": "exposed_unrestricted", "bundle": ""}
            elif "brain-safe" in servers:
                s = servers["brain-safe"]
                out["pi"] = _classify(s, str(s.get("command", "")), s.get("args", []))
            else:
                out["pi"] = {"state": "disconnected", "bundle": ""}
        except Exception:
            out["pi"] = {"state": "error", "bundle": ""}

    oc_cfg = home / ".config" / "opencode" / "opencode.jsonc"
    if not oc_cfg.exists():
        out["opencode"] = {"state": "missing_config", "bundle": ""}
    else:
        try:
            raw = oc_cfg.read_text(encoding="utf-8")
            data = json.loads(re.sub(r"(?m)^\s*//.*$", "", raw))
            mcp = data.get("mcp", {})
            if "brain" in mcp or "gm" in mcp or "gms" in mcp:
                out["opencode"] = {"state": "exposed_unrestricted", "bundle": ""}
            elif "brain-safe" in mcp:
                s = mcp["brain-safe"]
                cmd = s.get("command", [])
                cmd_str = " ".join(str(x) for x in cmd) if isinstance(cmd, list) else str(cmd)
                args = cmd if isinstance(cmd, list) else []
                out["opencode"] = _classify(s, cmd_str, args)
            else:
                out["opencode"] = {"state": "disconnected", "bundle": ""}
        except Exception:
            out["opencode"] = {"state": "error", "bundle": ""}

    return out


def list_bundles() -> list[dict[str, Any]]:
    root = exports_root()
    if not root.exists():
        return []
    bundles: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        cfg_p = child / "bundle_config.json"
        man_p = child / "manifest.json"
        if not cfg_p.exists() or not man_p.exists():
            continue
        cfg = _load_json(cfg_p)
        man = _load_json(man_p)
        staged_p = child / "staged.json"
        staged_counts = _load_json(staged_p).get("counts", {}) if staged_p.exists() else {}
        bundles.append(
            {
                "name": child.name,
                "allow_proposals": cfg.get("allow_proposals", True),
                "inbox_pending_count": _pending_inbox_count(child),
                "bundle_dir": str(child),
                "projects": cfg.get("projects", []),
                "allow_kinds": cfg.get("allow_kinds", list(ALLOWED_EXPORT_KINDS)),
                "threshold": cfg.get("threshold", 0.50),
                "manifest_version": man.get("manifest_version", 1),
                "updated_at": man.get("updated_at", ""),
                "approved_count": len(man.get("entries", {})),
                "staged_counts": staged_counts,
                "harnesses": external_harness_status(child),
            }
        )
    return bundles


def save_safe_profile(bundle_dir: Path, content: str) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    if not (bundle_dir / "manifest.json").exists():
        raise FileNotFoundError(f"Bundle not initialized at {bundle_dir}")
    atomic_write_text(bundle_dir / "safe_profile.md", content.rstrip() + "\n")
    return {"bundle_dir": str(bundle_dir), "chars": len(content.rstrip())}


def discover_bundle_candidates(
    gm_root: Path,
    bundle_dir: Path,
    *,
    include_readonly: bool = False,
    screener: PrivacyScreener | None = None,
) -> dict[str, Any]:
    """Screen all eligible Brain memories across the store and classify them for human cherry-picking."""
    bundle_dir = bundle_dir.resolve()
    cfg = _load_json(bundle_dir / "bundle_config.json")
    man_entries = _load_json(bundle_dir / "manifest.json").get("entries", {})
    sc = screener or PrivacyScreener(
        threshold=float(cfg.get("threshold", 0.50)),
        extra_denylist=tuple(cfg.get("extra_denylist", ())),
        strict=True,
    )
    cache = _load_screen_cache(gm_root)
    cache_dirty = False

    items: list[dict[str, Any]] = []
    buckets: dict[str, dict[str, Any]] = {}
    tier_counts = {"recommended": 0, "review": 0, "blocked": 0}
    total_scanned = 0
    skipped_private = 0
    skipped_readonly = 0

    for path, base_root, readonly, prefix in iter_markdown_files(gm_root):
        raw = path.read_text(encoding="utf-8", errors="replace")
        item = load_item(path, base_root, readonly=readonly, prefix=prefix, raw=raw)
        if item.kind in FORBIDDEN_KINDS:
            skipped_private += 1
            continue
        if readonly and not include_readonly:
            skipped_readonly += 1
            continue

        total_scanned += 1
        source_sha = _sha256_bytes(raw.encode("utf-8"))
        scr, missed = _screen_with_cache(raw, source_sha, sc, cache)
        cache_dirty = cache_dirty or missed

        norm_proj = normalize_project_slug(item.project) if item.project else ""
        sensitive_project = norm_proj in SENSITIVE_PROJECTS
        in_scope, skip_reason = _item_in_bundle_scope(item, readonly, cfg)
        act = scr["action"]
        if act == "allow" and not sensitive_project:
            suggested_tier = "recommended"
        elif act == "redact_and_review" or (act == "allow" and sensitive_project):
            suggested_tier = "review"
        else:
            suggested_tier = "blocked"
        tier_counts[suggested_tier] += 1

        if readonly:
            bkey, blabel, btype, bslug, bsens = "readonly", "External wiki (read-only)", "readonly", "", False
        elif not norm_proj:
            bkey, blabel, btype, bslug, bsens = "unprojected", "Unprojected durable notes", "unprojected", "", False
        else:
            bkey, blabel, btype, bslug, bsens = f"project:{norm_proj}", norm_proj, "project", norm_proj, sensitive_project

        bucket = buckets.setdefault(
            bkey,
            {
                "key": bkey,
                "label": blabel,
                "type": btype,
                "slug": bslug,
                "sensitive": bsens,
                "in_scope": False,
                "total": 0,
                "allow": 0,
                "redact_and_review": 0,
                "block": 0,
                "suggested_tier": "blocked",
            },
        )
        bucket["total"] += 1
        bucket[act] += 1

        items.append(
            {
                "id": item.id,
                "rel_path": item.rel_path,
                "title": item.title,
                "kind": item.kind,
                "project": item.project,
                "norm_project": norm_proj,
                "bucket_key": bkey,
                "readonly": readonly,
                "sensitive_project": sensitive_project,
                "in_scope": in_scope,
                "skip_reason": skip_reason,
                "approved": item.id in man_entries,
                "action": act,
                "suggested_tier": suggested_tier,
                "entity_types": scr["entity_types"],
                "hard_block_rules": scr["hard_block_rules"],
                "p_post_scrub": scr["p_post_scrub"],
                "diff_preview": _diff_preview(item.body, scr["scrubbed_body"]),
                "scrubbed_body": scr["scrubbed_body"],
                "source_sha256": source_sha,
            }
        )

    if cache_dirty:
        _save_screen_cache(gm_root, cache)

    for bucket in buckets.values():
        if bucket["allow"] > 0 and not bucket["sensitive"]:
            bucket["suggested_tier"] = "recommended"
        elif (bucket["allow"] + bucket["redact_and_review"]) > 0:
            bucket["suggested_tier"] = "review"
        else:
            bucket["suggested_tier"] = "blocked"

    summaries = sorted(
        buckets.values(),
        key=lambda b: (-(b["allow"] if not b["sensitive"] else 0), -b["allow"], -b["total"], b["key"]),
    )
    tier_order = {"recommended": 0, "review": 1, "blocked": 2}
    items.sort(key=lambda x: (tier_order.get(x["suggested_tier"], 3), x["id"]))

    payload = {
        "discovered_at": _now_iso(),
        "scanner_version": SCANNER_VERSION,
        "rules_hash": sc.rules_hash,
        "include_readonly": bool(include_readonly),
        "total_scanned": total_scanned,
        "skipped_private": skipped_private,
        "skipped_readonly": skipped_readonly,
        "tier_counts": tier_counts,
        "project_summaries": summaries,
        "items": items,
    }
    _refresh_suggestions_status(payload, cfg, man_entries)
    _save_json(bundle_dir / "suggestions.json", payload)
    return payload


def _refresh_suggestions_status(
    suggestions: dict[str, Any],
    cfg: dict[str, Any],
    man_entries: dict[str, Any],
) -> dict[str, Any]:
    allowed_projects = {normalize_project_slug(p) for p in cfg.get("projects", []) if p}
    allow_kinds = set(cfg.get("allow_kinds", ALLOWED_EXPORT_KINDS)) & set(ALLOWED_EXPORT_KINDS)
    inc_unproj = bool(cfg.get("include_unprojected", False))
    inc_ro = bool(cfg.get("include_readonly_roots", not cfg.get("exclude_readonly_extra_roots", True)))
    manual_ids = set(cfg.get("manual_include_ids", ()))

    for bucket in suggestions.get("project_summaries", []):
        btype = bucket.get("type")
        if btype == "readonly":
            bucket["in_scope"] = inc_ro
        elif btype == "unprojected":
            bucket["in_scope"] = inc_unproj
        else:
            bucket["in_scope"] = bucket.get("slug", "") in allowed_projects

    for it in suggestions.get("items", []):
        it["approved"] = it["id"] in man_entries
        if it["id"] in manual_ids:
            it["in_scope"] = True
            it["skip_reason"] = "included"
        elif it.get("kind") not in allow_kinds:
            it["in_scope"] = False
            it["skip_reason"] = "disallowed_kinds"
        elif it.get("readonly"):
            it["in_scope"] = inc_ro
            it["skip_reason"] = "included" if inc_ro else "readonly_roots"
        elif not it.get("norm_project"):
            it["in_scope"] = inc_unproj
            it["skip_reason"] = "included" if inc_unproj else "unprojected"
        else:
            in_proj = it["norm_project"] in allowed_projects
            it["in_scope"] = in_proj
            it["skip_reason"] = "included" if in_proj else "other_projects"
    return suggestions


def add_bundle_candidates(
    gm_root: Path,
    bundle_dir: Path,
    *,
    doc_ids: list[str],
    approve_if_clean: bool = False,
    screener: PrivacyScreener | None = None,
) -> dict[str, Any]:
    """Explicitly add individual notes to a bundle via manual_include_ids and restage."""
    bundle_dir = bundle_dir.resolve()
    clean_ids = list(dict.fromkeys(str(d).strip() for d in doc_ids if str(d).strip()))
    if not clean_ids:
        raise ValueError("Select at least one note to add.")
    cfg = _load_json(bundle_dir / "bundle_config.json")
    existing = [str(x).strip() for x in cfg.get("manual_include_ids", ()) if str(x).strip()]
    update_bundle_config(bundle_dir, manual_include_ids=tuple(sorted(set(existing) | set(clean_ids))))

    sc = screener or PrivacyScreener(
        threshold=float(cfg.get("threshold", 0.50)),
        extra_denylist=tuple(cfg.get("extra_denylist", ())),
        strict=True,
    )
    staged = stage_bundle(gm_root, bundle_dir, screener=sc)
    approved_ids: list[str] = []
    if approve_if_clean:
        action_by_id = {row["id"]: row["action"] for row in staged["items"]}
        to_approve = [did for did in clean_ids if action_by_id.get(did) == "allow"]
        if to_approve:
            app = approve_bundle(gm_root, bundle_dir, doc_ids=to_approve, screener=sc)
            approved_ids = app["approved"]
    return {
        "added": clean_ids,
        "approved": approved_ids,
        "staged_counts": staged["counts"],
    }


def read_bundle_detail(gm_root: Path, bundle_dir: Path, *, screener: PrivacyScreener | None = None, include_inbox: bool = False) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    cfg_p = bundle_dir / "bundle_config.json"
    man_p = bundle_dir / "manifest.json"
    if not cfg_p.exists() or not man_p.exists():
        raise FileNotFoundError(f"Bundle not initialized at {bundle_dir}")

    cfg = _load_json(cfg_p)
    man = _load_json(man_p)
    status_info = bundle_status(gm_root, bundle_dir)
    status_by_id = {r["id"]: r for r in status_info["entries"]}
    inventory = store_scope_inventory(gm_root, bundle_dir)

    staged_p = bundle_dir / "staged.json"
    staged_data = _load_json(staged_p) if staged_p.exists() else {}
    staged_items = staged_data.get("items", {})
    man_entries = man.get("entries", {})

    prof_p = bundle_dir / "safe_profile.md"
    safe_profile = prof_p.read_text(encoding="utf-8") if prof_p.exists() and not prof_p.is_symlink() else ""

    sug_p = bundle_dir / "suggestions.json"
    suggestions: dict[str, Any] | None = None
    if sug_p.exists() and not sug_p.is_symlink():
        try:
            suggestions = _refresh_suggestions_status(_load_json(sug_p), cfg, man_entries)
        except Exception:
            suggestions = None

    all_ids = sorted(set(staged_items.keys()) | set(man_entries.keys()))
    unified: list[dict[str, Any]] = []
    for doc_id in all_ids:
        st = staged_items.get(doc_id)
        mn = man_entries.get(doc_id)
        sb = status_by_id.get(doc_id)
        unified.append(
            {
                "id": doc_id,
                "title": (st or mn or {}).get("title", doc_id),
                "kind": (st or mn or {}).get("kind", "fact"),
                "project": (st or mn or {}).get("project", ""),
                "action": st["action"] if st else (mn.get("action", "allow") if mn else "allow"),
                "entity_types": st.get("entity_types", []) if st else [],
                "hard_block_rules": st.get("hard_block_rules", []) if st else [],
                "p_post_scrub": st.get("p_post_scrub", 0.0) if st else 0.0,
                "latency_ms": st.get("latency_ms", 0.0) if st else 0.0,
                "diff_preview": st.get("diff_preview", "") if st else "",
                "scrubbed_body": st.get("scrubbed_body", "") if st else "",
                "staged": st is not None,
                "approved": mn is not None,
                "approved_at": mn.get("approved_at", "") if mn else "",
                "export_state": sb["export_state"] if sb else "not_exported",
                "source_state": sb["source_state"] if sb else "staged_only",
            }
        )

    audit_p = bundle_dir / "audit.jsonl"
    recent_audit: list[dict[str, Any]] = []
    if audit_p.exists():
        lines = [ln for ln in audit_p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        for ln in reversed(lines[-25:]):
            try:
                recent_audit.append(json.loads(ln))
            except ValueError:
                continue

    return {
        "name": bundle_dir.name,
        "bundle_dir": str(bundle_dir),
        "inbox_pending_count": _pending_inbox_count(bundle_dir),
        "inbox": list_inbox_proposals(gm_root, bundle_dir, screener=screener) if include_inbox or _pending_inbox_count(bundle_dir) else [],
        "config": cfg,
        "manifest_version": man.get("manifest_version", 1),
        "updated_at": man.get("updated_at", ""),
        "approved_count": len(man_entries),
        "staged_at": staged_data.get("staged_at", ""),
        "rules_hash": staged_data.get("rules_hash", ""),
        "staged_counts": staged_data.get("counts", {}),
        "total_store_notes": staged_data.get("total_store_notes") or inventory["total_notes"],
        "skipped_breakdown": staged_data.get("skipped_breakdown") or inventory.get("coverage", {}),
        "inventory": inventory,
        "suggestions": suggestions,
        "harnesses": external_harness_status(bundle_dir),
        "safe_profile": safe_profile,
        "items": unified,
        "recent_audit": recent_audit,
    }

# Untrusted proposals remain in the bundle until a local human promotes them.
ALLOWED_PROPOSAL_KINDS = ("fact", "decision", "lesson")
MAX_INBOX_PENDING = 50
MAX_PROPOSAL_CONTENT_CHARS = 12_000
_INBOX_ID = re.compile(r"prop-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\Z", re.ASCII)


def _safe_inbox_path(bundle_dir: Path, proposal_id: str) -> Path:
    if not isinstance(proposal_id, str) or not _INBOX_ID.fullmatch(proposal_id):
        raise ValueError("Invalid proposal ID")
    inbox = bundle_dir / "inbox"
    path = inbox / (proposal_id + ".json")
    if inbox.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(inbox.resolve()):
        raise ValueError("Unsafe inbox path")
    return path


def _inbox_records(bundle_dir: Path) -> list[dict[str, Any]]:
    inbox = bundle_dir / "inbox"
    if inbox.is_symlink():
        raise ValueError("Unsafe inbox directory")
    if not inbox.exists():
        return []
    records = []
    for path in inbox.glob("*.json"):
        try:
            if _safe_inbox_path(bundle_dir, path.stem) != path or path.is_symlink():
                continue
            item = _load_json(path)
            if isinstance(item, dict) and item.get("id") == path.stem and item.get("status") == "pending":
                records.append(item)
        except (ValueError, OSError, TypeError):
            continue
    return records


def _pending_inbox_count(bundle_dir: Path) -> int:
    return len(_inbox_records(bundle_dir))


def _proposal_values(*, title: str, content: str, kind: str, project: str, headline: str, tags: Any, harness: str) -> dict[str, Any]:
    if not all(isinstance(x, str) for x in (title, content, kind, project, headline, harness)):
        raise ValueError("Proposal fields must be strings")
    title, content, headline, project = (x.strip() for x in (title, content, headline, project))
    if not title or len(title) > 160 or not content or len(content) > MAX_PROPOSAL_CONTENT_CHARS:
        raise ValueError("Title must be 1–160 characters and content 1–12000 characters")
    if len(headline) > 300 or len(project) > 64 or len(harness) > 48 or kind not in ALLOWED_PROPOSAL_KINDS:
        raise ValueError("Invalid proposal kind or field length")
    if isinstance(tags, str):
        tags = tags.split(',')
    if not isinstance(tags, (list, tuple)) or any(not isinstance(x, str) for x in tags):
        raise ValueError("Tags must be strings")
    tags = list(dict.fromkeys(x.strip() for x in tags if x.strip()))
    if len(tags) > 10 or any(len(x) > 40 for x in tags):
        raise ValueError("At most 10 tags of 40 characters are allowed")
    return dict(title=title, content=content, kind=kind, project=normalize_project_slug(project) if project else "", headline=headline, tags=tags, harness=re.sub(r'[^a-z0-9_-]', '', harness.lower()) or 'external')


def propose_to_inbox(bundle_dir: Path, *, title: str, content: str, kind: str = 'lesson', project: str = '', headline: str = '', tags: Any = (), harness: str = '') -> dict[str, Any]:
    import fcntl
    cfg_path = bundle_dir / 'bundle_config.json'
    if cfg_path.is_symlink() or not cfg_path.is_file():
        raise FileNotFoundError('Bundle configuration missing or unsafe')
    values = _proposal_values(title=title, content=content, kind=kind, project=project, headline=headline, tags=tags, harness=harness)
    inbox = bundle_dir / 'inbox'
    if inbox.is_symlink():
        raise ValueError('Unsafe inbox directory')
    inbox.mkdir(mode=0o700, exist_ok=True)
    # Serialize quota, deduplication, and allocation across MCP processes.
    lock_path = inbox / '.lock'
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cfg = _load_json(cfg_path)
        if not cfg.get('allow_proposals', True):
            raise PermissionError(f'Proposals are disabled for bundle {bundle_dir.name!r}.')
        digest = _sha256_bytes(values['content'].encode())
        records = _inbox_records(bundle_dir)
        for item in records:
            if item.get('content_sha256') == digest and item.get('title') == values['title']:
                l1 = item['l1_screen']
                return dict(proposal_id=item['id'], status='pending', bundle=bundle_dir.name, deduplicated=True, l1_action=l1['action'], l1_entity_types=l1['entity_types'], l1_hard_block_rules=l1['hard_block_rules'])
        if len(records) >= MAX_INBOX_PENDING:
            raise ValueError('Bundle inbox is full (50 pending proposals). Review or discard items in Brain Desktop.')
        det = DeterministicScreener(denylist=tuple(dict.fromkeys([*DEFAULT_DENYLIST_TERMS, *cfg.get('extra_denylist', ())])))
        findings = det.scan(f"{values['title']}\n\n{values['headline']}\n\n{values['content']}")
        hard = sorted({f.rule for f in findings if f.entity_type in HARD_BLOCK_ENTITIES})
        l1 = dict(action='block' if hard else 'redact_and_review' if findings else 'allow', entity_types=sorted({f.entity_type for f in findings}), hard_block_rules=hard)
        proposal_id = 'prop-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + os.urandom(4).hex()
        item = dict(id=proposal_id, created_at=_now_iso(), status='pending', bundle_name=bundle_dir.name, **values, content_sha256=digest, l1_screen=l1, full_screen=None, promoted_doc_id='', reviewed_at='')
        _save_json(_safe_inbox_path(bundle_dir, proposal_id), item)
        return dict(proposal_id=proposal_id, status='pending', bundle=bundle_dir.name, deduplicated=False, l1_action=l1['action'], l1_entity_types=l1['entity_types'], l1_hard_block_rules=hard)


def _inbox_screener(bundle_dir: Path, screener: PrivacyScreener | None) -> PrivacyScreener:
    if screener is not None:
        return screener
    cfg = _load_json(bundle_dir / 'bundle_config.json')
    return PrivacyScreener(threshold=float(cfg.get('threshold', .5)), extra_denylist=tuple(cfg.get('extra_denylist', ())), deterministic_only=os.environ.get('BRAIN_SCREEN_DETERMINISTIC') == '1')


def _review_screen(values: dict[str, Any], sc: PrivacyScreener, cache: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    # Cache the exact screened content, including metadata, not just the body digest.
    raw = f"{values['title']}\n\n{values['headline']}\n\n{values['content']}"
    full, changed = _screen_with_cache(raw, _sha256_bytes(raw.encode()), sc, cache, strip_frontmatter=False)
    body, changed_body = _screen_with_cache(values['content'], _sha256_bytes(values['content'].encode()), sc, cache, strip_frontmatter=False)
    result = dict(full, scrubbed_body=body['scrubbed_body'], rules_hash=sc.rules_hash)
    result['diff_preview'] = ''.join(difflib.unified_diff(values['content'].splitlines(keepends=True), body['scrubbed_body'].splitlines(keepends=True), fromfile='original', tofile='scrubbed'))
    return result, changed or changed_body


def list_inbox_proposals(gm_root: Path, bundle_dir: Path, *, screener: PrivacyScreener | None = None) -> list[dict[str, Any]]:
    records = _inbox_records(bundle_dir)
    if not records:
        return []
    sc = _inbox_screener(bundle_dir, screener)
    cache = _load_screen_cache(gm_root)
    dirty = False
    for item in records:
        item['full_screen'], changed = _review_screen(item, sc, cache)
        dirty |= changed
    if dirty:
        _save_screen_cache(gm_root, cache)
    return sorted(records, key=lambda x: x.get('created_at', ''), reverse=True)


def _inbox_audit(bundle_dir: Path, tool: str, **values: Any) -> None:
    with (bundle_dir / 'audit.jsonl').open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(dict(ts=_now_iso(), tool=tool, status='ok', **values)) + '\n')


def promote_inbox_proposal(gm_root: Path, bundle_dir: Path, proposal_id: str, *, use_scrubbed: bool = False, also_export: bool = False, force_blocked: bool = False, title: str | None = None, headline: str | None = None, project: str | None = None, content: str | None = None, tags: list[str] | None = None, screener: PrivacyScreener | None = None) -> dict[str, Any]:
    from .index import index_single_item
    path = _safe_inbox_path(bundle_dir, proposal_id)
    item = _load_json(path)
    if item.get('id') != proposal_id or item.get('status') != 'pending' or _sha256_bytes(item['content'].encode()) != item.get('content_sha256'):
        raise ValueError('Proposal integrity check failed')
    values = _proposal_values(**{k: (v if v is not None else item.get(k, '')) for k, v in dict(title=title, headline=headline, project=project, content=content, tags=tags, kind=None, harness=None).items()})
    sc = _inbox_screener(bundle_dir, screener)
    if use_scrubbed:
        values['content'] = sc.screen_markdown(values['content'], strip_frontmatter=False).scrubbed_body
    screen = sc.screen_markdown(f"{values['title']}\n\n{values['headline']}\n\n{values['content']}", strip_frontmatter=False)
    if (screen.action == 'block' or screen.hard_block_rules) and not force_blocked:
        raise ValueError('Proposal is blocked by privacy screening; edit it or explicitly force promotion.')
    saved = save_memory(gm_root, values['content'], title=values['title'], kind=values['kind'], project=values['project'], tags=values['tags'], headline=values['headline'], source=f'safe-inbox:{bundle_dir.name}/{proposal_id}', author=f"external:{values['harness']}", epistemic='verified', replace=False)
    index_single_item(gm_root, saved)
    export_result = None
    if also_export:
        export_result = add_bundle_candidates(gm_root, bundle_dir, doc_ids=[saved.id], approve_if_clean=True, screener=sc)
    path.unlink()
    _inbox_audit(bundle_dir, 'inbox_promote', proposal_id=proposal_id, doc_id=saved.id)
    return dict(promoted_doc_id=saved.id, rel_path=saved.rel_path, also_exported=bool(export_result and saved.id in export_result['approved']))


def discard_inbox_proposal(bundle_dir: Path, proposal_id: str) -> dict[str, Any]:
    _safe_inbox_path(bundle_dir, proposal_id).unlink()
    _inbox_audit(bundle_dir, 'inbox_discard', proposal_id=proposal_id)
    return {'discarded': proposal_id}
