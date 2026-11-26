import pytest

from gm.checkpoint import observe, save
from gm.store import save_memory


def event(root):
    return observe(root, surface="cli", harness="test", session="s1", turn="t1", trigger="explicit_request")


def test_checkpoint_save_is_idempotent_and_rejects_changed_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("GM_NO_EMBED", "1")
    receipt = event(tmp_path)
    assert event(tmp_path) == receipt
    args = dict(content="A verified value", subject="sample", predicate="value", source="user")
    first = save(tmp_path, receipt["id"], **args)
    assert save(tmp_path, receipt["id"], **args) == first
    with pytest.raises(ValueError, match="different operation"):
        save(tmp_path, receipt["id"], **{**args, "content": "another"})


def test_index_failure_recovers_without_rewriting_markdown(tmp_path, monkeypatch):
    import gm.index
    receipt = event(tmp_path)
    calls = []
    def index(root, item, background_embed=True):
        calls.append(item.id)
        if len(calls) == 1:
            raise RuntimeError("interrupted indexing")
    monkeypatch.setattr(gm.index, "index_single_item", index)
    args = dict(content="A value", title="Test fact")
    with pytest.raises(RuntimeError):
        save(tmp_path, receipt["id"], **args)
    path = tmp_path / "notes/facts/test-fact.md"
    before = path.read_bytes()
    assert save(tmp_path, receipt["id"], **args)["outcome"] == "saved"
    assert path.read_bytes() == before
    assert len(calls) == 2


def test_retry_does_not_overwrite_newer_memory(tmp_path, monkeypatch):
    import gm.index
    receipt = event(tmp_path)
    monkeypatch.setattr(gm.index, "index_single_item", lambda *a, **k: None)
    args = dict(content="original", subject="sample", predicate="value")
    save(tmp_path, receipt["id"], **args)
    save_memory(tmp_path, content="newer", subject="sample", predicate="value")
    with pytest.raises(FileExistsError):
        save(tmp_path, receipt["id"], **args)
    assert "newer" in (tmp_path / "notes/facts/sample--value.md").read_text()


def test_crash_after_markdown_is_reconciled(tmp_path, monkeypatch):
    import gm.store
    import gm.index
    receipt = event(tmp_path)
    original = gm.store.save_memory
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("crash after persistence")
    monkeypatch.setattr(gm.store, "save_memory", interrupted)
    monkeypatch.setattr(gm.index, "index_single_item", lambda *a, **k: None)
    args = dict(content="A value", title="Crash recovery")
    with pytest.raises(RuntimeError):
        save(tmp_path, receipt["id"], **args)
    path = tmp_path / "notes/facts/crash-recovery.md"
    before = path.read_bytes()
    monkeypatch.setattr(gm.store, "save_memory", original)
    assert save(tmp_path, receipt["id"], **args)["outcome"] == "saved"
    assert path.read_bytes() == before


def test_existing_memory_requires_current_revision(tmp_path, monkeypatch):
    from gm.store import markdown_revision
    import gm.index
    monkeypatch.setattr(gm.index, "index_single_item", lambda *a, **k: None)
    save_memory(tmp_path, content="old", subject="sample", predicate="value")
    receipt = event(tmp_path)
    args = dict(content="new", subject="sample", predicate="value")
    with pytest.raises(FileExistsError):
        save(tmp_path, receipt["id"], **args)
    path = tmp_path / "notes/facts/sample--value.md"
    revision = markdown_revision(path.read_text())
    assert save(tmp_path, receipt["id"], **args, expected_revision=revision)["outcome"] == "saved"


def test_pending_survives_reopen_and_disappears_on_save(tmp_path, monkeypatch):
    from gm.checkpoint import pending
    import gm.index
    monkeypatch.setattr(gm.index, "index_single_item", lambda *a, **k: None)
    assert pending(tmp_path, harness="test", session="s1") == []
    receipt = event(tmp_path)
    assert [r["id"] for r in pending(tmp_path, harness="test", session="s1")] == [receipt["id"]]
    assert pending(tmp_path, harness="test", session="other") == []
    save(tmp_path, receipt["id"], content="A fact", title="Fact")
    assert pending(tmp_path, harness="test", session="s1") == []


def test_skipped_checkpoint_cannot_be_saved(tmp_path):
    from gm.checkpoint import skip
    receipt = event(tmp_path)
    result = skip(tmp_path, receipt["id"], "unverified")
    assert skip(tmp_path, receipt["id"], "unverified") == result
    with pytest.raises(ValueError, match="skipped"):
        save(tmp_path, receipt["id"], content="unverified", title="test")


