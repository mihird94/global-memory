"""Markdown-first canonical storage for GM v3."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .validation import MemoryDraft, VALID_KINDS

NOTE_KINDS = ("decision", "lesson", "fact")


def bucket_for_kind(kind: str) -> str:
    return "episode" if kind in ("journal", "episode") else "fact"


def gm_home(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override).expanduser().resolve()
    env = os.environ.get("GM_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / "memories").resolve()


def ensure_layout(root: Path) -> None:
    for sub in (
        root,
        root / "projects",
        root / "notes" / "decisions",
        root / "notes" / "lessons",
        root / "notes" / "facts",
        root / "journal",
        root / ".gm",
    ):
        sub.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def slugify(text: str, max_len: int = 64) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    if not s:
        s = "note-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return s[:max_len].strip("-")


@contextmanager
def memory_write_lock(root: Path) -> Iterator[None]:
    """Serialize Markdown read-modify-write operations across local Brain callers."""
    ensure_layout(root)
    with (root / ".gm" / "write.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def markdown_revision(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, text: str, *, replace: bool = True, preserve_stat: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    original = path.stat() if preserve_stat else None
    fd, tmp_name = tempfile.mkstemp(prefix=".gm_tmp_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if original:
            os.chmod(tmp_name, stat.S_IMODE(original.st_mode))
            os.utime(tmp_name, ns=(original.st_atime_ns, original.st_mtime_ns))
        if replace:
            os.replace(tmp_name, path)
        else:
            os.link(tmp_name, path)
            os.unlink(tmp_name)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


_FRONTMATTER = re.compile(r"\A---(?P<newline>\r?\n)(?P<fields>.*?)(?m:^---[ \t]*(?P=newline))", re.DOTALL)


def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    front = _FRONTMATTER.match(raw)
    if front is None:
        return {}, raw
    body = raw[front.end():].lstrip("\r\n")
    meta: dict[str, Any] = {}
    for line in front["fields"].splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            meta[k] = [
                item.strip().strip('"').strip("'")
                for item in inner.split(",")
                if item.strip()
            ]
        elif v.startswith('"') and v.endswith('"'):
            try:
                meta[k] = json.loads(v)
            except json.JSONDecodeError:
                meta[k] = v[1:-1]
        else:
            meta[k] = v.strip('"').strip("'")
    return meta, body


def render_frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, list):
            items = ", ".join(str(x) for x in v)
            lines.append(f"{k}: [{items}]")
        else:
            s = str(v).replace("\n", " ").strip()
            if k == "headline" or any(ch in s for ch in (":", "#", '"')):
                s = json.dumps(s, ensure_ascii=False)
            lines.append(f"{k}: {s}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def with_markdown_body(raw: str, body: str) -> str:
    """Preserve the original frontmatter, including keys Brain does not interpret."""
    end = raw.find("\n---\n", 4) if raw.startswith("---\n") else -1
    if end == -1:
        return body.rstrip() + "\n"
    stamp = f'updated_at: "{now_iso()}"'
    header, count = re.subn(r"(?m)^updated_at:.*$", stamp, raw[:end], count=1)
    if not count:
        header += "\n" + stamp
    return header + "\n---\n\n" + body.strip() + "\n"


def with_fact_headline(raw: str, headline: str) -> str:
    """Set one frontmatter field while preserving the document's other bytes."""
    front = _FRONTMATTER.match(raw)
    line = f"headline: {json.dumps(headline, ensure_ascii=False)}"
    if front is None:
        newline = "\r\n" if "\r\n" in raw else "\n"
        return newline.join(("---", line, "---", "", "")) + raw
    fields, changed = re.subn(r"(?m)^[ \t]*headline[ \t]*:[^\r\n]*", lambda _: line, front["fields"], count=1)
    if not changed:
        fields += line + front["newline"]
    return raw[:front.start("fields")] + fields + raw[front.end("fields"):]


