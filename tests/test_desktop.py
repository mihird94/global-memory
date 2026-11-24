from __future__ import annotations

import json
import os
import re
from pathlib import Path

import numpy as np
import pytest

from gm import index
from gm.desktop import Desktop
from gm.facts import backfill_headlines
from gm.store import ensure_layout, save_memory


@pytest.fixture
def desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Desktop:
    monkeypatch.setenv("GM_NO_EMBED", "1")
    monkeypatch.setenv("GM_NO_RERANK", "1")
    return Desktop(tmp_path / "memories")


def test_create_edit_archive_and_revision_conflict(desktop: Desktop) -> None:
    note = {"kind": "decision", "title": 'Local index: "Café"', "content": "Keep the source in Markdown."}
    saved = desktop.create(note)
    memory = desktop.read(saved)
    assert memory["title"] == note["title"]
    assert desktop.browse({})["total"] == 1
    assert desktop.search({"query": "Markdown"})["items"][0]["id"] == saved["id"]

    with pytest.raises(FileExistsError):
        desktop.create({**note, "content": "An accidental overwrite"})
    path = desktop.root / memory["rel_path"]
    path.write_text(memory["raw"].replace("kind: decision", "kind: decision\ncustom_key: preserved"))
    with pytest.raises(FileExistsError, match="changed on disk"):
        desktop.edit({**saved, "revision": memory["revision"], "content": "Stale content"})
    with pytest.raises(FileExistsError, match="changed on disk"):
        desktop.archive({**saved, "revision": memory["revision"]})

    latest = desktop.read(saved)
    desktop.edit({**saved, "revision": latest["revision"], "content": "Use passage indexing."})
    updated = desktop.read(saved)
    assert "custom_key: preserved" in updated["raw"]
    assert desktop.search({"query": "passage"})["items"][0]["id"] == saved["id"]
    archived = desktop.archive({**saved, "revision": updated["revision"]})
    assert (desktop.root / "_archive_v3" / archived["archived"]).read_text() == updated["raw"]
    assert desktop.browse({})["total"] == 0


def test_filters_apply_to_keyword_and_vector_candidates(desktop: Desktop, monkeypatch: pytest.MonkeyPatch) -> None:
    def vectors(texts: list[str]) -> list[np.ndarray]:
        return [np.array([1.0, 0.0], dtype=np.float32) for _ in texts]

    for day, project in (("01", "alpha"), ("11", "beta"), ("11", "alpha")):
        path = save_memory(desktop.root, "Keyword sample", title=f"Updated {day}", project=project).path
        path.write_text(re.sub(r"(?m)^updated_at:.*$", f'updated_at: "2026-11-{day}T10:00:00Z"', path.read_text()))

    filters = {"project": "alpha", "since": "2026-11-11", "until": "2026-11-11"}
    browse = desktop.browse({**filters, "refresh": True})
    assert browse["total"] == 1
    fts = desktop.search({**filters, "query": "Keyword"})
    assert [item["id"] for item in fts["items"]] == [browse["items"][0]["id"]]

    monkeypatch.setattr(index, "embed_texts", vectors)
    monkeypatch.setattr(index, "embed_query", lambda _query: vectors([""])[0])
    index.sync_index(desktop.root, with_embeddings=True)
    vector = desktop.search({**filters, "query": "semantic-only"})
    assert [item["id"] for item in vector["items"]] == [browse["items"][0]["id"]]


def test_external_markdown_is_searchable_and_read_only(desktop: Desktop, tmp_path: Path) -> None:
    source = tmp_path / "wiki"
    source.mkdir()
    (source / "remote.md").write_text("# Remote\n\nQuixotic reference.")
    config = desktop.root / ".gm" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"extra_roots": [str(source)]}))

    hit = desktop.search({"query": "Quixotic"})["items"][0]
    assert hit["id"] == "wiki:remote"
    record = desktop.read(hit)
    assert record["readonly"]
    with pytest.raises(PermissionError):
        desktop.edit({**record, "content": "A replacement"})
    with pytest.raises(PermissionError):
        desktop.archive(record)
    with pytest.raises(FileNotFoundError):
        desktop.read({"id": str(source / "remote.md")})


