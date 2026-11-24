"""Audit and backfill the headline metadata of the live fact library."""

from __future__ import annotations

import shutil
from collections.abc import Iterator, Mapping
from contextlib import nullcontext
from pathlib import Path

from .index import index_single_item
from .store import (
    MemoryItem,
    atomic_write_text,
    bucket_for_kind,
    iter_markdown_files,
    load_item,
    markdown_revision,
    memory_write_lock,
    parse_frontmatter,
    stored_fact_headline,
    with_fact_headline,
)
from .validation import HeadlineAnswer


def _scan_fact_bucket(root: Path) -> Iterator[tuple[MemoryItem, str, dict]]:
    for path, base, readonly, prefix in iter_markdown_files(root):
        try:
            readonly = readonly or path.resolve() != path
            raw = path.read_bytes().decode("utf-8")
            item = load_item(path, base, readonly=readonly, prefix=prefix, raw=raw)
        except FileNotFoundError:
            continue
        if bucket_for_kind(item.kind) == "fact":
            meta, _ = parse_frontmatter(raw)
            yield item, raw, meta


def backfill_headlines(
    root: Path,
    *,
    dry_run: bool = False,
    backup_dir: Path | None = None,
    reviewed: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, int]:
    """Add headlines across the Facts view with stable IDs, dates, bodies, and search chunks."""
    root = root.resolve()
    reviewed = reviewed or {}
    counts = dict(writable_facts=0, read_only_facts=0, missing_headlines=0, empty_facts=0,
                  incomplete_identities=0, backfilled=0)
    indexed: list[MemoryItem] = []
    changes: list[tuple[MemoryItem, str]] = []
    with nullcontext() if dry_run else memory_write_lock(root):
        for item, raw, meta in _scan_fact_bucket(root):
            if item.readonly:
                counts["read_only_facts"] += 1
                continue
            counts["writable_facts"] += 1
            counts["empty_facts"] += not item.body
            counts["incomplete_identities"] += bool(meta.get("subject")) != bool(meta.get("predicate"))
            if stored_fact_headline(meta):
                indexed.append(item)
                continue
            counts["missing_headlines"] += 1
            if item.id in reviewed:
                revision, reviewed_headline = reviewed[item.id]
                if markdown_revision(raw) != revision:
                    raise FileExistsError(f"{item.id} changed after headline review. Review that fact again.")
                item.headline = " ".join(HeadlineAnswer(headline=reviewed_headline).headline.split())
            changes.append((item, with_fact_headline(raw, item.headline)))

        if not dry_run:
            for item, updated in changes:
                if backup_dir is not None:
                    backup = backup_dir / item.rel_path
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item.path, backup)
                atomic_write_text(item.path, updated, preserve_stat=True)
                counts["backfilled"] += 1
                indexed.append(item)

    if not dry_run:
        for item in indexed:
            index_single_item(root, item, background_embed=False)
    return counts