def stored_fact_headline(meta: dict[str, Any]) -> str:
    value = meta.get("headline")
    return " ".join(value.split()) if isinstance(value, str) else ""


def infer_fact_headline(body: str, title: str) -> str:
    """Take a short opening statement or use the memory title as a fallback."""
    value = atomic_fact_value(body)
    for line in (value or body).splitlines():
        text = line.strip()
        if not text or text.startswith(("#", "---", "<!--", "```", "|")):
            continue
        text = re.sub(r"^[*-]\s+", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = " ".join(text.replace("**", "").replace("`", "").split())
        if text and text != title:
            if len(text) <= 150:
                return text
            return (text[:150].rsplit(" ", 1)[0] or text[:150]).rstrip(" ,:;") + "…"
    return " ".join(title.split()) or "Fact"


def atomic_fact_value(body: str) -> str:
    fields = r"(?ms)^(?:- )?\*\*Value:\*\*[ \t]*(.*?)(?=\n(?:- )?\*\*Supersedes:\*\*|\Z)"
    value = re.search(fields, body)
    return value[1].strip() if value else ""


@dataclass
class MemoryItem:
    id: str
    path: Path
    rel_path: str
    kind: str
    title: str
    body: str
    project: str = ""
    tags: list[str] = field(default_factory=list)
    updated_at: str = ""
    mtime: float = 0.0
    readonly: bool = False
    headline: str = ""


def load_config(root: Path) -> dict[str, Any]:
    cfg_path = root / ".gm" / "config.json"
    if not cfg_path.exists():
        return {"extra_roots": []}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {"extra_roots": []}


def infer_kind_from_rel(rel_path: str) -> str:
    p = rel_path.replace("\\", "/")
    if p == "profile.md":
        return "profile"
    if p.startswith("projects/"):
        return "project"
    if p.startswith("notes/decisions/"):
        return "decision"
    if p.startswith("notes/lessons/"):
        return "lesson"
    if p.startswith("notes/facts/"):
        return "fact"
    if p.startswith("journal/"):
        return "journal"
    return "fact"


def infer_title(meta: dict[str, Any], body: str, path: Path) -> str:
    if meta.get("title"):
        return str(meta["title"])
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ").strip()


def load_item(path: Path, root: Path, readonly: bool = False, prefix: str = "", *, raw: str | None = None) -> MemoryItem:
    if raw is None:
        raw = path.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(raw)
    rel = path.relative_to(root).as_posix()
    rel_path = f"{prefix}:{rel}" if prefix else rel
    kind = str(meta.get("kind") or infer_kind_from_rel(rel))
    if kind not in VALID_KINDS:
        kind = "fact"
    title = infer_title(meta, body, path)
    headline = stored_fact_headline(meta)
    if bucket_for_kind(kind) == "fact" and not headline:
        summary = meta.get("summary") or meta.get("description")
        headline = " ".join(summary.split()) if isinstance(summary, str) and summary.strip() else infer_fact_headline(body, title)
    project = str(meta.get("project") or "")
    if not project and kind == "project":
        project = path.stem
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    stat = path.stat()
    updated_at = str(
        meta.get("updated_at")
        or datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    item_id = rel_path[:-3] if rel_path.endswith(".md") else rel_path
    return MemoryItem(
        id=item_id,
        path=path,
        rel_path=rel_path,
        kind=kind,
        title=title,
        body=body.strip(),
        project=project,
        tags=tags,
        updated_at=updated_at,
        mtime=stat.st_mtime,
        readonly=readonly,
        headline=headline,
    )


def iter_markdown_files(root: Path) -> list[tuple[Path, Path, bool, str]]:
    """Return list of (file_path, base_root, readonly, prefix)."""
    results: list[tuple[Path, Path, bool, str]] = []
    skip_dirs = {".gm", "_archive_v2", "_archive_v3", ".git", ".obsidian", ".trash"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in sorted(dirnames) if d not in skip_dirs and not d.startswith(".")]
        for fname in sorted(filenames):
            if fname.endswith(".md"):
                results.append((Path(dirpath) / fname, root, False, ""))

    cfg = load_config(root)
    for extra in cfg.get("extra_roots", []):
        epath = Path(extra).expanduser().resolve()
        if not epath.exists():
            continue
        prefix = epath.name
        for dirpath, dirnames, filenames in os.walk(epath):
            dirnames[:] = [d for d in sorted(dirnames) if not d.startswith(".")]
            for fname in sorted(filenames):
                if fname.endswith(".md"):
                    results.append((Path(dirpath) / fname, epath, True, prefix))
    return results


def _invalidate_sync_cache(root: Path) -> None:
    try:
        (root / ".gm" / "last_sync").unlink()
    except OSError:
        pass


def note_target(root: Path, draft: MemoryDraft) -> tuple[Path, str]:
    """Resolve the path and title of a fact, decision or lesson draft."""
    if draft.subject:
        title = draft.title or f"{draft.subject} | {draft.predicate}"
        slug = f"{slugify(draft.subject, 32)}--{slugify(draft.predicate, 32)}"
    else:
        title = draft.title or draft.content.splitlines()[0][:72].lstrip("#-* ").strip()
        slug = slugify(title)
        if draft.project:
            slug = f"{slugify(draft.project, 24)}-{slug}"[:72].strip("-")
    return root / "notes" / f"{draft.kind}s" / f"{slug}.md", title


def save_memory(
    root: Path,
    content: str,
    title: str = "",
    kind: str = "fact",
    project: str = "",
    tags: list[str] | None = None,
    subject: str = "",
    predicate: str = "",
    *,
    headline: str = "",
    source: str = "",
    epistemic: str = "",
    author: str = "",
    replace: bool = True,
    expected_revision: str | None = None,
    checkpoint_operation: str = "",
    checkpoint_journal_day: str = "",
) -> MemoryItem:
    draft = MemoryDraft(content=content, kind=kind, title=title, project=project, headline=headline,
                        subject=subject, predicate=predicate, source=source, epistemic=epistemic, author=author)
    content, title, project = draft.content, draft.title, draft.project
    kind = "journal" if draft.kind == "episode" else draft.kind
    if checkpoint_operation and not re.fullmatch(r"[0-9a-f]{32}", checkpoint_operation):
        raise ValueError("Invalid checkpoint operation or unsupported memory kind")
    if checkpoint_journal_day and (kind != "journal" or not checkpoint_operation
                                   or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", checkpoint_journal_day)):
        raise ValueError("Invalid checkpoint journal date")
    headline = draft.headline
    source, author = draft.source, draft.author
    epistemic = draft.epistemic or (
        "decision" if kind == "decision" else ("lesson" if kind == "lesson" else ("verified" if kind in ("fact", "project") else ""))
    )
    ensure_layout(root)
    _invalidate_sync_cache(root)

    ts = now_iso()
    tag_list = [t.strip() for t in (tags or []) if t.strip()]

    if kind == "journal":
        day = checkpoint_journal_day or today_str()
        path = root / "journal" / f"{day}.md"
        stamp = datetime.now().strftime("%H:%M")
        header = f"## {stamp}" + (f" — {title}" if title else "")
        if project:
            header += f" [{project}]"
        entry = f"\n{header}\n{content}\n"
        marker = ""
        if checkpoint_operation:
            marker = f"<!-- brain-checkpoint:{checkpoint_operation} -->"
            entry = f"\n{marker}\n{header}\n{content}\n{marker}\n"
        with memory_write_lock(root):
            if path.exists():
                existing = path.read_text(encoding="utf-8")
                _, body = parse_frontmatter(existing)
                if marker and marker in body:
                    raise FileExistsError("This checkpoint already appears in the journal.")
                atomic_write_text(path, with_markdown_body(existing, body.rstrip() + "\n" + entry))
            else:
                fm = render_frontmatter({"kind": "journal", "title": f"Journal {day}", "updated_at": ts})
                atomic_write_text(path, fm + f"# Journal {day}\n" + entry)
            return load_item(path, root)

    if kind == "project":
        proj_name = project or title
        if not proj_name:
            raise ValueError("project name or title is required for kind='project'")
        return update_project(root, proj_name, content, headline=headline, replace=replace,
                              expected_revision=expected_revision, checkpoint_operation=checkpoint_operation)

    # Lightweight 3-part fact notation: (subject, predicate, value) auto-supersedes by (subject, predicate)
    subj, pred = draft.subject, draft.predicate
    path, note_title = note_target(root, draft)
    if kind == "fact" and subj and pred:
        fm = render_frontmatter(
            {
                "title": note_title,
                "headline": headline or infer_fact_headline(content, note_title),
                "kind": "fact",
                "subject": subj,
                "predicate": pred,
                "project": project,
                "tags": tag_list,
                "epistemic": epistemic,
                "source": source,
                "author": author,
                "checkpoint_operation": checkpoint_operation,
                "updated_at": ts,
            }
        )
        lines = [
            f"# {note_title}",
            "",
            f"- **Subject:** {subj}",
            f"- **Predicate:** {pred}",
            f"- **Value:** {content}",
        ]
        with memory_write_lock(root):
            previous = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            if expected_revision is not None and markdown_revision(previous) != expected_revision:
                raise FileExistsError("This memory changed on disk. Reopen it before editing.")
            _, prev_body = parse_frontmatter(previous)
            prev = atomic_fact_value(prev_body)
            if prev and prev != content:
                lines.append(f"- **Supersedes:** {prev}")
            atomic_write_text(path, fm + "\n".join(lines) + "\n", replace=replace)
            return load_item(path, root)

    # Atomic note under notes/<kind>s/<slug>.md
    if not headline:
        headline = infer_fact_headline(content, note_title)

    fm = render_frontmatter(
        {
            "title": note_title,
            "headline": headline,
            "kind": kind,
            "project": project,
            "tags": tag_list,
            "epistemic": epistemic,
            "source": source,
            "author": author,
            "checkpoint_operation": checkpoint_operation,
            "updated_at": ts,
        }
    )
    body = content if content.startswith("# ") else f"# {note_title}\n\n{content}\n"
    with memory_write_lock(root):
        if expected_revision is not None:
            previous = path.read_text(encoding="utf-8") if path.exists() else ""
            if markdown_revision(previous) != expected_revision:
                raise FileExistsError("This memory changed on disk. Reopen it before editing.")
        atomic_write_text(path, fm + body, replace=replace)
        return load_item(path, root)


def update_project(
    root: Path,
    name: str,
    update: str = "",
    *,
    repo_root: str = "",
    headline: str = "",
    replace: bool = True,
    expected_revision: str | None = None,
    checkpoint_operation: str = "",
) -> MemoryItem:
    ensure_layout(root)
    slug = slugify(name, 48)
    path = root / "projects" / f"{slug}.md"
    if not update.strip() and not repo_root.strip():
        if not path.exists():
            raise FileNotFoundError(f"Project '{slug}' not found")
        return load_item(path, root)

    with memory_write_lock(root):
        previous = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        if expected_revision is not None and markdown_revision(previous) != expected_revision:
            raise FileExistsError("This memory changed on disk. Reopen it before editing.")
        existing_meta, existing_body = parse_frontmatter(previous)
        resolved_repo_root = repo_root.strip() or str(existing_meta.get("repo_root") or "")
        if resolved_repo_root:
            resolved_repo_root = str(Path(resolved_repo_root).expanduser().resolve())
        body = update.strip() or existing_body.strip() or f"# {name.strip()}"
        if not body.startswith("# "):
            body = f"# {name.strip()}\n\n{body}"
        fm = render_frontmatter({
            "title": str(existing_meta.get("title") or name.strip()),
            "headline": headline or infer_fact_headline(body, name.strip()),
            "kind": "project", "project": slug, "repo_root": resolved_repo_root,
            "checkpoint_operation": checkpoint_operation, "updated_at": now_iso(),
        })
        atomic_write_text(path, fm + body + "\n", replace=replace)
        _invalidate_sync_cache(root)
        return load_item(path, root)


def resolve_path(root: Path, id_or_path: str) -> Path:
    root = root.resolve()
    raw = id_or_path.strip()
    if not raw or "\0" in raw:
        raise ValueError("Provide a memory ID from brain_search or a Markdown path within a configured memory root.")
    extras = [Path(extra).expanduser().resolve() for extra in load_config(root).get("extra_roots", [])]
    requested = Path(raw).expanduser()
    prefix, separator, relative = raw.partition(":")
    named_roots = [extra for extra in extras if extra.name == prefix] if separator and not requested.is_absolute() else []
    if named_roots:
        candidates = [(extra / relative, (extra,)) for extra in named_roots]
    else:
        roots = (root, *extras) if requested.is_absolute() else (root,)
        candidates = [(root / requested, roots)]
    for candidate, allowed in candidates:
        for path in (candidate, Path(str(candidate) + ".md")):
            resolved = path.resolve()
            if not any(resolved.is_relative_to(base) for base in allowed):
                raise PermissionError("Choose an ID or Markdown path within a configured memory root.")
            if resolved.suffix == ".md" and resolved.is_file():
                return resolved
    raise FileNotFoundError("Memory not found. Run brain_search and use the ID from the result.")


def read_memory(root: Path, id_or_path: str) -> tuple[str, str]:
    path = resolve_path(root, id_or_path)
    return str(path), path.read_text(encoding="utf-8", errors="replace")


def forget_memory(root: Path, id_or_path: str, *, expected_revision: str | None = None) -> str:
    root = root.resolve()
    with memory_write_lock(root):
        path = resolve_path(root, id_or_path)
        try:
            rel = path.relative_to(root)
        except ValueError:
            raise PermissionError("This source is read-only. Choose an active memory from the shared store.") from None
        if any(part.startswith((".", "_archive")) for part in rel.parts):
            raise PermissionError("Choose an active memory ID from brain_search to archive.")
        if expected_revision is not None:
            raw = path.read_text(encoding="utf-8", errors="replace")
            if markdown_revision(raw) != expected_revision:
                raise FileExistsError("This memory changed on disk. Reopen it before archiving.")
        archive_root = root / "_archive_v3"
        archive_dst = archive_root / rel
        if archive_dst.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            archive_dst = archive_dst.with_name(f"{archive_dst.stem}-{stamp}{archive_dst.suffix}")
        archive_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(archive_dst))
        return archive_dst.relative_to(archive_root).as_posix()


def list_projects(root: Path) -> list[str]:
    proj_dir = root / "projects"
    if not proj_dir.exists():
        return []
    return sorted(p.stem for p in proj_dir.glob("*.md"))


def detect_project(root: Path, cwd: str | None = None) -> str:
    projects = list_projects(root)
    if not projects:
        return ""
    cur = Path(cwd or os.getcwd()).resolve()

    # 1. Prefer explicit repo_root / roots frontmatter in projects/*.md
    proj_dir = root / "projects"
    best_match: tuple[int, str] | None = None
    for slug in projects:
        p = proj_dir / f"{slug}.md"
        try:
            meta, _ = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        roots_raw = meta.get("roots") or ([] if not meta.get("repo_root") else [meta["repo_root"]])
        if isinstance(roots_raw, str):
            roots_raw = [roots_raw]
        for rr in roots_raw:
            try:
                rp = Path(str(rr)).expanduser().resolve()
                if cur.is_relative_to(rp):
                    depth = len(rp.parts)
                    if best_match is None or depth > best_match[0]:
                        best_match = (depth, slug)
            except Exception:
                continue
    if best_match is not None:
        return best_match[1]

    # 2. Fallback: match slug against last 3 directory components
    names = {slugify(part, 48) for part in cur.parts[-3:]}
    for slug in projects:
        if slug.lower() in names:
            return slug
    return ""