def test_mutable_fact_updates_and_journal_appends(desktop: Desktop) -> None:
    fact = desktop.create({"kind": "atomic", "subject": "build-runner", "predicate": "python", "content": "3.12"})
    first = desktop.read(fact)
    desktop.edit({**fact, "revision": first["revision"], "content": "3.13"})
    updated = desktop.read(fact)
    assert updated["value"] == "3.13"
    assert "**Supersedes:** 3.12" in updated["markdown"]

    journal = desktop.create({"kind": "journal", "content": "Opening journal entry."})
    assert journal == desktop.create({"kind": "journal", "content": "A second journal entry."})
    day = desktop.read(journal)
    assert "Opening journal entry." in day["markdown"]
    assert "A second journal entry." in day["markdown"]

    old = desktop.root / "journal" / "older-episode.md"
    old.write_text("---\nkind: episode\n---\n\n# Older episode\n\nLegacy marker.")
    assert desktop.browse({"kind": "journal", "refresh": True})["total"] == 2
    assert desktop.search({"kind": "journal", "query": "Legacy marker"})["items"][0]["id"] == "journal/older-episode"


def test_headlines_cover_every_kind_in_the_facts_view(desktop: Desktop) -> None:
    root = desktop.root
    legacy = {
        "profile.md": "Profile",
        "projects/atlas.md": "Atlas",
        "notes/decisions/design.md": "Design",
        "notes/lessons/lesson.md": "Lesson",
        "notes/facts/fact.md": "Fact",
        "journal/2026-11-22.md": "Journal",
    }
    for relative, title in legacy.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {title}\n\nOne verified statement for {title}.\n")

    assert backfill_headlines(root)["backfilled"] == 5
    catalog = desktop.browse({"bucket": "fact", "refresh": True})
    assert catalog["total"] == 5
    for row in catalog["items"]:
        note = desktop.read(row)
        assert row["headline"] == note["headline"] == f"One verified statement for {row['title']}."
        assert "headline:" in note["raw"]
    assert "headline:" not in (root / "journal/2026-11-22.md").read_text()

    project = desktop.create({"kind": "project", "title": "New project", "content": "Status", "headline": "Current project status"})
    assert desktop.read(project)["headline"] == "Current project status"


def test_open_library_detects_writes_from_another_caller(desktop: Desktop) -> None:
    before = desktop.browse({"refresh": True})["catalog_revision"]
    assert desktop.changes({})["catalog_revision"] == before
    other_caller = Desktop(desktop.root)
    item = other_caller.create({"kind": "fact", "title": "New", "content": "Added while the library was open."})
    revision = desktop.changes({})["catalog_revision"]
    assert revision != before
    assert desktop.browse({"bucket": "fact"})["items"][0]["id"] == item["id"]

    original = desktop.read(item)
    assert desktop.read({**item, "if_revision": original["revision"]}) == {"unchanged": True}
    path = desktop.root / original["rel_path"]
    path.write_text("# New\n\nThis change was made in a text editor.")
    os.utime(desktop.root / ".gm" / "last_sync", (1, 1))
    assert desktop.changes({})["catalog_revision"] != revision
    edited = desktop.read({**item, "if_revision": original["revision"]})
    assert "text editor" in edited["markdown"]


def test_manual_refresh_checks_markdown_during_search(desktop: Desktop) -> None:
    ensure_layout(desktop.root)
    desktop.browse({"refresh": True})
    path = desktop.root / "notes" / "facts" / "outside-index.md"
    path.write_text("# New note\n\nA zircon term.")
    assert desktop.search({"query": "zircon", "refresh": True})["items"][0]["id"] == "notes/facts/outside-index"