def test_project_updates_are_revision_guarded_and_recoverable(tmp_path, monkeypatch):
    from gm.store import markdown_revision, update_project
    import gm.index
    monkeypatch.setattr(gm.index, "index_single_item", lambda *a, **k: None)
    update_project(tmp_path, "alpha", "Initial", repo_root=str(tmp_path))
    path = tmp_path / "projects/alpha.md"
    before = path.read_text()
    receipt = event(tmp_path)
    args = dict(kind="project", project="alpha", content="Updated status")
    with pytest.raises(FileExistsError):
        save(tmp_path, receipt["id"], **args)
    revision = markdown_revision(before)
    result = save(tmp_path, receipt["id"], **args, expected_revision=revision)
    assert result["memory_id"] == "projects/alpha"
    assert "Updated status" in path.read_text()
    assert str(tmp_path) in path.read_text()
    update_project(tmp_path, "alpha", "Newer status")
    with pytest.raises(FileExistsError):
        save(tmp_path, receipt["id"], **args, expected_revision=revision)
    assert "Newer status" in path.read_text()


def test_recovery_rejects_edited_content_even_if_marker_is_preserved(tmp_path, monkeypatch):
    import gm.index
    from gm.store import with_markdown_body
    monkeypatch.setattr(gm.index, "index_single_item", lambda *a, **k: None)
    receipt = event(tmp_path)
    args = dict(content="Original body", title="Preserved marker")
    save(tmp_path, receipt["id"], **args)
    path = tmp_path / "notes/facts/preserved-marker.md"
    path.write_text(with_markdown_body(path.read_text(), "# Preserved marker\n\nChanged body"))
    with pytest.raises(FileExistsError, match="changed"):
        save(tmp_path, receipt["id"], **args)


def test_repeated_preference_returns_existing_reference_without_write(tmp_path, monkeypatch):
    import gm.index
    monkeypatch.setattr(gm.index, "index_single_item", lambda *a, **k: None)
    saved = save_memory(tmp_path, content="concise", subject="user", predicate="style")
    before = saved.path.read_bytes()
    receipt = event(tmp_path)
    result = save(tmp_path, receipt["id"], content="concise", subject="user", predicate="style")
    assert result["deduplicated"] and result["memory_id"] == saved.id
    assert saved.path.read_bytes() == before
    assert save(tmp_path, receipt["id"], content="concise", subject="user", predicate="style") == result


def test_journal_retry_stays_on_original_day_after_another_append(tmp_path, monkeypatch):
    import gm.index
    import gm.store

    monkeypatch.setattr(gm.index, "index_single_item", lambda *args, **kwargs: None)
    monkeypatch.setattr(gm.store, "today_str", lambda: "2026-11-25")
    receipt = event(tmp_path)
    args = dict(kind="episode", title="Pilot milestone", content="Recorded one checkpoint.")
    original = save(tmp_path, receipt["id"], **args)
    gm.store.save_memory(tmp_path, kind="journal", content="Another entry.")
    monkeypatch.setattr(gm.store, "today_str", lambda: "2026-11-26")
    assert save(tmp_path, receipt["id"], **args) == original
    path = tmp_path / "journal/2026-11-25.md"
    assert path.read_text().count("Recorded one checkpoint.") == 1
    assert "Another entry." in path.read_text()
    assert not (tmp_path / "journal/2026-11-26.md").exists()


def test_checkpoint_ledger_uses_wal_mode(tmp_path):
    import sqlite3
    event(tmp_path)
    with sqlite3.connect(tmp_path / ".gm/checkpoints.sqlite3") as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_concurrent_write_conflict_does_not_wedge_checkpoint(tmp_path, monkeypatch):
    import gm.index
    import gm.store
    from gm.checkpoint import pending, skip
    from gm.store import markdown_revision

    monkeypatch.setattr(gm.index, "index_single_item", lambda *a, **k: None)
    r1 = observe(tmp_path, surface="cli", harness="test", session="s-race", turn="t1", trigger="explicit_request")
    orig_save = gm.store.save_memory

    def racing_save(root, *args, **kwargs):
        orig_save(root, content="Concurrent external update",
                  subject=kwargs.get("subject", "race"), predicate=kwargs.get("predicate", "key"))
        return orig_save(root, *args, **kwargs)

    monkeypatch.setattr(gm.store, "save_memory", racing_save)
    with pytest.raises(FileExistsError):
        save(tmp_path, r1["id"], content="Our value", subject="race", predicate="key")

    monkeypatch.setattr(gm.store, "save_memory", orig_save)
    rev = markdown_revision((tmp_path / "notes/facts/race--key.md").read_text())
    res = save(tmp_path, r1["id"], content="Merged value", subject="race", predicate="key", expected_revision=rev)
    assert res["outcome"] == "saved"
    assert pending(tmp_path, harness="test", session="s-race") == []

    # Verify a conflicted pending checkpoint can also be cleanly skipped instead of staying wedged
    r2 = observe(tmp_path, surface="cli", harness="test", session="s-race", turn="t2", trigger="review")
    monkeypatch.setattr(gm.store, "save_memory", racing_save)
    with pytest.raises(FileExistsError):
        save(tmp_path, r2["id"], content="Our second value", subject="race", predicate="key2")
    monkeypatch.setattr(gm.store, "save_memory", orig_save)
    assert skip(tmp_path, r2["id"], "user_declined")["outcome"] == "skipped"
