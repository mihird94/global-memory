"""SQLite chunk-level index: FTS5 BM25 + Ollama embeddings + ONNX cross-encoder + confidence gate."""

from __future__ import annotations

import fcntl
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .retrieval import (
    blob_to_vec,
    embed_model,
    embed_query,
    embed_texts,
    rerank_candidates,
    vec_to_blob,
)
from .store import (
    MemoryItem,
    bucket_for_kind,
    detect_project,
    ensure_layout,
    iter_markdown_files,
    list_projects,
    load_item,
    memory_write_lock,
)
from .validation import SearchRequest, normalize_project_slug

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS docs (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    rel_path TEXT UNIQUE NOT NULL,
    bucket TEXT NOT NULL DEFAULT 'fact',
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    headline TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    mtime REAL NOT NULL DEFAULT 0,
    body TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT UNIQUE NOT NULL,
    doc_id TEXT NOT NULL,
    chunk_idx INTEGER NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    mtime REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    mtime REAL NOT NULL,
    vec BLOB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cemb_doc_id ON chunk_embeddings(doc_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    heading,
    text,
    content='chunks',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, heading, text)
    VALUES (new.rowid, new.heading, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, heading, text)
    VALUES ('delete', old.rowid, old.heading, old.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, heading, text)
    VALUES ('delete', old.rowid, old.heading, old.text);
    INSERT INTO chunks_fts(rowid, heading, text)
    VALUES (new.rowid, new.heading, new.text);
END;
"""

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "for", "from", "how",
    "i", "in", "is", "it", "my", "of", "on", "or", "should", "that", "the", "to",
    "was", "what", "when", "where", "which", "who", "why", "with",
}


def _connect(root: Path) -> sqlite3.Connection:
    ensure_layout(root)
    db_path = root / ".gm" / "index.sqlite"
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.executescript(SCHEMA_SQL)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(docs)")}
    if {"bucket", "headline"} - cols:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(docs)")}
            if "bucket" not in cols:
                conn.execute("ALTER TABLE docs ADD COLUMN bucket TEXT NOT NULL DEFAULT 'fact'")
                conn.execute("UPDATE docs SET bucket = CASE WHEN kind IN ('journal','episode') THEN 'episode' ELSE 'fact' END")
            if "headline" not in cols:
                conn.execute("ALTER TABLE docs ADD COLUMN headline TEXT NOT NULL DEFAULT ''")
    return conn


def _chunk_markdown(title: str, body: str, max_chars: int = 850, overlap: int = 100) -> list[tuple[str, str]]:
    """Split Markdown by ## / ### headings, then window long sections with overlap."""
    sections: list[tuple[str, str]] = []
    cur_heading = title
    cur_lines: list[str] = []

    for line in body.splitlines():
        if re.match(r"^#{2,3}\s+", line):
            sec_text = "\n".join(cur_lines).strip()
            if sec_text:
                sections.append((cur_heading, sec_text))
            cur_heading = re.sub(r"^#{2,3}\s+", "", line).strip() or title
            cur_lines = []
        else:
            cur_lines.append(line)
    tail = "\n".join(cur_lines).strip()
    if tail:
        sections.append((cur_heading, tail))

    if not sections:
        sections = [(title, body.strip() or title)]

    chunks: list[tuple[str, str]] = []
    for heading, sec_text in sections:
        prefix = f"{title} — {heading}\n" if heading != title else f"{title}\n"
        if len(sec_text) <= max_chars:
            chunks.append((heading, (prefix + sec_text).strip()))
            continue
        start = 0
        while start < len(sec_text):
            end = min(len(sec_text), start + max_chars)
            # Snap to whitespace boundary when possible
            if end < len(sec_text):
                ws = sec_text.rfind(" ", start + max_chars // 2, end)
                if ws != -1:
                    end = ws
            piece = sec_text[start:end].strip()
            if piece:
                chunks.append((heading, (prefix + piece).strip()))
            if end >= len(sec_text):
                break
            start = max(end - overlap, start + 1)
    return chunks


def _replace_chunks(conn: sqlite3.Connection, item: MemoryItem) -> None:
    conn.execute("DELETE FROM chunks WHERE doc_id = ?", (item.id,))
    conn.execute("DELETE FROM chunk_embeddings WHERE doc_id = ?", (item.id,))
    chunks = _chunk_markdown(item.title, item.body)
    for idx, (heading, text) in enumerate(chunks):
        chunk_id = f"{item.id}#{idx}"
        conn.execute(
            """
            INSERT INTO chunks(chunk_id, doc_id, chunk_idx, heading, text, mtime)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chunk_id, item.id, idx, heading, text, item.mtime),
        )


def _upsert_item(conn: sqlite3.Connection, item: MemoryItem) -> bool:
    """Upsert a Markdown item and rebuild its chunks if modified or unchunked."""
    tags_str = " ".join(item.tags)
    bucket = bucket_for_kind(item.kind)
    existing = conn.execute("SELECT mtime, headline FROM docs WHERE id = ?", (item.id,)).fetchone()
    has_chunks = conn.execute("SELECT 1 FROM chunks WHERE doc_id = ? LIMIT 1", (item.id,)).fetchone() is not None

    if existing:
        if abs(float(existing["mtime"]) - item.mtime) < 1e-6 and has_chunks:
            if existing["headline"] == item.headline:
                return False
            conn.execute("UPDATE docs SET headline = ? WHERE id = ?", (item.headline, item.id))
            return True
        conn.execute(
            """
            UPDATE docs
            SET rel_path=?, bucket=?, kind=?, title=?, headline=?, project=?, tags=?, updated_at=?, mtime=?, body=?
            WHERE id=?
            """,
            (
                item.rel_path,
                bucket,
                item.kind,
                item.title,
                item.headline,
                item.project,
                tags_str,
                item.updated_at,
                item.mtime,
                item.body,
                item.id,
            ),
        )
        _replace_chunks(conn, item)
        return True

    conn.execute(
        """
        INSERT INTO docs(id, rel_path, bucket, kind, title, headline, project, tags, updated_at, mtime, body)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.id,
            item.rel_path,
            bucket,
            item.kind,
            item.title,
            item.headline,
            item.project,
            tags_str,
            item.updated_at,
            item.mtime,
            item.body,
        ),
    )
    _replace_chunks(conn, item)
    return True


def _sync_embeddings(conn: sqlite3.Connection, batch_size: int = 16) -> int:
    """Embed any chunks missing an up-to-date embedding for the current Ollama model."""
    model = embed_model()
    rows = conn.execute(
        """
        SELECT c.chunk_id, c.doc_id, c.text, c.mtime, d.project, d.tags
        FROM chunks c
        JOIN docs d ON d.id = c.doc_id
        LEFT JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id AND e.model = ?
        WHERE e.chunk_id IS NULL OR abs(e.mtime - c.mtime) > 1e-6
        """,
        (model,),
    ).fetchall()
    if not rows:
        return 0

    embedded = 0
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        texts = [
            f"{r['project']} {r['tags']}\n{r['text']}".strip()
            for r in chunk
        ]
        vecs = embed_texts(texts)
        if vecs is None:
            break
        for r, vec in zip(chunk, vecs):
            conn.execute(
                """
                INSERT INTO chunk_embeddings(chunk_id, doc_id, model, dim, mtime, vec)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    doc_id=excluded.doc_id,
                    model=excluded.model,
                    dim=excluded.dim,
                    mtime=excluded.mtime,
                    vec=excluded.vec
                """,
                (r["chunk_id"], r["doc_id"], model, int(vec.shape[0]), float(r["mtime"]), vec_to_blob(vec)),
            )
            embedded += 1
        conn.commit()
    return embedded


def trigger_background_embed(root: Path) -> bool:
    """Spawn a detached, lock-guarded background embedder so agent calls never block on Ollama."""
    if os.environ.get("GM_NO_EMBED") == "1" or os.environ.get("GM_NO_BG_EMBED") == "1":
        return False
    ensure_layout(root)
    lock_path = root / ".gm" / "embed.lock"
    # Quick non-blocking check: skip spawning if a background embedder is already running
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BlockingIOError:
            return False
        finally:
            os.close(fd)
    except OSError:
        pass

    try:
        subprocess.Popen(
            [sys.executable, "-m", "gm.cli", "--home", str(root), "embed-missing"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:
        return False


def embed_missing(root: Path) -> dict[str, int]:
    """Lock-guarded incremental Ollama embedding pass (safe to run in background)."""
    ensure_layout(root)
    lock_path = root / ".gm" / "embed.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"embedded": 0, "skipped_locked": 1}
        conn = _connect(root)
        try:
            n = _sync_embeddings(conn)
            return {"embedded": n, "skipped_locked": 0}
        finally:
            conn.close()
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def index_single_item(root: Path, item: MemoryItem, background_embed: bool = True) -> None:
    """Fast (~1ms) single-item FTS5 upsert after a write — no directory walk, no blocking embed."""
    with memory_write_lock(root):
        try:
            if item.path.stat().st_mtime != item.mtime:
                item = load_item(item.path, root)
        except FileNotFoundError:
            return
        conn = _connect(root)
        try:
            _upsert_item(conn, item)
            conn.commit()
        finally:
            conn.close()
    if background_embed:
        trigger_background_embed(root)


def sync_index(
    root: Path,
    with_embeddings: bool = False,
    background_embed: bool = False,
    max_age_seconds: float = 0.0,
) -> dict[str, int]:
    """Incrementally sync Markdown files -> chunks -> SQLite FTS5 (<15ms).

    When `max_age_seconds > 0` and a full walk ran recently (`.gm/last_sync`), skip the directory walk
    so repeated `brain_search` calls stay fast even with large read-only Obsidian roots.
    """
    marker = root / ".gm" / "last_sync"
    db_path = root / ".gm" / "index.sqlite"
    if max_age_seconds > 0 and not with_embeddings and db_path.exists():
        try:
            recent = (time.time() - marker.stat().st_mtime) < max_age_seconds
        except FileNotFoundError:
            recent = False
        if recent:
            return {"indexed": 0, "chunks": 0, "removed": 0, "embedded": 0, "skipped_ttl": 1}

    conn = _connect(root)
    try:
        seen_ids: set[str] = set()
        indexed = 0
        changed = False
        with memory_write_lock(root):
            for fpath, base_root, readonly, prefix in iter_markdown_files(root):
                try:
                    item = load_item(fpath, base_root, readonly=readonly, prefix=prefix)
                except FileNotFoundError:
                    continue
                seen_ids.add(item.id)
                if _upsert_item(conn, item):
                    changed = True
                indexed += 1

            existing_ids = {row["id"] for row in conn.execute("SELECT id FROM docs")}
            stale = existing_ids - seen_ids
            for sid in stale:
                conn.execute("DELETE FROM docs WHERE id = ?", (sid,))
                conn.execute("DELETE FROM chunks WHERE doc_id = ?", (sid,))
                conn.execute("DELETE FROM chunk_embeddings WHERE doc_id = ?", (sid,))
            conn.commit()

        embedded = _sync_embeddings(conn) if with_embeddings else 0
        chunks_total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        missing_emb = 0
        if not with_embeddings and background_embed:
            missing_emb = conn.execute(
                """
                SELECT COUNT(*) FROM chunks c
                LEFT JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id AND e.model = ?
                WHERE e.chunk_id IS NULL OR abs(e.mtime - c.mtime) > 1e-6
                """,
                (embed_model(),),
            ).fetchone()[0]
    finally:
        conn.close()

    bg_spawned = False
    if background_embed and (changed or missing_emb > 0):
        bg_spawned = trigger_background_embed(root)

    try:
        marker.touch()
    except OSError:
        pass

    return {
        "indexed": indexed,
        "chunks": chunks_total,
        "removed": len(stale),
        "embedded": embedded,
        "bg_embed_spawned": int(bg_spawned),
    }


def reindex_all(root: Path) -> dict[str, int]:
    """Drop and rebuild SQLite chunk FTS5 + Ollama embeddings from scratch."""
    db_path = root / ".gm" / "index.sqlite"
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    return sync_index(root, with_embeddings=True)


def index_stats(root: Path) -> dict[str, int]:
    db_path = root / ".gm" / "index.sqlite"
    if not db_path.exists():
        return {"docs": 0, "chunks": 0, "facts": 0, "episodes": 0, "embedded": 0}
    conn = _connect(root)
    try:
        total = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        facts = conn.execute("SELECT COUNT(*) FROM docs WHERE bucket='fact'").fetchone()[0]
        episodes = conn.execute("SELECT COUNT(*) FROM docs WHERE bucket='episode'").fetchone()[0]
        emb = conn.execute("SELECT COUNT(*) FROM chunk_embeddings WHERE model=?", (embed_model(),)).fetchone()[0]
        return {"docs": total, "chunks": chunks, "facts": facts, "episodes": episodes, "embedded": emb}
    finally:
        conn.close()


def _fts_query(raw: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", raw)
    if not tokens:
        return ""
    if len(tokens) == 1:
        return f'"{tokens[0]}"*'
    return " ".join(f'"{t}"*' if len(t) >= 3 else f'"{t}"' for t in tokens)


def _fts_query_or(raw: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", raw)
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"*' if len(t) >= 3 else f'"{t}"' for t in tokens)


def _recency_multiplier(bucket: str, updated_at: str) -> float:
    """Apply gentle temporal decay ONLY to episodes; facts stay evergreen."""
    if bucket != "episode" or not updated_at:
        return 1.0
    try:
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        age_days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
        return max(0.55, math.exp(-0.015 * age_days))
    except Exception:
        return 1.0


def _make_snippet(body: str, query_tokens: list[str], max_chars: int = 240) -> str:
    clean = re.sub(r"\s+", " ", body).strip()
    if len(clean) <= max_chars:
        return clean
    lower = clean.lower()
    ranked_tokens = sorted(
        [t for t in query_tokens if t.lower() not in _STOPWORDS] or query_tokens,
        key=len,
        reverse=True,
    )
    pos = -1
    for tok in ranked_tokens:
        idx = lower.find(tok.lower())
        if idx != -1:
            pos = idx
            break
    if pos == -1:
        return clean[:max_chars].rstrip() + "..."
    start = max(0, pos - 70)
    end = min(len(clean), start + max_chars)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(clean) else ""
    return prefix + clean[start:end].strip() + suffix


def _doc_filters(
    bucket: str = "", kind: str = "", since: str = "", until: str = "", project: str = ""
) -> tuple[list[str], list[str]]:
    where: list[str] = []
    params: list[str] = []
    if kind in ("journal", "episode"):
        where.append("d.kind IN ('journal', 'episode')")
        kind = ""
    for value, condition in (
        (bucket, "d.bucket = ?"),
        (kind, "d.kind = ?"),
        (since[:10], "substr(d.updated_at, 1, 10) >= ?"),
        (until[:10], "substr(d.updated_at, 1, 10) <= ?"),
        (project, "lower(d.project) = lower(?)"),
    ):
        if value:
            where.append(condition)
            params.append(value)
    return where, params


def _fts_chunk_candidates(
    conn: sqlite3.Connection,
    query: str,
    bucket: str,
    kind: str,
    since: str = "",
    until: str = "",
    k: int = 35,
    project_filter: str = "",
) -> list[dict[str, Any]]:
    q_and = _fts_query(query)
    if not q_and:
        return []
    q_tokens = re.findall(r"[A-Za-z0-9_]+", query)

    filters, values = _doc_filters(bucket, kind, since, until, project_filter)
    where = ["chunks_fts MATCH ?", *filters]
    params = [q_and, *values]

    sql = f"""
        SELECT c.chunk_id, c.doc_id, c.heading, c.text AS chunk_text,
               d.rel_path, d.bucket, d.kind, d.title, d.headline, d.project, d.updated_at,
               bm25(chunks_fts, 2.5, 1.0) AS rank
        FROM chunks_fts
        JOIN chunks c ON c.rowid = chunks_fts.rowid
        JOIN docs d ON d.id = c.doc_id
        WHERE {' AND '.join(where)}
        ORDER BY rank
        LIMIT ?
    """
    rows = conn.execute(sql, [*params, k]).fetchall()
    if not rows and len(q_tokens) > 1:
        params[0] = _fts_query_or(query)
        rows = conn.execute(sql, [*params, k]).fetchall()
    return [dict(r) for r in rows]


def _vector_chunk_candidates(
    conn: sqlite3.Connection,
    q_vec: np.ndarray,
    bucket: str,
    kind: str,
    since: str = "",
    until: str = "",
    k: int = 35,
    project_filter: str = "",
) -> list[dict[str, Any]]:
    filters, values = _doc_filters(bucket, kind, since, until, project_filter)
    where = ["e.model = ?", "abs(e.mtime - c.mtime) < 1e-6", *filters]
    params = [embed_model(), *values]

    rows = conn.execute(
        f"""
        SELECT c.chunk_id, c.doc_id, c.heading, c.text AS chunk_text,
               d.rel_path, d.bucket, d.kind, d.title, d.headline, d.project, d.updated_at,
               e.dim, e.vec
        FROM chunk_embeddings e
        JOIN chunks c ON c.chunk_id = e.chunk_id
        JOIN docs d ON d.id = c.doc_id
        WHERE {' AND '.join(where)}
        """,
        params,
    ).fetchall()
    if not rows:
        return []

    q_dim = int(q_vec.shape[0])
    valid_rows = [r for r in rows if int(r["dim"]) == q_dim]
    if not valid_rows:
        return []

    mat = np.vstack([blob_to_vec(r["vec"]) for r in valid_rows])
    sims = mat @ q_vec
    top_idx = np.argsort(sims)[::-1][:k]
    out: list[dict[str, Any]] = []
    for idx in top_idx:
        sim = float(sims[int(idx)])
        if sim < 0.15:
            continue
        item = dict(valid_rows[int(idx)])
        item.pop("vec", None)
        item["vec_sim"] = sim
        out.append(item)
    return out


_VALUE_LITERAL_RE = re.compile(
    r"(?:\b\d{1,3}(?:\.\d{1,3}){3}\b|\$?\b\d[\d,]*(?:\.\d+)?%?\b|\bv?\d+\.\d+(?:\.\d+)?\b|https?://\S+)"
)


def _content_tokens(text: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r"[A-Za-z0-9_]+", text)
        if len(t) >= 2 and t.lower() not in _STOPWORDS
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _extract_value_text(hit: dict[str, Any]) -> str:
    txt = hit.get("headline") or hit.get("snippet") or ""
    m = re.search(r"\*\*Value:\*\*\s*([^\n]+)", hit.get("snippet", ""))
    return m.group(1).strip() if m else txt


def _detect_read_conflicts(conn: sqlite3.Connection, hits: list[dict[str, Any]]) -> None:
    """Lazy MVCC-style read-time conflict detection via split key-overlap + value-divergence."""
    fact_hits = [h for h in hits if h.get("bucket") == "fact"]
    if len(fact_hits) < 2:
        return

    # Load existing chunk embeddings for returned fact hits (<0.1ms, zero Ollama calls)
    cids = [h["chunk_id"] for h in fact_hits if h.get("chunk_id")]
    vecs: dict[str, np.ndarray] = {}
    if cids:
        placeholders = ",".join("?" for _ in cids)
        rows = conn.execute(
            f"SELECT chunk_id, vec FROM chunk_embeddings WHERE model = ? AND chunk_id IN ({placeholders})",
            [embed_model(), *cids],
        ).fetchall()
        for r in rows:
            vecs[r["chunk_id"]] = blob_to_vec(r["vec"])

    for i in range(len(fact_hits)):
        a = fact_hits[i]
        a_key = _content_tokens(f"{a.get('title', '')} {a.get('heading', '')}")
        a_val_txt = _extract_value_text(a)
        a_lits = set(_VALUE_LITERAL_RE.findall(a_val_txt))
        a_val_toks = _content_tokens(a_val_txt) - a_key
        va = vecs.get(a.get("chunk_id", ""))

        for j in range(i + 1, len(fact_hits)):
            b = fact_hits[j]
            if a["id"] == b["id"]:
                continue
            # Scoped rules in different projects are not conflicts
            if a.get("project") and b.get("project") and a["project"].lower() != b["project"].lower():
                continue

            b_key = _content_tokens(f"{b.get('title', '')} {b.get('heading', '')}")
            key_jacc = _jaccard(a_key, b_key)
            vb = vecs.get(b.get("chunk_id", ""))
            vec_sim = float(va @ vb) if (va is not None and vb is not None and va.shape == vb.shape) else 0.0

            # Signal 1: high topical / slot collision (key overlap OR high chunk cosine)
            if key_jacc < 0.45 and vec_sim < 0.78:
                continue

            # Signal 2: value divergence (different concrete literals, or same slot with divergent values)
            b_val_txt = _extract_value_text(b)
            b_lits = set(_VALUE_LITERAL_RE.findall(b_val_txt))
            b_val_toks = _content_tokens(b_val_txt) - b_key
            val_jacc = _jaccard(a_val_toks, b_val_toks)

            literal_conflict = bool(a_lits and b_lits and a_lits != b_lits and not (a_lits <= b_lits or b_lits <= a_lits))
            slot_value_conflict = (key_jacc >= 0.55 and bool(a_val_toks) and bool(b_val_toks) and val_jacc < 0.45)

            if not (literal_conflict or slot_value_conflict):
                continue

            reason = "divergent values/literals" if literal_conflict else "same topic with divergent values"
            a.setdefault("conflicts_with", []).append(
                {"id": b["id"], "updated_at": b["updated_at"], "reason": reason}
            )
            b.setdefault("conflicts_with", []).append(
                {"id": a["id"], "updated_at": a["updated_at"], "reason": reason}
            )


def _confidence_label(score: float, reranked: bool) -> str:
    if not reranked:
        return "medium" if score >= 0.45 else "low"
    if score >= 0.25:
        return "high"
    if score >= 0.15:
        return "medium"
    return "low"


def recall(
    root: Path,
    query: str,
    project: str = "",
    kind: str = "",
    bucket: str = "",
    since: str = "",
    until: str = "",
    limit: int = 8,
    use_rerank: bool = True,
    min_score: float = 0.0,
    *,
    project_filter: str = "",
) -> list[dict[str, Any]]:
    """3-stage chunk-level hybrid recall: FTS5 + Ollama embeddings -> RRF -> ONNX rerank + confidence."""
    request = SearchRequest(query=query, project=project, kind=kind, bucket=bucket, since=since, until=until, limit=limit)
    # Never block agent recall on bulk doc embedding; throttle directory walks via 60s TTL
    ttl = float(os.environ.get("GM_SYNC_TTL", "60"))
    sync_index(root, with_embeddings=False, background_embed=True, max_age_seconds=ttl)
    query, limit = request.query, request.limit
    scope = dict(bucket=request.bucket, kind=request.kind, since=request.since, until=request.until,
                 project_filter=project_filter)

    q_tokens = re.findall(r"[A-Za-z0-9_]+", query)
    conn = _connect(root)
    try:
        fts_hits = _fts_chunk_candidates(conn, query, **scope)
        q_vec = embed_query(query)
        vec_hits = (
            _vector_chunk_candidates(conn, q_vec, **scope)
            if q_vec is not None
            else []
        )

        # Stage 1: Chunk-level RRF, then keep best chunk per doc_id
        chunk_pool: dict[str, dict[str, Any]] = {}
        chunk_rrf: dict[str, float] = {}
        rrf_k = 60.0
        for rank, row in enumerate(fts_hits, start=1):
            cid = row["chunk_id"]
            chunk_pool[cid] = row
            chunk_rrf[cid] = chunk_rrf.get(cid, 0.0) + 1.0 / (rrf_k + rank)
        for rank, row in enumerate(vec_hits, start=1):
            cid = row["chunk_id"]
            chunk_pool.setdefault(cid, row)
            chunk_rrf[cid] = chunk_rrf.get(cid, 0.0) + 1.0 / (rrf_k + rank)

        if not chunk_pool:
            return []

        best_by_doc: dict[str, tuple[float, dict[str, Any]]] = {}
        for cid, score in chunk_rrf.items():
            row = chunk_pool[cid]
            did = row["doc_id"]
            if did not in best_by_doc or score > best_by_doc[did][0]:
                best_by_doc[did] = (score, row)

        ranked_docs = sorted(best_by_doc.values(), key=lambda x: x[0], reverse=True)[: max(limit * 3, 20)]
        candidates = [row for _, row in ranked_docs]
        rrf_scores = [sc for sc, _ in ranked_docs]

        # Stage 2: ONNX cross-encoder reranking on the winning chunk text
        rerank_scores: list[float] | None = None
        if use_rerank and len(candidates) >= 1:
            passages = [c["chunk_text"][:900] for c in candidates]
            rerank_scores = rerank_candidates(query, passages, cache_dir=root / ".gm" / "models")

        reranked = rerank_scores is not None
        mode_parts = ["hybrid" if vec_hits else "fts"]
        if reranked:
            mode_parts.append("rerank")
        mode = "+".join(mode_parts)

        # Stage 3: Final scoring + confidence gating
        proj_l = request.project.lower()
        scored: list[tuple[float, dict[str, Any]]] = []
        for idx, c in enumerate(candidates):
            base = rerank_scores[idx] if reranked else (rrf_scores[idx] * 30.0)
            if proj_l and c["project"].lower() == proj_l:
                base += 0.12 if reranked else base * 0.35
            base *= _recency_multiplier(c["bucket"], c["updated_at"])
            if min_score > 0.0 and base < min_score:
                continue
            scored.append(
                (
                    base,
                    {
                        "id": c["doc_id"],
                        "chunk_id": c["chunk_id"],
                        "heading": c["heading"],
                        "title": c["title"],
                        "headline": c["headline"],
                        "bucket": c["bucket"],
                        "kind": c["kind"],
                        "project": c["project"],
                        "updated_at": c["updated_at"][:10],
                        "rel_path": c["rel_path"],
                        "snippet": _make_snippet(c["chunk_text"], q_tokens),
                        "score": round(base, 4),
                        "confidence": _confidence_label(base, reranked),
                        "mode": mode,
                    },
                )
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        top_hits = [item for _, item in scored[:limit]]
        _detect_read_conflicts(conn, top_hits)
        return top_hits
    finally:
        conn.close()


def _summarize_profile(profile_path: Path, max_lines: int = 12) -> str:
    if not profile_path.exists():
        return ""
    lines = profile_path.read_text(encoding="utf-8", errors="replace").splitlines()
    picked: list[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("---") or s.startswith("$$"):
            continue
        if s.startswith(("# ", "## ", "* ", "- ")):
            picked.append(s)
        if len(picked) >= max_lines:
            break
    return "\n".join(picked)


def build_context(
    root: Path,
    project: str = "",
    cwd: str = "",
    compact: bool = True,
) -> str:
    """L1 progressive disclosure: fast (<50ms) compact session bootstrap."""
    sync_index(root, with_embeddings=False)
    active_project = normalize_project_slug(project) if project.strip() else detect_project(root, cwd or None)
    sections: list[str] = []

    profile_path = root / "profile.md"
    if profile_path.exists():
        if compact:
            prof = _summarize_profile(profile_path, max_lines=10)
            if prof:
                sections.append(f"## Profile (summary — `brain_read('profile')` for full)\n{prof}")
        else:
            sections.append(profile_path.read_text(encoding="utf-8").strip())

    projects = list_projects(root)
    if active_project and Path(active_project).name == active_project and active_project not in (".", ".."):
        proj_path = root / "projects" / f"{active_project}.md"
        if proj_path.exists():
            proj_text = proj_path.read_text(encoding="utf-8", errors="replace").strip()
            if compact and len(proj_text) > 900:
                proj_text = proj_text[:900].rstrip() + f"\n... (`brain_read('projects/{active_project}')` for full)"
            sections.append(f"## Active Project: {active_project}\n{proj_text}")
    elif projects:
        sections.append("## Projects\n" + ", ".join(projects))

    conn = _connect(root)
    try:
        if active_project:
            notes = conn.execute(
                """
                SELECT id, kind, title, project, updated_at FROM docs
                WHERE kind IN ('decision', 'lesson')
                ORDER BY (CASE WHEN lower(project)=lower(?) THEN 0 ELSE 1 END), updated_at DESC
                LIMIT 6
                """,
                (active_project,),
            ).fetchall()
        else:
            notes = conn.execute(
                """
                SELECT id, kind, title, project, updated_at FROM docs
                WHERE kind IN ('decision', 'lesson')
                ORDER BY updated_at DESC
                LIMIT 6
                """
            ).fetchall()
        if notes:
            lines = [f"- [{r['kind']}] {r['title']} (`{r['id']}`)" for r in notes]
            sections.append("## Key Facts & Lessons\n" + "\n".join(lines))

        episodes = conn.execute(
            """
            SELECT id, title, updated_at FROM docs
            WHERE bucket = 'episode'
            ORDER BY id DESC
            LIMIT 3
            """
        ).fetchall()
        if episodes:
            e_lines = [f"- {r['title']} (`{r['id']}`)" for r in episodes]
            sections.append("## Recent Episodes\n" + "\n".join(e_lines))
    finally:
        conn.close()

    sections.append(
        "_Use `brain_search(query)` for excerpts, `brain_read(id)` for full notes, and `brain_store(...)` to save a memory. "
        "Use `brain board list --for <session>` to find cross-harness assignments._"
    )
    return "\n\n".join(sections)
