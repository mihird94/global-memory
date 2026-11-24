"""Non-destructive v2 -> v3 migrator for ~/memories."""

from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from .index import reindex_all
from .store import atomic_write_text, ensure_layout, now_iso, render_frontmatter, slugify

V2_ARCHIVE_ITEMS = (
    "gms_trust.sqlite",
    "gms_trust.sqlite-wal",
    "gms_trust.sqlite-shm",
    "gms_trust.sqlite.bak",
    "gms_trust.sqlite.bak-shm",
    "gms_trust.sqlite.bak-wal",
    "backup.log",
    "backup.err",
    "index.md",
    "projects.md",
    "preferences.md",
    "episodic",
    "semantic",
    "lessons",
    "operational",
    "procedural",
    "logs",
)


def _domain_for_key(key: str) -> str:
    k = key.lower()
    if k.startswith("birthday_"):
        return "birthdays"
    if k.startswith("alphaos"):
        return "alphaos"
    if k.startswith("agent_memory") or k.startswith("gms"):
        return "agent-memory"
    if "." in k:
        return slugify(k.split(".", 1)[0], 24)
    if "_" in k:
        head = k.split("_", 1)[0]
        if len(head) >= 3:
            return slugify(head, 24)
    return "general"


def _flatten_json_facts(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                out[str(k)] = json.dumps(v, ensure_ascii=False)
            else:
                out[str(k)] = str(v)
    return out


def migrate_v2(root: Path, dry_run: bool = False) -> dict[str, Any]:
    ensure_layout(root)
    archive = root / "_archive_v2"
    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "profile": False,
        "projects": [],
        "fact_groups": [],
        "semantic_docs": [],
        "lessons": 0,
        "journals": 0,
        "archived": [],
    }
    ts = now_iso()

    # 1. preferences.md -> profile.md
    pref = root / "preferences.md"
    if pref.exists() and not (root / "profile.md").exists():
        summary["profile"] = True
        if not dry_run:
            text = pref.read_text(encoding="utf-8", errors="replace").strip()
            fm = render_frontmatter({"title": "User Profile & Preferences", "kind": "profile", "updated_at": ts})
            atomic_write_text(root / "profile.md", fm + text + "\n")

    # 2. projects/<subdir>/*.md -> projects/<subdir>.md
    proj_dir = root / "projects"
    if proj_dir.exists():
        for sub in sorted(proj_dir.iterdir()):
            if not sub.is_dir() or sub.name.startswith("."):
                continue
            md_files = sorted(sub.glob("*.md"))
            if not md_files:
                continue
            slug = slugify(sub.name, 48)
            summary["projects"].append(slug)
            if not dry_run:
                parts = [f"# {sub.name}\n"]
                for mf in md_files:
                    body = mf.read_text(encoding="utf-8", errors="replace").strip()
                    if body:
                        parts.append(f"## {mf.stem}\n\n{body}")
                fm = render_frontmatter({"title": sub.name, "kind": "project", "project": slug, "updated_at": ts})
                atomic_write_text(proj_dir / f"{slug}.md", fm + "\n\n".join(parts) + "\n")
                dst = archive / "projects" / sub.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    shutil.move(str(sub), str(dst))

    # 3. lessons/global.md -> notes/lessons/
    lessons_file = root / "lessons" / "global.md"
    if lessons_file.exists():
        raw = lessons_file.read_text(encoding="utf-8", errors="replace")
        bullets = [
            m.group(1).strip()
            for m in re.finditer(r"^- (.+)$", raw, flags=re.MULTILINE)
            if "Ollama" not in m.group(1) and "qwen3-embedding" not in m.group(1)
        ]
        if bullets:
            summary["lessons"] = len(bullets)
            if not dry_run:
                fm = render_frontmatter(
                    {"title": "Global Engineering & Trading Lessons", "kind": "lesson", "tags": ["migrated"], "updated_at": ts}
                )
                body = "# Global Engineering & Trading Lessons\n\n" + "\n".join(f"- {b}" for b in bullets) + "\n"
                atomic_write_text(root / "notes" / "lessons" / "global-lessons.md", fm + body)

    # 4. semantic/operational/procedural facts.json -> grouped notes/facts/<domain>.md
    all_facts: dict[str, str] = {}
    for rel in ("semantic/facts.json", "operational/facts.json", "procedural/facts.json"):
        all_facts.update(_flatten_json_facts(root / rel))

    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for k, v in sorted(all_facts.items()):
        grouped[_domain_for_key(k)].append((k, v))

    # Merge tiny 1-item groups into general
    merged: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for dom, items in grouped.items():
        if len(items) == 1 and dom not in ("alphaos", "agent-memory", "birthdays"):
            merged["general"].extend(items)
        else:
            merged[dom].extend(items)

    for dom, items in sorted(merged.items()):
        summary["fact_groups"].append(f"{dom} ({len(items)})")
        if not dry_run:
            project = dom if dom in ("alphaos",) else ""
            fm = render_frontmatter(
                {
                    "title": f"Facts: {dom}",
                    "kind": "fact",
                    "project": project,
                    "tags": ["migrated", dom],
                    "updated_at": ts,
                }
            )
            lines = [f"# Facts: {dom}", ""]
            for k, v in items:
                lines.append(f"- **{k}:** {v}")
            atomic_write_text(root / "notes" / "facts" / f"{dom}.md", fm + "\n".join(lines) + "\n")

    # 5. semantic/*.md -> notes/facts/
    sem_dir = root / "semantic"
    if sem_dir.exists():
        for md in sorted(sem_dir.glob("*.md")):
            if md.stat().st_size < 40:
                continue
            summary["semantic_docs"].append(md.name)
            if not dry_run:
                target = root / "notes" / "facts" / md.name
                if not target.exists():
                    shutil.copy2(md, target)

    # 6. episodic/history/*.md -> journal/*.md
    hist_dir = root / "episodic" / "history"
    if hist_dir.exists():
        for md in sorted(hist_dir.glob("*.md")):
            summary["journals"] += 1
            if not dry_run:
                target = root / "journal" / md.name
                if not target.exists():
                    shutil.copy2(md, target)

    # 7. Archive v2 clutter safely into _archive_v2/
    archive.mkdir(parents=True, exist_ok=True)
    for name in V2_ARCHIVE_ITEMS:
        src = root / name
        if src.exists():
            summary["archived"].append(name)
            if not dry_run:
                dst = archive / name
                if dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(dst)
                    else:
                        dst.unlink()
                shutil.move(str(src), str(dst))

    # Also archive any leftover gms_trust*.bak files
    for bak in root.glob("gms_trust*"):
        summary["archived"].append(bak.name)
        if not dry_run:
            dst = archive / bak.name
            if not dst.exists():
                shutil.move(str(bak), str(dst))

    if not dry_run:
        summary["index"] = reindex_all(root)

    return summary
