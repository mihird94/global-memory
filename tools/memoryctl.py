#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
import math
import subprocess
from typing import Dict, List, Tuple
from urllib import request

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
import sys
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


try:
    from schemas import validate_fact, get_namespace_for_key, list_contracts, parse_payload
except ImportError:
    try:
        from tools.schemas import validate_fact, get_namespace_for_key, list_contracts, parse_payload
    except ImportError:
        def validate_fact(key: str, value: Any) -> tuple[bool, Any, str | None]:
            return True, value, None
        def get_namespace_for_key(key: str) -> str | None:
            return None
        def list_contracts() -> dict[str, dict]:
            return {}
        def parse_payload(val: Any) -> Any:
            return val

try:
    from harvest import harvest_session
except ImportError:
    try:
        from tools.harvest import harvest_session
    except ImportError:
        harvest_session = None

try:
    from backfill import run_backfill
except ImportError:
    try:
        from tools.backfill import run_backfill
    except ImportError:
        run_backfill = None

try:
    from backup_db import backup_database
except ImportError:
    try:
        from tools.backup_db import backup_database
    except ImportError:
        backup_database = None



def _default_mem_root() -> Path:
    memory_root = os.environ.get("MEMORY_ROOT")
    if memory_root:
        return Path(memory_root).expanduser()
    return Path.home() / "memories"


MEM_ROOT = _default_mem_root()
INDEX_ROOT = MEM_ROOT / "episodic" / "index"
DRIFT_ROOT = INDEX_ROOT / "drift"
DEFAULT_EMBED_MODEL = os.environ.get("MEMORY_EMBED_MODEL", "qwen3-embedding:0.6b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_EMBED_URL = os.environ.get("OLLAMA_EMBED_URL", f"{OLLAMA_URL}/api/embeddings")
EMBED_TIMEOUT_SEC = int(os.environ.get("MEMORY_EMBED_TIMEOUT_SEC", "180"))
EMBED_RETRIES = int(os.environ.get("MEMORY_EMBED_RETRIES", "3"))
DEFAULT_RERANK_MODEL = os.environ.get("MEMORY_RERANK_MODEL", "ms-marco-TinyBERT-L-2-v2")
_RERANKER_INSTANCE: Dict[str, object] = {}


def _get_flashrank_cache_dir() -> Path:
    custom_dir = os.environ.get("FLASHRANK_CACHE_DIR")
    if custom_dir:
        return Path(custom_dir).expanduser()
    return Path.home() / ".cache" / "flashrank"


def _get_reranker(model_name: str | None = None):
    """Lazy-load and cache the FlashRank cross-encoder ranker.
    Gracefully returns None if flashrank or dependencies are not installed."""
    name = model_name or DEFAULT_RERANK_MODEL
    if name in _RERANKER_INSTANCE:
        return _RERANKER_INSTANCE[name]
    try:
        from flashrank import Ranker
        cache_dir = _get_flashrank_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        ranker = Ranker(model_name=name, cache_dir=str(cache_dir))
        _RERANKER_INSTANCE[name] = ranker
        return ranker
    except (ImportError, Exception):
        return None


def _resolve(path_a: Path, path_b: Path) -> Path:
    return path_a if path_a.exists() else path_b


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text()


def _append(path: Path, text: str) -> None:
    _ensure_parent(path)
    with path.open("a") as f:
        f.write(text)


def _json_update(path: Path, key: str, value: str) -> None:
    _ensure_parent(path)
    data: Dict[str, str] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    data[key] = value
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _write_json(path: Path, payload: dict) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2))


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _chunk_text(text: str, max_chars: int = 800) -> List[str]:
    chunks: List[str] = []
    buf = ""
    for para in text.split("\n\n"):
        part = para.strip()
        if not part:
            continue
        if len(buf) + len(part) + 2 <= max_chars:
            buf = f"{buf}\n\n{part}".strip()
            continue
        if buf:
            chunks.append(buf)
        buf = part
    if buf:
        chunks.append(buf)
    return chunks


def _iter_episodic_texts() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    history_dir = MEM_ROOT / "episodic" / "history"
    if history_dir.exists():
        for path in sorted(history_dir.glob("*.md")):
            text = _read(path).strip()
            if text:
                out.append((str(path), text))
    journal = MEM_ROOT / "episodic" / "journal.md"
    if journal.exists():
        text = _read(journal).strip()
        if text:
            out.append((str(journal), text))
    return out


def _iter_structured_texts() -> List[Tuple[str, str]]:
    """Iterate over semantic, operational, procedural facts and claims to embed."""
    out: List[Tuple[str, str]] = []

    # 1. Facts from JSON stores
    for bucket in ("semantic", "operational", "procedural"):
        json_path = MEM_ROOT / bucket / "facts.json"
        if json_path.exists():
            try:
                facts = json.loads(json_path.read_text(encoding="utf-8"))
                for k, v in facts.items():
                    if isinstance(v, dict):
                        stmt = v.get("statement") or v.get("value") or json.dumps(v, sort_keys=True)
                        rationale = f" Rationale: {v['rationale']}" if v.get("rationale") else ""
                        text = f"[{bucket}] {k}: {stmt}{rationale}"
                    else:
                        text = f"[{bucket}] {k}: {v}"
                    out.append((f"{bucket}:{k}", text))
            except Exception:
                pass

    # 2. Reusable procedures from SQLite
    db_path = MEM_ROOT / "gms_trust.sqlite"
    if db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            has_proc = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_procedures'").fetchone()
            if has_proc:
                for row in c.execute("SELECT name, description, steps_json FROM gms_procedures WHERE status = 'active'").fetchall():
                    name = row["name"]
                    desc = row["description"] or ""
                    steps = row["steps_json"] or ""
                    text = f"[procedure] {name}: {desc}\nSteps: {steps}"
                    out.append((f"procedure:{name}", text))
            conn.close()
        except Exception:
            pass

    return out


def _build_drift_snapshot(mat, model: str, doc_count: int, chunk_count: int) -> dict:
    rows = mat.tolist() if hasattr(mat, "tolist") else [list(row) for row in mat]
    if not rows:
        centroid = []
        dimension = 0
    else:
        dimension = len(rows[0])
        centroid = [
            sum(row[i] for row in rows) / float(len(rows))
            for i in range(dimension)
        ]
    centroid_norm = math.sqrt(sum(value * value for value in centroid))
    return {
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "embedding_model": model,
        "doc_count": doc_count,
        "vector_count": chunk_count,
        "dimension": dimension if dimension else int(getattr(mat, "shape", [0, 0])[1] if getattr(mat, "shape", None) else 0),
        "centroid": [float(value) for value in centroid],
        "centroid_norm": float(centroid_norm),
    }


def _compute_drift_report(current: dict, previous: dict | None, threshold: float) -> dict:
    report = {
        "status": "baseline",
        "threshold": threshold,
        "current": current,
        "previous": None,
        "drift": None,
    }
    if previous is None:
        return report

    current_centroid = current.get("centroid") or []
    previous_centroid = previous.get("centroid") or []
    if len(current_centroid) != len(previous_centroid) or not current_centroid:
        report["status"] = "incompatible"
        report["previous"] = {
            "created_at": previous.get("created_at"),
            "embedding_model": previous.get("embedding_model"),
            "vector_count": previous.get("vector_count"),
            "dimension": previous.get("dimension"),
        }
        report["drift"] = {"reason": "dimension_mismatch_or_empty_centroid"}
        return report

    current_norm = math.sqrt(sum(value * value for value in current_centroid))
    previous_norm = math.sqrt(sum(value * value for value in previous_centroid))
    if current_norm == 0.0 or previous_norm == 0.0:
        cosine_similarity = 1.0
    else:
        dot = sum(cur * prev for cur, prev in zip(current_centroid, previous_centroid))
        cosine_similarity = float(dot / (current_norm * previous_norm))
        cosine_similarity = max(-1.0, min(1.0, cosine_similarity))
    angular_distance = float(math.acos(cosine_similarity))
    l2_distance = math.sqrt(
        sum((cur - prev) * (cur - prev) for cur, prev in zip(current_centroid, previous_centroid))
    )

    report["previous"] = {
        "created_at": previous.get("created_at"),
        "embedding_model": previous.get("embedding_model"),
        "vector_count": previous.get("vector_count"),
        "dimension": previous.get("dimension"),
    }
    report["drift"] = {
        "cosine_similarity": cosine_similarity,
        "angular_distance": angular_distance,
        "l2_distance": l2_distance,
    }
    report["status"] = "alert" if angular_distance > threshold else "ok"
    return report


def _persist_drift_snapshot(snapshot: dict, threshold: float) -> dict:
    latest_path = DRIFT_ROOT / "latest.json"
    previous_path = DRIFT_ROOT / "latest.previous.json"
    previous = _load_json(latest_path)
    report = _compute_drift_report(snapshot, previous, threshold)

    DRIFT_ROOT.mkdir(parents=True, exist_ok=True)
    if previous is not None:
        _write_json(previous_path, previous)
    _write_json(DRIFT_ROOT / f"{snapshot['created_at'].replace(':', '-').replace('Z', '')}.json", snapshot)
    _write_json(latest_path, snapshot)
    _write_json(DRIFT_ROOT / "status.json", report)
    return report


def _read_drift_status(threshold: float) -> dict:
    latest = _load_json(DRIFT_ROOT / "latest.json")
    if latest is None:
        return {
            "status": "missing",
            "threshold": threshold,
            "message": "No drift snapshot found. Run index-build first.",
        }
    previous = _load_json(DRIFT_ROOT / "latest.previous.json")
    return _compute_drift_report(latest, previous, threshold)


def _embed(text: str, model: str, *, keep_alive: int | str = "30m") -> List[float]:
    last_err: Exception | None = None
    for attempt in range(1, EMBED_RETRIES + 1):
        try:
            payload = json.dumps({"model": model, "prompt": text, "keep_alive": keep_alive}).encode("utf-8")
            req = request.Request(
                OLLAMA_EMBED_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=EMBED_TIMEOUT_SEC) as resp:  # nosec B310
                body = json.loads(resp.read().decode("utf-8"))
            emb = body.get("embedding")
            if not isinstance(emb, list) or not emb:
                raise RuntimeError(f"embedding payload invalid for model={model}")
            return emb
        except Exception as err:
            last_err = err
            if attempt < EMBED_RETRIES:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"embedding call failed after retries (model={model}): {last_err}")


def cmd_start_context(_: argparse.Namespace) -> int:
    idx = MEM_ROOT / "index.md"
    prefs = _resolve(MEM_ROOT / "preferences.md", MEM_ROOT / "global_context.md")
    projects = _resolve(MEM_ROOT / "projects.md", MEM_ROOT / "semantic" / "projects.md")
    lessons = _resolve(MEM_ROOT / "lessons" / "global.md", MEM_ROOT / "semantic" / "lessons_global.md")
    history_dir = MEM_ROOT / "episodic" / "history"
    history_daily = datetime.now().strftime("%Y-%m-%d")
    daily = history_dir / f"{history_daily}.md"
    if daily.exists() and daily.stat().st_size > 200:
        episodic = daily
    elif history_dir.exists():
        valid_files = [p for p in sorted(history_dir.glob("*.md")) if p.stat().st_size > 200]
        if valid_files:
            episodic = valid_files[-1]
        else:
            episodic = MEM_ROOT / "episodic" / "journal.md"
    else:
        episodic = MEM_ROOT / "episodic" / "journal.md"

    print(f"[index]\n{idx}\n")
    print(_read(idx)[:2000])
    print(f"\n[preferences]\n{prefs}\n")
    print(_read(prefs)[:2000])
    print(f"\n[projects]\n{projects}\n")
    print(_read(projects)[:2000])
    print(f"\n[lessons]\n{lessons}\n")
    print(_read(lessons)[:8000])
    print(f"\n[episodic]\n{episodic}\n")
    print(_read(episodic)[-2500:])
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    target = MEM_ROOT / "semantic"
    rg_path = shutil.which("rg")
    if rg_path:
        import subprocess

        cmd = [rg_path, "-n", args.pattern, str(target)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.stdout:
            print(proc.stdout.strip())
        if proc.stderr:
            print(proc.stderr.strip())
        return proc.returncode

    pattern = re.compile(re.escape(args.pattern), re.IGNORECASE)
    matches = 0
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                print(f"{path}:{line_no}:{line}")
                matches += 1
    return 0 if matches > 0 else 1


def cmd_log(args: argparse.Namespace) -> int:
    now = datetime.now()
    daily = MEM_ROOT / "episodic" / "history" / f"{now.strftime('%Y-%m-%d')}.md"

    # Auto-detect active git branch
    branch_suffix = ""
    try:
        res = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            branch = res.stdout.strip()
            if branch and branch not in ("main", "master", "HEAD"):
                branch_suffix = f" [branch: {branch}]"
    except Exception:
        pass

    line = f"### {now.strftime('%Y-%m-%d')} [{now.strftime('%H:%M')}] - {args.agent}{branch_suffix} - {args.title}\n"
    body = f"- {args.note}\n"
    _append(daily, "\n" + line + body)
    print(f"appended: {daily}")
    return 0


def cmd_lesson_add(args: argparse.Namespace) -> int:
    out = MEM_ROOT / "lessons" / "global.md"
    now = datetime.now().strftime("%Y-%m-%d")
    _append(out, f"\n- [{now}] {args.text}\n")
    print(f"updated: {out}")
    return 0


def cmd_fact_set(args: argparse.Namespace) -> int:
    is_valid, norm_val, err_msg = validate_fact(args.key, args.value)
    if not is_valid:
        print(f"ERROR: Schema validation failed for '{args.key}':\n  {err_msg}")
        return 1

    val_to_save = json.dumps(norm_val, sort_keys=True) if isinstance(norm_val, (dict, list)) else str(args.value)
    payload = {
        "key": args.key,
        "value": val_to_save,
        "agent": getattr(args, "agent", "human-cli"),
        "force": getattr(args, "force", False),
    }
    if getattr(args, "kind", None):
        payload["kind"] = args.kind
    return _call_memory_tool("mem_save_typed", payload)


def cmd_fact_validate(_: argparse.Namespace) -> int:
    contracts = list_contracts()
    print(f"Available Schema Contracts: {', '.join(contracts.keys())}\n")
    violations = 0
    total = 0
    for bucket in ("semantic", "operational", "procedural"):
        json_path = MEM_ROOT / bucket / "facts.json"
        if not json_path.exists():
            continue
        try:
            facts = json.loads(json_path.read_text())
        except Exception:
            continue
        for k, v in facts.items():
            total += 1
            is_valid, norm_val, err_msg = validate_fact(k, v)
            ns = get_namespace_for_key(k)
            if ns:
                if not is_valid:
                    violations += 1
                    print(f"[{bucket.upper()}] [INVALID] Key: '{k}' -> {err_msg}")
                else:
                    print(f"[{bucket.upper()}] [VALID]   Key: '{k}' (Contract: {ns})")
            else:
                print(f"[{bucket.upper()}] [UNTYPED] Key: '{k}'")
    print(f"\nAudit complete: {total} total facts checked, {violations} schema violations found.")
    return 0 if violations == 0 else 1


def cmd_index_build(args: argparse.Namespace) -> int:
    docs = _iter_episodic_texts()
    structured_docs = _iter_structured_texts()
    docs = docs + structured_docs
    if not docs:
        print("no episodic or structured docs found")
        return 1

    meta = []
    texts = []
    for src, raw in docs:
        chunks = _chunk_text(raw)
        for i, chunk in enumerate(chunks):
            meta.append({"source": src, "chunk": i, "text": chunk})
            texts.append(chunk)

    # Keep the embedding model resident only for this bounded batch. Unloading
    # after every chunk turns a rebuild into hundreds of cold model loads.
    try:
        vectors = [_embed(t, args.model, keep_alive="5m") for t in texts]
    finally:
        try:
            from eval_model_harvesting import unload_ollama_model
            unload_ollama_model(args.model)
        except Exception:
            pass

    # 1. Consolidated SQLite Storage: store directly in gms_trust.sqlite
    try:
        import memory_mcp_server
        memory_mcp_server.init_db()
        items_to_store = []
        for m, vec in zip(meta, vectors):
            items_to_store.append({
                "source": m["source"],
                "chunk": m["chunk"],
                "text": m["text"],
                "embedding": vec,
            })
        stored_count = memory_mcp_server.store_sqlite_embeddings(items_to_store, model=args.model)
        print(f"sqlite-vec: stored {stored_count} embedding vectors in gms_trust.sqlite")
    except Exception as e:
        print(f"sqlite-vec warning: could not store in SQLite: {e}")

    # 2. Export external FAISS index if faiss is installed (backward compatibility)
    try:
        import numpy as np
        import faiss
        mat = np.array(vectors, dtype=np.float32)
        faiss.normalize_L2(mat)
        index = faiss.IndexFlatIP(mat.shape[1])
        index.add(mat)

        INDEX_ROOT.mkdir(parents=True, exist_ok=True)
        idx_path = INDEX_ROOT / "episodic.faiss"
        meta_path = INDEX_ROOT / "episodic_meta.json"
        faiss.write_index(index, str(idx_path))
        meta_path.write_text(json.dumps(meta, indent=2))
        drift_report = _persist_drift_snapshot(
            _build_drift_snapshot(mat, args.model, len(docs), len(texts)),
            args.drift_threshold,
        )
        print(f"built: {idx_path}")
        print(f"meta:  {meta_path}")
        print(f"docs={len(docs)} chunks={len(texts)} dim={mat.shape[1]} model={args.model}")
        print(f"drift_status={drift_report['status']} threshold={args.drift_threshold}")
    except ImportError:
        dim = len(vectors[0]) if vectors else 0
        print(f"docs={len(docs)} chunks={len(texts)} dim={dim} model={args.model}")
        print("Note: faiss not installed; vectors are fully searchable via SQLite-resident storage.")

    return 0


NAMESPACE_DECAY_HALFLIVES = {
    "policy": 0,        # 0 = infinite (no decay)
    "contract": 0,      # infinite
    "procedural": 0,    # infinite (reusable skills & runbooks must never decay)
    "infra": 365,       # 365 days
    "system": 365,      # 365 days
    "journal": 90,      # 90 days
    "episodic": 90,     # 90 days
    "task": 14,         # 14 days
    "trading": 3,       # 3 days
}


def get_decay_rate_for_item(source: str, text: str, default_rate: float) -> float:
    source_lower = source.lower()
    text_prefix = text[:200].lower()
    combined = f"{source_lower} {text_prefix}"

    # Invariants (policies, contracts, procedures) must never be decayed even if mentioning other words
    for zero_ns in ("policy", "contract", "procedural"):
        if zero_ns in combined:
            return 0.0

    for ns, half_life in NAMESPACE_DECAY_HALFLIVES.items():
        if ns in combined:
            if half_life == 0:
                return 0.0
            return math.log(2) / half_life
    return default_rate


def cmd_index_query(args: argparse.Namespace) -> int:
    import numpy as np

    db_path = MEM_ROOT / "gms_trust.sqlite"
    meta: list[dict] = []
    vector_rank_map: dict[int, int] = {}
    vector_score_map: dict[int, float] = {}
    use_sqlite = False

    # 1. Primary: Unified SQLite Vector Storage (gms_embeddings)
    if db_path.exists():
        try:
            import sqlite3
            import memory_mcp_server
            conn = sqlite3.connect(str(db_path))
            c = conn.cursor()
            c.execute("SELECT id, source, chunk, text FROM gms_embeddings ORDER BY id ASC")
            db_rows = c.fetchall()
            conn.close()
            if db_rows:
                use_sqlite = True
                meta = [{"id": r[0], "source": r[1], "chunk": r[2], "text": r[3]} for r in db_rows]
                qvec = _embed(args.query, args.model)
                search_k = min(len(meta), 100)
                hits = memory_mcp_server.search_sqlite_embeddings(
                    qvec, top_k=search_k, model=args.model, db_path=db_path
                )
                hit_text_map = {h["text"]: (rank, h["score"]) for rank, h in enumerate(hits, 1)}
                for doc_id, item in enumerate(meta):
                    if item["text"] in hit_text_map:
                        rank, score = hit_text_map[item["text"]]
                        vector_rank_map[doc_id] = rank
                        vector_score_map[doc_id] = float(score)
        except Exception:
            use_sqlite = False

    # 2. Fallback: External FAISS index (legacy compatibility)
    if not use_sqlite:
        idx_path = INDEX_ROOT / "episodic.faiss"
        meta_path = INDEX_ROOT / "episodic_meta.json"
        if not idx_path.exists() or not meta_path.exists():
            print("index missing: run memoryctl index-build or memoryctl backfill first")
            return 1
        try:
            import faiss
            meta = json.loads(meta_path.read_text())
            index = faiss.read_index(str(idx_path))
            qvec = np.array([_embed(args.query, args.model)], dtype=np.float32)
            faiss.normalize_L2(qvec)
            search_k = min(len(meta), 100)
            scores, ids = index.search(qvec, search_k)
            for rank, doc_id in enumerate(ids[0], 1):
                if doc_id >= 0:
                    vector_rank_map[int(doc_id)] = rank
                    vector_score_map[int(doc_id)] = float(scores[0][rank-1])
        except ImportError:
            print("ERROR: SQLite embeddings missing and faiss library is not installed.")
            return 1

    # Active branch detection
    active_branch = None
    if not args.no_boost:
        try:
            res = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                branch = res.stdout.strip()
                if branch and branch not in ("main", "master", "HEAD"):
                    active_branch = branch
        except Exception:
            pass

    today = datetime.now()

    # Check for rank_bm25 support
    has_bm25 = False
    bm25_scores = None
    if not args.no_hybrid:
        try:
            from rank_bm25 import BM25Okapi
            tokenized_corpus = [re.findall(r'\w+', row["text"].lower()) for row in meta]
            bm25 = BM25Okapi(tokenized_corpus)
            tokenized_query = re.findall(r'\w+', args.query.lower())
            bm25_scores = bm25.get_scores(tokenized_query)
            has_bm25 = True
        except (ImportError, Exception):
            pass

    reranked = []

    if has_bm25 and bm25_scores is not None:
        # Hybrid Search via Reciprocal Rank Fusion (RRF)
        bm25_ranked_indices = np.argsort(bm25_scores)[::-1]
        bm25_rank_map = {}
        for rank, idx in enumerate(bm25_ranked_indices, 1):
            if bm25_scores[idx] > 0:
                bm25_rank_map[int(idx)] = rank

        # Union of candidates in both pools
        candidates = set(vector_rank_map.keys()).union(set(bm25_rank_map.keys()))
        for doc_id in candidates:
            row = meta[doc_id]
            rank_vec = vector_rank_map.get(doc_id, 1000)
            rank_bm25 = bm25_rank_map.get(doc_id, 1000)

            # Reciprocal Rank Fusion (RRF) formula
            rrf_score = (1.0 / (60 + rank_vec)) + (1.0 / (60 + rank_bm25))

            # Apply temporal decay
            decay_factor = 1.0
            days_ago = 0
            if not args.no_decay:
                doc_date = today
                match = re.search(r"(\d{4}-\d{2}-\d{2})", row["source"])
                if match:
                    try:
                        doc_date = datetime.strptime(match.group(1), "%Y-%m-%d")
                    except ValueError:
                        pass
                else:
                    p = Path(row["source"])
                    if p.exists():
                        doc_date = datetime.fromtimestamp(p.stat().st_mtime)

                days_ago = max(0, (today - doc_date).days)
                rate = get_decay_rate_for_item(row.get("source", ""), row.get("text", ""), args.decay_rate)
                decay_factor = math.exp(-rate * days_ago)

            # Apply branch boost
            boost_factor = 1.0
            branch_matched = False
            if active_branch:
                clean_branch = active_branch.split("/")[-1].lower()
                if clean_branch in row["text"].lower() or active_branch.lower() in row["text"].lower():
                    boost_factor = args.branch_boost
                    branch_matched = True

            final_score = rrf_score * decay_factor * boost_factor
            reranked.append({
                "doc_id": doc_id,
                "row": row,
                "rrf_score": rrf_score,
                "ce_score": None,
                "rank_vec": rank_vec,
                "rank_bm25": rank_bm25,
                "raw_score": vector_score_map.get(doc_id, 0.0),
                "decay_factor": decay_factor,
                "days_ago": days_ago,
                "boost_factor": boost_factor,
                "branch_matched": branch_matched,
                "final_score": final_score
            })
    else:
        # Vector-Only Search with Decay and Boost
        sorted_docs = sorted(vector_rank_map.keys(), key=lambda d: vector_rank_map[d])
        for rank, doc_id in enumerate(sorted_docs, 1):
            row = meta[doc_id]
            raw_score = vector_score_map.get(doc_id, 0.0)

            decay_factor = 1.0
            days_ago = 0
            if not args.no_decay:
                doc_date = today
                match = re.search(r"(\d{4}-\d{2}-\d{2})", row["source"])
                if match:
                    try:
                        doc_date = datetime.strptime(match.group(1), "%Y-%m-%d")
                    except ValueError:
                        pass
                else:
                    p = Path(row["source"])
                    if p.exists():
                        doc_date = datetime.fromtimestamp(p.stat().st_mtime)
                days_ago = max(0, (today - doc_date).days)
                rate = get_decay_rate_for_item(row.get("source", ""), row.get("text", ""), args.decay_rate)
                decay_factor = math.exp(-rate * days_ago)

            boost_factor = 1.0
            branch_matched = False
            if active_branch:
                clean_branch = active_branch.split("/")[-1].lower()
                if clean_branch in row["text"].lower() or active_branch.lower() in row["text"].lower():
                    boost_factor = args.branch_boost
                    branch_matched = True

            final_score = float(raw_score * decay_factor * boost_factor)
            reranked.append({
                "doc_id": doc_id,
                "row": row,
                "rrf_score": None,
                "ce_score": None,
                "rank_vec": rank,
                "rank_bm25": None,
                "raw_score": raw_score,
                "decay_factor": decay_factor,
                "days_ago": days_ago,
                "boost_factor": boost_factor,
                "branch_matched": branch_matched,
                "final_score": final_score
            })

    # Stage 2: Cross-Encoder Reranking (FlashRank ONNX)
    should_rerank = getattr(args, "rerank", True) and not getattr(args, "no_rerank", False)
    if should_rerank and reranked:
        rerank_model_name = getattr(args, "rerank_model", DEFAULT_RERANK_MODEL)
        ranker = _get_reranker(rerank_model_name)
        if ranker is not None:
            # Sort initial candidates by final_score descending to select top candidates for cross-encoder
            reranked.sort(key=lambda x: x["final_score"], reverse=True)
            rerank_pool_size = min(len(reranked), getattr(args, "rerank_k", 25))
            candidate_pool = reranked[:rerank_pool_size]
            remaining_pool = reranked[rerank_pool_size:]
            
            try:
                from flashrank import RerankRequest
                passages = [{"id": str(item["doc_id"]), "text": item["row"]["text"], "item": item} for item in candidate_pool]
                rerank_req = RerankRequest(query=args.query, passages=passages)
                rerank_results = ranker.rerank(rerank_req)
                
                reranked_candidates = []
                for res in rerank_results:
                    item = res["item"]
                    ce_score = float(res.get("score", 0.0))
                    item["ce_score"] = ce_score
                    # Blend cross-encoder score with temporal decay and branch boost
                    item["final_score"] = ce_score * item["decay_factor"] * item["boost_factor"]
                    reranked_candidates.append(item)
                
                reranked_candidates.sort(key=lambda x: x["final_score"], reverse=True)
                reranked = reranked_candidates + remaining_pool
            except Exception:
                pass

    # Sort descending by final score
    reranked.sort(key=lambda x: x["final_score"], reverse=True)
    
    # Print top k
    for rank, item in enumerate(reranked[:args.k], 1):
        row = item["row"]
        snippet = row["text"].replace("\n", " ")
        if len(snippet) > 180:
            snippet = snippet[:180] + "..."
            
        details = []
        if item.get("ce_score") is not None:
            details.append(f"ce={item['ce_score']:.4f}")
        if item["rrf_score"] is not None:
            details.append(f"rrf={item['rrf_score']:.4f}")
            v_rank = "n/a" if item["rank_vec"] == 1000 else str(item["rank_vec"])
            k_rank = "n/a" if item["rank_bm25"] == 1000 else str(item["rank_bm25"])
            details.append(f"ranks=[v:{v_rank}, k:{k_rank}]")
        elif item.get("raw_score") is not None:
            details.append(f"raw={item['raw_score']:.4f}")
            
        if not args.no_decay:
            details.append(f"decay={item['decay_factor']:.3f} ({item['days_ago']}d ago)")
        if active_branch:
            details.append(f"boost={item['boost_factor']:.2f}" + (" (branch match)" if item['branch_matched'] else ""))
            
        details_str = f" ({', '.join(details)})" if details else ""
        print(f"{rank}. score={item['final_score']:.4f}{details_str} src={row['source']} chunk={row['chunk']}")
        print(f"   {snippet}")
        
    return 0


def cmd_drift_status(args: argparse.Namespace) -> int:
    report = _read_drift_status(args.threshold)
    print(json.dumps(report, indent=2))
    return 0 if report.get("status") != "missing" else 1


def cmd_trust_list(args: argparse.Namespace) -> int:
    DB_PATH = MEM_ROOT / "gms_trust.sqlite"
    if not DB_PATH.exists():
        print("Trust database does not exist yet.")
        return 0
    import sqlite3
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id, alpha, beta, last_updated FROM gms_agent_reputation")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            print("No agent reputations recorded.")
            return 0
            
        print(f"{'Agent ID':<20} | {'Alpha (Success)':<15} | {'Beta (Penalties)':<15} | {'Trust Score':<12} | {'Last Updated'}")
        print("-" * 80)
        for agent_id, alpha, beta, last_updated in rows:
            trust = (alpha + 1.0) / (alpha + beta + 2.0)
            print(f"{agent_id:<20} | {alpha:<15.1f} | {beta:<15.1f} | {trust:<12.4f} | {last_updated}")
    except Exception as e:
        print(f"Error querying trust database: {e}")
        return 1
    return 0


def cmd_quarantine_list(args: argparse.Namespace) -> int:
    DB_PATH = MEM_ROOT / "gms_trust.sqlite"
    if not DB_PATH.exists():
        print("Trust database does not exist yet.")
        return 0
    import sqlite3
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT fact_key, value, agent_id, branch, timestamp FROM gms_quarantined_facts")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            print("No quarantined facts found.")
            return 0
            
        print(f"{'Fact Key':<25} | {'Agent':<15} | {'Branch':<15} | {'Timestamp':<20} | {'Value'}")
        print("-" * 100)
        for key, val, agent, branch, ts in rows:
            print(f"{key:<25} | {agent:<15} | {branch:<15} | {ts:<20} | {val}")
    except Exception as e:
        print(f"Error querying quarantine: {e}")
        return 1
    return 0


def cmd_quarantine_resolve(args: argparse.Namespace) -> int:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import memory_mcp_server
        res = memory_mcp_server.tool_mem_resolve_quarantine({
            "key": args.key,
            "agent_id": args.agent_id,
            "action": args.action,
            "agent": args.resolver
        })
        print(res)
        if res.startswith("ERROR"):
            return 1
    except Exception as e:
        print(f"Error resolving quarantine: {e}")
        return 1
    return 0


def cmd_quarantine_review_add(args: argparse.Namespace) -> int:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import memory_mcp_server
        res = memory_mcp_server.tool_mem_record_review({
            "key": args.key,
            "agent_id": args.agent_id,
            "reviewer_id": args.reviewer,
            "rating": args.rating,
            "rationale": args.rationale
        })
        print(res)
        if res.startswith("ERROR"):
            return 1
    except Exception as e:
        print(f"Error recording review: {e}")
        return 1
    return 0


def cmd_quarantine_review_list(args: argparse.Namespace) -> int:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import memory_mcp_server
        res = memory_mcp_server.tool_mem_get_reviews({
            "key": args.key,
            "agent_id": args.agent_id
        })
        if res.startswith("ERROR"):
            print(res)
            return 1
        reviews = json.loads(res)
        if not reviews:
            print("No reviews found for this item.")
            return 0
        print(f"{'Reviewer':<20} | {'Trust':<8} | {'Rating':<10} | {'Rationale'}")
        print("-" * 90)
        for r in reviews:
            print(f"{r['reviewer_id']:<20} | {r['trust']:<8.4f} | {r['rating']:<10} | {r['rationale']}")
    except Exception as e:
        print(f"Error listing reviews: {e}")
        return 1
    return 0


def cmd_quarantine_recommendation(args: argparse.Namespace) -> int:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import memory_mcp_server
        res = memory_mcp_server.tool_mem_get_recommendation_summary({
            "key": args.key,
            "agent_id": args.agent_id
        })
        if res.startswith("ERROR"):
            print(res)
            return 1
        summary = json.loads(res)
        print(f"Recommendation: {summary['recommendation'].upper()}")
        print(f"Confidence Score: {summary['score']}")
        print(f"Reviewer Count: {summary['reviewer_count']}")
        print(f"Endorse Weight: {summary['endorse_weight']}")
        print(f"Reject Weight: {summary['reject_weight']}")
        print(f"Abstain Weight: {summary['abstain_weight']}")
        if summary['reviews']:
            print("\nWitness Details:")
            print(f"{'Reviewer':<20} | {'Trust':<8} | {'Rating':<10}")
            print("-" * 45)
            for r in summary['reviews']:
                print(f"{r['reviewer_id']:<20} | {r['trust']:<8.4f} | {r['rating']:<10}")
    except Exception as e:
        print(f"Error getting recommendation: {e}")
        return 1
    return 0


def _call_memory_tool(name: str, payload: dict) -> int:
    """Invoke a local MCP implementation so CLI and MCP share task semantics."""
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import memory_mcp_server
        result = memory_mcp_server.TOOLS[name]["fn"](payload)
        print(result)
        return 1 if result.startswith("ERROR:") else 0
    except Exception as exc:
        print(f"Error invoking {name}: {exc}")
        return 1


def cmd_task_create(args: argparse.Namespace) -> int:
    return _call_memory_tool("mem_task_create", vars(args))


def cmd_task_claim(args: argparse.Namespace) -> int:
    return _call_memory_tool("mem_task_claim", vars(args))


def cmd_task_checkpoint(args: argparse.Namespace) -> int:
    try:
        state = json.loads(args.state)
        artifacts = json.loads(args.artifact_refs)
        claims = json.loads(args.claim_refs)
        episodes = json.loads(args.episode_refs)
    except json.JSONDecodeError as exc:
        print(f"ERROR: checkpoint JSON is invalid: {exc.msg}")
        return 1
    return _call_memory_tool("mem_task_checkpoint", {
        "task_id": args.task_id, "agent": args.agent, "expected_revision": args.expected_revision,
        "label": args.label, "state": state, "artifact_refs": artifacts,
        "claim_refs": claims, "episode_refs": episodes,
    })


def cmd_task_handoff(args: argparse.Namespace) -> int:
    try:
        context = json.loads(args.context)
        artifacts = json.loads(args.artifact_refs)
    except json.JSONDecodeError as exc:
        print(f"ERROR: handoff JSON is invalid: {exc.msg}")
        return 1
    return _call_memory_tool("mem_handoff_create", {
        "task_id": args.task_id, "source_agent": args.source_agent, "target_agent": args.target_agent,
        "expected_revision": args.expected_revision, "objective": args.objective,
        "completed_work": args.completed_work, "next_action": args.next_action, "blockers": args.blockers,
        "acceptance_criteria": args.acceptance_criteria, "context": context, "artifact_refs": artifacts,
    })


def cmd_task_resume(args: argparse.Namespace) -> int:
    arg_val = getattr(args, "action_or_task_id", None)
    action = None
    task_id = getattr(args, "task_id_flag", None)
    if arg_val in ("build", "verify"):
        action = arg_val
    elif arg_val:
        task_id = arg_val

    project_id = getattr(args, "project", None)
    target_format = getattr(args, "format", "antigravity")
    as_of = getattr(args, "as_of", None)

    if action in ("build", "verify") or project_id:
        from project_briefing import build_resume_bundle
        if not project_id and task_id:
            import sqlite3
            db_path = MEM_ROOT / "gms_trust.sqlite"
            if db_path.exists():
                try:
                    with sqlite3.connect(str(db_path)) as conn:
                        row = conn.execute("SELECT project FROM gms_tasks WHERE task_id = ?", (task_id,)).fetchone()
                        if row and row[0]:
                            project_id = row[0]
                except Exception:
                    pass
        if not project_id:
            project_id = "global-memory"
        bundle = build_resume_bundle(MEM_ROOT, project_id=project_id, as_of=as_of, target_format=target_format, task_id=task_id)
        if action == "verify":
            valid = bool(bundle.get("packet_hash") and bundle.get("schema_version") == "gms-task-resume-bundle-v1")
            print(json.dumps({"status": "verified" if valid else "invalid", "packet_hash": bundle.get("packet_hash"), "target_format": target_format}, indent=2))
            return 0 if valid else 1
        if target_format == "json":
            print(json.dumps(bundle, indent=2))
        else:
            print(bundle.get("prompt", ""))
        return 0

    if task_id:
        return _call_memory_tool("mem_task_resume", {"task_id": task_id})
    print(json.dumps({"error": "Specify task_id or --project"}, indent=2))
    return 1


def cmd_task_complete(args: argparse.Namespace) -> int:
    return _call_memory_tool("mem_task_complete", vars(args))


def cmd_project_state(args: argparse.Namespace) -> int:
    return _call_memory_tool("mem_project_state", vars(args))


def cmd_claims_list(args: argparse.Namespace) -> int:
    DB_PATH = MEM_ROOT / "gms_trust.sqlite"
    if not DB_PATH.exists():
        print("Trust database does not exist yet.")
        return 0
    import sqlite3
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        query = "SELECT claim_id, memory_kind, memory_key, value, agent_id, branch, status, supersedes_claim_id, confidence, contradiction_type, created_at FROM gms_claims WHERE 1=1"
        params = []
        if args.kind:
            query += " AND memory_kind = ?"
            params.append(args.kind)
        if args.key:
            query += " AND memory_key = ?"
            params.append(args.key)
        if args.status:
            query += " AND status = ?"
            params.append(args.status)
            
        query += " ORDER BY claim_id ASC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            print("No claims found.")
            return 0
            
        print(f"{'ID':<5} | {'Kind':<12} | {'Key':<20} | {'Status':<12} | {'Agent':<15} | {'Conf':<6} | {'Conflict Type':<25} | {'Value'}")
        print("-" * 125)
        for claim_id, kind, key, val, agent, branch, status, sup_id, confidence, contradiction_type, ts in rows:
            sup_str = str(sup_id) if sup_id is not None else "None"
            conf_str = f"{confidence:.2f}" if confidence is not None else "None"
            contra_str = contradiction_type if contradiction_type is not None else "None"
            print(f"{claim_id:<5} | {kind:<12} | {key:<20} | {status:<12} | {agent:<15} | {conf_str:<6} | {contra_str:<25} | {val}")
    except Exception as e:
        print(f"Error querying claims: {e}")
        return 1
    return 0


def cmd_calibration_report(args: argparse.Namespace) -> int:
    DB_PATH = MEM_ROOT / "gms_trust.sqlite"
    if not DB_PATH.exists():
        if args.json:
            print(json.dumps({"overlapping_keys_count": 0, "agents": {}}))
        else:
            print("Trust database does not exist yet.")
        return 0

    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import dream_cycle
        report = dream_cycle.generate_calibration_report(DB_PATH)
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e), "overlapping_keys_count": 0, "agents": {}}))
        else:
            print(f"Error generating calibration report: {e}")
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    if "error" in report:
        print(f"Error: {report['error']}")
        return 1

    print(f"Model: {report.get('model', 'unknown')}")
    print(f"Iterations: {report.get('iterations', 0)} | Converged: {report.get('converged', False)}")
    print(f"Overlapping Keys: {report['overlapping_keys_count']}")
    agents = report.get("agents", {})
    if not agents:
        print("No agents with calibration data.")
        return 0

    print(f"{'Agent':<30} | {'Overlap':<10} | {'Agreement':<10} | {'Disagreement':<12} | {'DS Acc':<8} | {'Agree Rate':<10}")
    print("-" * 100)
    for agent, stats in sorted(agents.items()):
        rate_str = f"{stats['agreement_rate']:.3f}"
        acc_str = f"{stats.get('inferred_accuracy', 0.0):.3f}"
        print(f"{agent:<30} | {stats['overlap_count']:<10} | {stats['agreement_count']:<10} | {stats['disagreement_count']:<12} | {acc_str:<8} | {rate_str:<10}")

    return 0


def cmd_retention_report(args: argparse.Namespace) -> int:
    DB_PATH = MEM_ROOT / "gms_trust.sqlite"
    if not DB_PATH.exists():
        payload = {
            "generated_at": None,
            "thresholds": {
                "low_confidence": args.low_confidence,
                "stale_active_days": args.stale_active_days,
                "stale_quarantine_days": args.stale_quarantine_days,
            },
            "stale_active_claims": [],
            "stale_quarantines": [],
            "summary": {"active_claim_candidates": 0, "quarantine_candidates": 0},
        }
        print(json.dumps(payload, indent=2) if args.json else "Trust database does not exist yet.")
        return 0

    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import dream_cycle
        report = dream_cycle.generate_retention_report(
            DB_PATH,
            low_confidence_threshold=args.low_confidence,
            stale_active_days=args.stale_active_days,
            stale_quarantine_days=args.stale_quarantine_days,
        )
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error generating retention report: {e}")
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    summary = report["summary"]
    print(
        f"Retention candidates: active={summary['active_claim_candidates']} "
        f"quarantine={summary['quarantine_candidates']}"
    )
    return 0


def cmd_retention_prune(args: argparse.Namespace) -> int:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import dream_cycle
        report = dream_cycle.run_retention_pruning(
            low_confidence_threshold=args.low_confidence,
            stale_active_days=args.stale_active_days,
            stale_quarantine_days=args.stale_quarantine_days,
        )
    except Exception as e:
        print(f"Error applying retention pruning: {e}")
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    applied = report.get("applied", {})
    print(
        f"Retention pruning applied: archived_active={applied.get('archived_active_claims', 0)} "
        f"discarded_quarantine={applied.get('discarded_quarantines', 0)}"
    )
    return 0


def cmd_tui(_: argparse.Namespace) -> int:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        import gms_tui
        return gms_tui.main()
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Error launching TUI: {e}")
        return 1




def _structured_graph_triples(key: str, raw_value: object) -> list[tuple[str,str,str]]:
    value=raw_value
    if isinstance(value,str) and value.lstrip().startswith("{"):
        try: value=json.loads(value)
        except Exception: return []
    if not isinstance(value,dict) or value.get("schema_version")!="gms-context-record-v1": return []
    triples=[]; scope=value.get("scope") or {}; freshness=value.get("freshness") or {}
    if value.get("record_type"): triples.append((key,"is_a",str(value["record_type"])))
    if scope.get("project"): triples.append((key,"scoped_to",str(scope["project"])))
    if scope.get("workstream"): triples.append((key,"part_of_workstream",str(scope["workstream"])))
    for target in scope.get("applies_to") or []: triples.append((key,"applies_to",str(target)))
    for implication in value.get("implications") or []: triples.append((key,"implies",str(implication)))
    for evidence in value.get("evidence") or []:
        if evidence.get("ref"): triples.append((key,"supported_by",str(evidence["ref"])))
    for prior in freshness.get("supersedes") or []: triples.append((key,"supersedes",str(prior)))
    return triples


def cmd_graph_build(_: argparse.Namespace | None = None) -> int:
    """Batch extract triples from active claims, facts, and episodic history into SQLite graph tables."""
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    import memory_mcp_server

    memory_mcp_server.init_db()
    count = 0

    DB_PATH = MEM_ROOT / "gms_trust.sqlite"
    if DB_PATH.exists():
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT claim_id, memory_kind, memory_key, value FROM gms_claims WHERE status = 'active'")
        rows = cursor.fetchall()
        conn.close()
        for cid, kind, key, val in rows:
            structured = _structured_graph_triples(key,val)
            if structured:
                memory_mcp_server.invalidate_graph_relationship(subject=key,predicate="configured_as")
            triples = structured or memory_mcp_server.extract_graph_triples(f"{key}: {val}")
            if not triples:
                triples = [(key, "configured_as", val)]
            for sub, pred, obj in triples:
                memory_mcp_server.record_graph_relationship(sub, pred, obj, source_claim_id=cid)
                count += 1

    facts_file = MEM_ROOT / "semantic" / "facts.json"
    if facts_file.exists():
        try:
            facts = json.loads(facts_file.read_text())
            for k, v in facts.items():
                structured = _structured_graph_triples(k,v)
                if structured:
                    memory_mcp_server.invalidate_graph_relationship(subject=k,predicate="configured_as")
                triples = structured or memory_mcp_server.extract_graph_triples(f"{k}: {v}")
                if not triples:
                    triples = [(k, "configured_as", str(v))]
                for sub, pred, obj in triples:
                    memory_mcp_server.record_graph_relationship(sub, pred, obj)
                    count += 1
        except Exception:
            pass

    print(f"Graph build complete: registered/updated {count} entity relationship triple(s).")
    return 0


def build_graph_relationships() -> int:
    """Helper alias for batch extracting graph triples during Dream Cycle."""
    return cmd_graph_build(None)



def cmd_graph_query(args: argparse.Namespace) -> int:
    payload = {"entity": args.entity, "hops": args.hops, "format": "json"}
    if getattr(args, "as_of", None):
        payload["valid_at"] = args.as_of
    if getattr(args, "include_expired", False):
        payload["include_expired"] = True
    return _call_memory_tool("mem_graph_query", payload)


def cmd_graph_show(args: argparse.Namespace) -> int:
    payload = {"entity": args.entity, "hops": args.hops, "format": "ascii"}
    if getattr(args, "as_of", None):
        payload["valid_at"] = args.as_of
    if getattr(args, "include_expired", False):
        payload["include_expired"] = True
    return _call_memory_tool("mem_graph_query", payload)


def cmd_graph_invalidate(args: argparse.Namespace) -> int:
    import memory_mcp_server
    memory_mcp_server.init_db()
    count = memory_mcp_server.invalidate_graph_relationship(
        subject=args.subject,
        predicate=args.predicate,
        obj=args.object,
        valid_to=getattr(args, "valid_to", None),
    )
    print(f"Invalidated {count} relationship edge(s) matching ({args.subject}, {args.predicate}, {args.object or '*'}).")
    return 0


def cmd_session_harvest(args: argparse.Namespace) -> int:
    if harvest_session is None:
        print("ERROR: harvest module not available")
        return 1
    report = harvest_session(
        agent=args.agent,
        summary=args.summary,
        text=args.text,
        incremental_index=not getattr(args, "no_index", False),
    )
    print(json.dumps(report, indent=2))
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    if run_backfill is None:
        print("ERROR: backfill module not available")
        return 1
    root = Path(args.root).resolve() if getattr(args, "root", None) else MEM_ROOT
    report = run_backfill(
        mem_root=root,
        dry_run=getattr(args, "dry_run", False),
        skip_embeddings=getattr(args, "skip_embeddings", False),
        skip_graph=getattr(args, "skip_graph", False),
    )
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        prefix = "[DRY-RUN] " if report.get("dry_run") else ""
        print(f"{prefix}GMS v2.1.0 Backfill Report:")
        print(f"  Target DB: {report['db_path']}")
        print(f"  Claims backfilled: {report['claims_backfilled']}")
        print(f"  Provenance backfilled: {report['provenance_backfilled']}")
        print(f"  Procedures backfilled: {report['procedures_backfilled']}")
        print(f"  Embeddings backfilled: {report['embeddings_backfilled']} (method: {report['embeddings_method']})")
        print(f"  Graph relationships backfilled: {report['relationships_backfilled']}")
        audit = report.get("schema_audit", {})
        print(f"  Schema Audit: {audit.get('valid_count', 0)}/{audit.get('total_facts', 0)} valid, {audit.get('violation_count', 0)} violations")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    if backup_database is None:
        print("ERROR: backup_db module not available")
        return 1
    root = Path(args.root).resolve() if getattr(args, "root", None) else MEM_ROOT
    dest = Path(args.dest).resolve() if getattr(args, "dest", None) else None
    report = backup_database(mem_root=root, dest_path=dest)
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        status = report["status"].upper()
        if report["status"] == "success":
            print(f"[{report['timestamp']}] GMS DB Backup: {status} -> {report['destination']} ({report['size_bytes']} bytes, {report['table_count']} tables, integrity: {report['integrity']})")
    return 0 if report.get("status") == "success" else 1


def cmd_ui(args: argparse.Namespace) -> int:
    desktop_dir = REPO_ROOT / "desktop"
    if not desktop_dir.exists():
        print("ERROR: desktop/ directory not found in repository.")
        return 1

    node_modules = desktop_dir / "node_modules"
    if not node_modules.exists():
        print("Notice: Mbrain Desktop UI dependencies are not installed.")
        print("To install and run the Mac Electron UI:")
        print("  cd desktop && npm install && npm start")
        return 1

    if sys.platform != "darwin" and not os.environ.get("DISPLAY"):
        print("Notice: Mbrain Desktop UI is an optional graphical interface.")
        print("Running in headless Linux environment. UI is disabled.")
        return 0

    print("Launching Mbrain Desktop Control Center (Electron)...")
    mbrain_app = Path.home() / "Applications" / "Mbrain.app"
    if sys.platform == "darwin" and mbrain_app.exists():
        try:
            subprocess.run(["open", str(mbrain_app)])
            return 0
        except Exception as e:
            print(f"Failed to open Mbrain.app, falling back to npm start: {e}")

    try:
        subprocess.run(["npm", "start"], cwd=str(desktop_dir))
        return 0
    except Exception as e:
        print(f"Failed to launch desktop UI: {e}")
        return 1


def cmd_sync_stores(args: argparse.Namespace) -> int:
    try:
        from dream_cycle import sync_json_and_sqlite_claims
        root = Path(args.root).resolve() if getattr(args, "root", None) else MEM_ROOT
        res = sync_json_and_sqlite_claims(root)
        if getattr(args, "json", False):
            print(json.dumps(res, indent=2))
        else:
            print(f"Store Sync: {res.get('status')}")
            print(f"  Facts updated in JSON: {res.get('updated_in_json', 0)}")
            print(f"  Claims added to SQLite: {res.get('added_to_claims', 0)}")
            print(f"  Divergences resolved: {res.get('divergences_resolved', 0)}")
            for d in res.get("divergences", []):
                print(f"    - {d.get('key')}: {d.get('action')}")
        return 0
    except Exception as e:
        print(f"ERROR syncing stores: {e}")
        return 1


def cmd_latest(args: argparse.Namespace) -> int:
    return _call_memory_tool("mem_latest", {"limit": args.limit, "kind": args.kind})


def cmd_project_init(args: argparse.Namespace) -> int:
    return _call_memory_tool("mem_project", {"action": "init", "project": args.project})


def cmd_project_get(args: argparse.Namespace) -> int:
    return _call_memory_tool("mem_project", {"action": "get", "project": args.project, "section": args.section})


def cmd_project_update(args: argparse.Namespace) -> int:
    return _call_memory_tool("mem_project", {"action": "update", "project": args.project, "section": args.section, "content": args.content, "append": not args.overwrite})


def cmd_synthesize(args: argparse.Namespace) -> int:
    project = getattr(args, "project", "")
    topic = getattr(args, "topic", "")
    model = getattr(args, "model", "qwen3.5:9b")
    
    context_chunks = []
    if project:
        mb_file = MEM_ROOT / "projects" / project / "activeContext.md"
        if mb_file.exists():
            context_chunks.append(f"### Project Memory Bank ({project})\n{mb_file.read_text()}")
    
    latest_text = _call_memory_tool("mem_latest", {"limit": 10})
    context_chunks.append(f"### Recent Milestones & Claims\n{latest_text}")
    
    if topic:
        search_res = _call_memory_tool("mem_search", {"query": topic, "mode": "hybrid"})
        context_chunks.append(f"### Relevant Knowledge Graph & Vector Context ({topic})\n{search_res}")
        
    full_prompt = (
        "You are Brain, an executive AI operating system assistant.\n"
        "Synthesize the following project and memory context into a concise, high-density 1-page Executive Snapshot.\n"
        "Highlight:\n"
        "1. Active Status & Core Focus\n"
        "2. Key Working Features & Recent Progress\n"
        "3. High-Priority Open Items / Blockers\n\n"
        + "\n\n".join(context_chunks)
    )
    
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps({"model": model, "prompt": full_prompt, "stream": True, "keep_alive": "2m"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        print(f"# Executive Synthesis Report ({project or topic or 'System'})\n")
        with urllib.request.urlopen(req, timeout=60) as resp:
            for raw_line in resp:
                if raw_line and raw_line.strip():
                    try:
                        obj = json.loads(raw_line.decode("utf-8"))
                        print(obj.get("response", ""), end="", flush=True)
                    except Exception:
                        pass
            print("\n")
            return 0
    except Exception as err:
        print(f"# Executive Context Compilation ({project or topic or 'System'})\n[Ollama Offline/Fallback: {err}]\n")
        print("\n\n".join(context_chunks))
        return 0


def cmd_audit(_: argparse.Namespace) -> int:
    facts_file = MEM_ROOT / "semantic" / "facts.json"
    facts = {}
    if facts_file.exists():
        try:
            facts = json.loads(facts_file.read_text())
        except Exception:
            pass
            
    claims = []
    db_path = MEM_ROOT / "gms_trust.sqlite"
    if db_path.exists():
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT claim_id, agent_id, memory_kind, memory_key, value, status FROM gms_claims")
        rows = cursor.fetchall()
        conn.close()
        for r in rows:
            claims.append({
                "claim_id": r[0], "agent_id": r[1], "kind": r[2], "key": r[3], "value": r[4], "status": r[5]
            })
            
    report_lines = ["# Brain Semantic Contradiction Audit Report", ""]
    report_lines.append(f"Total Active Semantic Facts: {len(facts)}")
    report_lines.append(f"Total Recorded Claims: {len(claims)}")
    report_lines.append("")
    
    conflicts_found = 0
    active_claims_by_key = {}
    for c in claims:
        if c.get("status") == "active":
            k = c.get("key")
            v = c.get("value")
            if k in active_claims_by_key and active_claims_by_key[k] != v:
                report_lines.append(f"[HIGH RISK CONFLICT] Key: '{k}' has multiple active values:")
                report_lines.append(f"  - Value 1: {active_claims_by_key[k]}")
                report_lines.append(f"  - Value 2: {v}")
                conflicts_found += 1
            else:
                active_claims_by_key[k] = v
                
    if conflicts_found == 0:
        report_lines.append("[SUCCESS] Zero active claim key conflicts detected.")
        
    print("\n".join(report_lines))
    return 0


def cmd_project_list(_: argparse.Namespace) -> int:
    return _call_memory_tool("mem_project", {"action": "list"})


def cmd_link_memory(args: argparse.Namespace) -> int:
    import memory_mcp_server
    res = memory_mcp_server.tool_mem_link_memory({
        "memory_ref": args.ref,
        "entity": args.entity,
        "relationship": args.rel
    })
    print(res)
    return 0


def cmd_entity_memories(args: argparse.Namespace) -> int:
    import memory_mcp_server
    res = memory_mcp_server.tool_mem_get_entity_memories({
        "entity": args.entity
    })
    print(res)
    return 0


DEFAULT_APPLESCRIPT_TIMEOUT = 10


def _run_osascript(script: str, timeout: int = DEFAULT_APPLESCRIPT_TIMEOUT) -> tuple[int, str, str]:
    """Execute osascript safely with timeout and structured error handling."""
    try:
        res = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return res.returncode, res.stdout, res.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"AppleScript execution timed out after {timeout} seconds."
    except Exception as e:
        return 1, "", f"AppleScript execution error: {e}"


def cmd_apple(args: argparse.Namespace) -> int:
    """Safe Apple automation commands (reminders, notes, calendar) via native osascript."""
    if sys.platform != "darwin":
        print("[ERROR] Apple automation is only supported on macOS.")
        return 1

    app_type = getattr(args, "app_type", None)
    action = getattr(args, "action", "list")

    if app_type == "reminder":
        if action == "list":
            script = '''
            tell application "Reminders"
                set remList to {}
                repeat with r in (every reminder of default list whose completed is false)
                    set end of remList to (name of r)
                end repeat
                set AppleScript's text item delimiters to linefeed
                return remList as text
            end tell
            '''
            rc, stdout, stderr = _run_osascript(script)
            if rc == 0:
                items = [x.strip() for x in stdout.strip().splitlines() if x.strip()]
                print(f"[Apple Reminders] ({len(items)} active)")
                for item in items:
                    print(f"  • {item}")
                return 0
            else:
                print(f"[ERROR] {stderr.strip()}")
                return 1
        elif action == "add":
            title = getattr(args, "title", "").replace('"', '\\"')
            notes = (getattr(args, "notes", "") or "").replace('"', '\\"')
            due = getattr(args, "due", "") or ""
            if due:
                notes = f"{notes} (Due: {due})".strip() if notes else f"Due: {due}"
            props = f'name:"{title}", body:"{notes}"'
            script = f'tell application "Reminders" to make new reminder with properties {{{props}}}'
            rc, stdout, stderr = _run_osascript(script)
            if rc == 0:
                print(f"[SUCCESS] Created reminder: {getattr(args, 'title', '')}")
                return 0
            else:
                print(f"[ERROR] {stderr.strip()}")
                return 1

    elif app_type == "note":
        if action == "list":
            script = '''
            tell application "Notes"
                set noteList to {}
                repeat with n in (every note)
                    set end of noteList to (name of n)
                end repeat
                set AppleScript's text item delimiters to linefeed
                return noteList as text
            end tell
            '''
            rc, stdout, stderr = _run_osascript(script)
            if rc == 0:
                items = [x.strip() for x in stdout.strip().splitlines() if x.strip()][:25]
                print(f"[Apple Notes] ({len(items)} notes)")
                for item in items:
                    print(f"  • {item}")
                return 0
            else:
                print(f"[ERROR] {stderr.strip()}")
                return 1
        elif action == "add":
            title = getattr(args, "title", "").replace('"', '\\"')
            body = (getattr(args, "notes", "") or "").replace('"', '\\"')
            script = f'tell application "Notes" to make new note with properties {{name:"{title}", body:"{body}"}}'
            rc, stdout, stderr = _run_osascript(script)
            if rc == 0:
                print(f"[SUCCESS] Created note: {getattr(args, 'title', '')}")
                return 0
            else:
                print(f"[ERROR] {stderr.strip()}")
                return 1

    elif app_type == "calendar":
        script = '''
        tell application "Calendar"
            set eventList to {}
            repeat with c in calendars
                repeat with e in (every event of c where its start date is greater than (current date) and its start date is less than ((current date) + 7 * days))
                    set end of eventList to (summary of e)
                end repeat
            end repeat
            set AppleScript's text item delimiters to linefeed
            return eventList as text
        end tell
        '''
        rc, stdout, stderr = _run_osascript(script)
        if rc == 0:
            items = [x.strip() for x in stdout.strip().splitlines() if x.strip()]
            print(f"[Apple Calendar] ({len(items)} upcoming events next 7 days)")
            for item in items:
                print(f"  • {item}")
            return 0
        else:
            print(f"[ERROR] {stderr.strip()}")
            return 1

    print("[USAGE] memoryctl apple [reminder|note|calendar] [list|add] ...")
    return 1


def cmd_harvest_status(_: argparse.Namespace) -> int:
    import gms_desktop_api
    api = gms_desktop_api.GMSDesktopAPI(mem_root=MEM_ROOT)
    status = api.get_harvest_status()
    print(json.dumps(status, indent=2))
    return 0


def cmd_harvest_candidates(args: argparse.Namespace) -> int:
    import gms_desktop_api
    api = gms_desktop_api.GMSDesktopAPI(mem_root=MEM_ROOT)
    status_filter = None if args.status == "all" else args.status
    res = api.get_harvest_candidates(
        project=args.project,
        record_type=args.type,
        status=status_filter,
        limit=args.limit,
        offset=args.offset,
    )
    print(json.dumps(res, indent=2))
    return 0


def cmd_harvest_show(args: argparse.Namespace) -> int:
    import gms_desktop_api
    api = gms_desktop_api.GMSDesktopAPI(mem_root=MEM_ROOT)
    res = api.get_harvest_candidate(args.candidate_id)
    print(json.dumps(res, indent=2))
    return 0 if res.get("status") == "success" else 1


def cmd_harvest_review(args: argparse.Namespace) -> int:
    import gms_desktop_api
    api = gms_desktop_api.GMSDesktopAPI(mem_root=MEM_ROOT)
    edited = json.loads(args.edited_payload) if args.edited_payload else None
    data = {
        "action": args.action,
        "reviewer": args.reviewer,
        "rationale": args.rationale,
        "edited_payload": edited,
        "merge_with_claim_id": args.merge_with,
        "expected_content_hash": getattr(args, "expected_hash", None),
    }
    res = api.review_harvest_candidate(args.candidate_id, data)
    print(json.dumps(res, indent=2))
    return 0 if res.get("status") == "success" else 1


def cmd_harvest_migrate_flat(args: argparse.Namespace) -> int:
    import migrate_flat_records
    apply = getattr(args, "apply", False)
    res = migrate_flat_records.run_migration(apply=apply, mem_root=MEM_ROOT)
    print(json.dumps(res, indent=2))
    return 0


def cmd_harvest_run(args: argparse.Namespace) -> int:
    import dream_cycle
    cmd_argv = []
    if getattr(args, "dry_run", False):
        cmd_argv.append("--dry-run")
    if getattr(args, "smoke", False):
        cmd_argv.append("--smoke")
    if getattr(args, "json", False):
        cmd_argv.append("--json")
    if getattr(args, "report", None):
        cmd_argv.extend(["--report", args.report])
    if getattr(args, "provider", None):
        cmd_argv.extend(["--provider", args.provider])
    if getattr(args, "model", None):
        cmd_argv.extend(["--model", args.model])
    return dream_cycle.main(cmd_argv)



def cmd_harvest_curate(args: argparse.Namespace) -> int:
    from autonomous_curation import curate_pending
    res = curate_pending(MEM_ROOT, apply=bool(getattr(args, "apply", False)), limit=args.limit)
    print(json.dumps(res, indent=2))
    return 0


def cmd_harvest_contest(args: argparse.Namespace) -> int:
    from autonomous_curation import contest_candidate
    res = contest_candidate(
        MEM_ROOT, args.candidate_id, args.rationale, apply=bool(getattr(args, "apply", False))
    )
    print(json.dumps(res, indent=2))
    return 0 if res.get("status") != "error" else 1


def cmd_pollution_audit(args: argparse.Namespace) -> int:
    import pollution_audit
    findings = pollution_audit.run_pollution_audit(mem_root=MEM_ROOT)
    print(json.dumps(findings, indent=2))
    return 0


def cmd_pollution_cleanup(args: argparse.Namespace) -> int:
    import pollution_audit
    apply = getattr(args, "apply", False)
    res = pollution_audit.run_pollution_cleanup(apply=apply, mem_root=MEM_ROOT)
    print(json.dumps(res, indent=2))
    return 0 if res.get("status") in ("dry_run", "applied") else 1


def cmd_source_verify(args: argparse.Namespace) -> int:
    import memory_mcp_server
    import schemas
    cand = memory_mcp_server.get_context_candidate_by_id(args.candidate_id, db_path=MEM_ROOT / "gms_trust.sqlite")
    if not cand:
        print(json.dumps({"status": "error", "error": f"Candidate '{args.candidate_id}' not found."}, indent=2))
        return 1
    payload = cand.get("payload", {})
    evidence_list = payload.get("evidence", [])
    if not evidence_list:
        prov = payload.get("provenance", {})
        s_refs = prov.get("source_refs", [])
        evidence_list = [{"ref": r} for r in s_refs]

    results = []
    all_valid = True
    for item in evidence_list:
        ref = item.get("ref", "")
        e_hash = item.get("excerpt_hash")
        valid, status, details = schemas.validate_source_reference(ref, excerpt_hash=e_hash, mem_root=MEM_ROOT)
        if not valid:
            all_valid = False
        results.append({"ref": ref, "valid": valid, "status": status, "details": details})

    output = {
        "candidate_id": args.candidate_id,
        "canonical_key": cand.get("canonical_key"),
        "evidence_count": len(results),
        "all_valid": all_valid,
        "results": results,
    }
    print(json.dumps(output, indent=2))
    return 0 if all_valid else 1


def cmd_eval_harvesting(args: argparse.Namespace) -> int:
    import eval_model_harvesting
    report = eval_model_harvesting.run_evaluation(run_live=getattr(args, "live", False))
    print(json.dumps(report, indent=2))
    return 0

def cmd_convention_audit(_: argparse.Namespace) -> int:
    from memory_convention_audit import convention_audit
    print(json.dumps(convention_audit(MEM_ROOT), indent=2)); return 0

def cmd_convention_cleanup(args: argparse.Namespace) -> int:
    from memory_convention_audit import cleanup_preview, apply_fixture_cleanup
    preview = cleanup_preview(MEM_ROOT)
    if getattr(args, "apply", False):
        required = bool(args.reviewer and len(args.rationale.strip()) >= 10 and args.expected_hash)
        if not required:
            print(json.dumps({"status":"error","error":"apply requires --reviewer, substantive --rationale, and --expected-hash","preview":preview},indent=2)); return 1
        if args.expected_hash != preview["expected_snapshot_hash"]:
            print(json.dumps({"status":"error","error":"snapshot changed; rerun preview"},indent=2)); return 1
        result=apply_fixture_cleanup(MEM_ROOT,actor=args.reviewer,rationale=args.rationale,expected_hash=args.expected_hash,apply=True)
        print(json.dumps(result,indent=2)); return 0 if result.get("status")=="applied" else 1
    print(json.dumps(preview,indent=2)); return 0

def cmd_migration_inventory(_: argparse.Namespace) -> int:
    from memory_convention_audit import migration_inventory
    print(json.dumps(migration_inventory(MEM_ROOT),indent=2)); return 0

def cmd_migration_action(args: argparse.Namespace) -> int:
    from memory_convention_audit import stage_migration, rollback_migration
    keys=[x for x in args.keys.split(",") if x]
    if args.migration_action=="stage":
        result=stage_migration(MEM_ROOT,keys,actor=args.actor,rationale=args.rationale,expected_hash=args.expected_hash,apply=args.apply)
    else:
        result=rollback_migration(MEM_ROOT,keys,actor=args.actor,rationale=args.rationale,apply=args.apply)
    print(json.dumps(result,indent=2)); return 0 if not result.get("errors") else 1

def cmd_aliases(args: argparse.Namespace) -> int:
    from memory_aliases import alias_inventory, resolve_alias, consolidate_collision
    if getattr(args,"consolidate",""):
        result=consolidate_collision(MEM_ROOT,args.consolidate,args.preferred,actor=args.actor,rationale=args.rationale,apply=args.apply)
    else: result=resolve_alias(MEM_ROOT,args.resolve) if args.resolve else alias_inventory(MEM_ROOT)
    print(json.dumps(result,indent=2)); return 0

def cmd_retrieval_plan(args: argparse.Namespace) -> int:
    from context_retrieval_planner import retrieve
    print(json.dumps(retrieve(MEM_ROOT,args.query,project=args.project,as_of=args.as_of,
                              assurance=args.assurance,token_budget=args.token_budget,
                              enable_indexed_vector=args.indexed_vector,
                              embedding_model=args.embedding_model,
                              enable_reranking=args.rerank,
                              rerank_model=args.rerank_model,
                              rerank_k=args.rerank_k),indent=2)); return 0

def cmd_context_packet(args: argparse.Namespace) -> int:
    from context_packet import build_context_packet
    print(json.dumps(build_context_packet(MEM_ROOT,args.query,project=args.project,profile=args.profile,as_of=args.as_of),indent=2)); return 0

def cmd_lifecycle(args: argparse.Namespace) -> int:
    from memory_lifecycle import lifecycle_history, transition
    if args.lifecycle_action == "history":
        print(json.dumps(lifecycle_history(MEM_ROOT/"gms_trust.sqlite",args.record_id),indent=2)); return 0
    request=json.loads(args.request)
    print(json.dumps(transition(MEM_ROOT/"gms_trust.sqlite",request,apply=args.apply),indent=2)); return 0


def cmd_project_briefing(args: argparse.Namespace) -> int:
    from project_briefing import generate_project_briefing, explain_project_briefing
    action = getattr(args, "action", "get") or "get"
    project_id = getattr(args, "project", "")
    if not project_id:
        print(json.dumps({"error": "Missing required --project"}, indent=2))
        return 1
    briefing = generate_project_briefing(MEM_ROOT, project_id, as_of=getattr(args, "as_of", None), profile=getattr(args, "profile", "standard"))
    if action == "explain":
        res = explain_project_briefing(briefing)
        print(json.dumps(res, indent=2))
    else:
        print(json.dumps(briefing, indent=2))
    return 0


def cmd_project_timeline(args: argparse.Namespace) -> int:
    from project_timeline import get_project_timeline
    action = getattr(args, "action", "list") or "list"
    project_id = getattr(args, "project", "") or "global-memory"
    event_type = getattr(args, "event_type", None) or getattr(args, "type", None)
    agent = getattr(args, "agent", None)
    limit = getattr(args, "limit", 50)
    timeline = get_project_timeline(MEM_ROOT, project_id, event_type=event_type, agent=agent, limit=limit)
    if action == "event":
        event_id = getattr(args, "event_id", "")
        if not event_id:
            print(json.dumps({"error": "Missing --event-id"}, indent=2))
            return 1
        found = [e for e in timeline.get("events", []) if e.get("event_id") == event_id]
        if not found:
            print(json.dumps({"error": f"Event not found: {event_id}"}, indent=2))
            return 1
        print(json.dumps(found[0], indent=2))
    else:
        print(json.dumps(timeline, indent=2))
    return 0


def cmd_decision(args: argparse.Namespace) -> int:
    from decision_intelligence import list_decisions, get_decision, get_decision_impact
    action = getattr(args, "action", "list") or "list"
    if action == "list":
        res = list_decisions(MEM_ROOT, project=getattr(args, "project", "") or "", include_superseded=True)
        print(json.dumps(res, indent=2))
    elif action == "get":
        decision_id = getattr(args, "decision_id", "")
        if not decision_id:
            print(json.dumps({"error": "Missing --decision-id"}, indent=2))
            return 1
        res = get_decision(MEM_ROOT, decision_id)
        if not res:
            print(json.dumps({"error": f"Decision not found: {decision_id}"}, indent=2))
            return 1
        print(json.dumps(res, indent=2))
    elif action == "impact":
        decision_id = getattr(args, "decision_id", "")
        if not decision_id:
            print(json.dumps({"error": "Missing --decision-id"}, indent=2))
            return 1
        res = get_decision_impact(MEM_ROOT, decision_id)
        print(json.dumps(res, indent=2))
    return 0


def cmd_action_inbox(args: argparse.Namespace) -> int:
    from action_inbox import list_inbox_items, preview_inbox_action
    action = getattr(args, "action", "list") or "list"
    project = getattr(args, "project", "") or ""
    if action == "list":
        category = getattr(args, "category", None)
        res = list_inbox_items(MEM_ROOT, project=project)
        if category:
            res["items"] = [it for it in res.get("items", []) if it.get("category") == category]
            res["total_count"] = len(res["items"])
        print(json.dumps(res, indent=2))
    elif action in ("preview", "apply"):
        inbox_id = getattr(args, "inbox_id", "")
        if not inbox_id:
            print(json.dumps({"error": "Missing --inbox-id"}, indent=2))
            return 1
        preview = preview_inbox_action(MEM_ROOT, inbox_id=inbox_id, project=project)
        if action == "apply":
            if not getattr(args, "apply", False):
                print(json.dumps({"status": "preview_only", "message": "Pass --apply to execute", "preview": preview}, indent=2))
                return 0
            if not preview.get("executable"):
                print(json.dumps({"status": "blocked", "error": preview.get("consequence", "Action not executable directly"), "preview": preview}, indent=2))
                return 1
            if preview.get("target_type") == "candidate":
                from harvest import review_candidate
                candidate_id = preview.get("target_id")
                review_action = preview.get("suggested_action", "defer")
                rev_res = review_candidate(
                    root=MEM_ROOT,
                    candidate_id=candidate_id,
                    action=review_action,
                    reviewer=getattr(args, "reviewer", "cli") or "cli",
                    rationale=getattr(args, "rationale", "Applied from action inbox") or "Applied from action inbox",
                    expected_hash=getattr(args, "expected_hash", None)
                )
                print(json.dumps({"status": "applied", "result": rev_res}, indent=2))
                return 0 if rev_res.get("status") == "ok" else 1
            else:
                print(json.dumps({"status": "preview_only", "preview": preview}, indent=2))
                return 0
        print(json.dumps(preview, indent=2))
    return 0


def cmd_memory_repair(args: argparse.Namespace) -> int:
    from memory_repair import find_repair_evidence, analyze_missing_fields, stage_repair_candidate, archive_opaque_fact
    action = getattr(args, "action", "analyze") or "analyze"
    key = getattr(args, "key", "")
    if not key:
        print(json.dumps({"error": "Missing --key"}, indent=2))
        return 1
    if action == "evidence":
        res = find_repair_evidence(MEM_ROOT, key)
        print(json.dumps(res, indent=2))
    elif action == "questions":
        analysis = analyze_missing_fields(MEM_ROOT, key)
        print(json.dumps({
            "key": key,
            "user_questions": analysis.get("user_questions", []),
            "current_value": analysis.get("current_value"),
            "proposed_fields": analysis.get("proposed_fields", {})
        }, indent=2))
    elif action == "analyze":
        res = analyze_missing_fields(MEM_ROOT, key)
        print(json.dumps(res, indent=2))
    elif action == "stage":
        payload_str = getattr(args, "payload", None)
        if not payload_str:
            analysis = analyze_missing_fields(MEM_ROOT, key)
            repaired_payload = analysis.get("proposed_fields", {})
        else:
            repaired_payload = json.loads(payload_str)
        apply = getattr(args, "apply", False)
        actor = getattr(args, "actor", "cli")
        rationale = getattr(args, "rationale", "Repaired from source evidence")
        res = stage_repair_candidate(
            MEM_ROOT, legacy_key=key, repaired_payload=repaired_payload, apply=apply, actor=actor, rationale=rationale
        )
        print(json.dumps(res, indent=2))
    elif action == "archive":
        res=archive_opaque_fact(MEM_ROOT,key,actor=getattr(args,"actor","system"),rationale=getattr(args,"rationale",""),apply=getattr(args,"apply",False))
        print(json.dumps(res,indent=2))
    return 0


def cmd_morning_briefing(args: argparse.Namespace) -> int:
    from morning_briefing import generate_morning_briefing, list_morning_briefings
    action = getattr(args, "action", "get") or "get"
    project_id = getattr(args, "project", None)
    if action == "list" or not project_id:
        res = list_morning_briefings(MEM_ROOT)
        print(json.dumps(res, indent=2))
    else:
        res = generate_morning_briefing(MEM_ROOT, project_id, as_of=getattr(args, "as_of", None))
        print(json.dumps(res, indent=2))
    return 0


def cmd_eval_resumption(args: argparse.Namespace) -> int:
    from resumption_eval import run_resumption_evaluation
    res = run_resumption_evaluation(
        MEM_ROOT,
        enable_indexed_vector=getattr(args, "indexed_vector", False),
        run_agent_trial=getattr(args, "live_agent", False),
        agent_model=getattr(args, "model", "qwen3:8b"),
    )
    print(json.dumps(res, indent=2))
    return 0


def cmd_eval_lab(args: argparse.Namespace) -> int:
    import eval.cli
    action = getattr(args, "action", "run")
    if action == "run":
        eval.cli.run_evals(suite=getattr(args, "suite", "all"), export=not getattr(args, "no_export", False), live=getattr(args, "live", False))
        return 0
    elif action == "ablate":
        eval.cli.run_ablations(export=not getattr(args, "no_export", False), live=getattr(args, "live", False))
        return 0
    return 1


def cmd_file_context(args: argparse.Namespace) -> int:
    import memory_mcp_server
    res = memory_mcp_server.tool_mem_file_context({
        "file_path": getattr(args, "file_path", ""),
        "project": getattr(args, "project", "") or "",
    })
    print(res)
    return 0


def cmd_learn_error(args: argparse.Namespace) -> int:
    import memory_mcp_server
    res = memory_mcp_server.tool_mem_learn_error({
        "error_trace": getattr(args, "error_trace", ""),
        "command": getattr(args, "command", "") or "",
        "resolution": getattr(args, "resolution", "") or "",
        "project": getattr(args, "project", "") or "",
        "agent": getattr(args, "agent", "developer"),
    })
    print(res)
    return 0


def cmd_core_memory(args: argparse.Namespace) -> int:
    import memory_mcp_server
    action = getattr(args, "action", "get")
    if action == "get":
        print(memory_mcp_server.tool_mem_core_memory_get({}))
    elif action == "append":
        print(memory_mcp_server.tool_mem_core_memory_append({
            "block": args.block,
            "content": args.content,
            "agent": getattr(args, "agent", "developer"),
        }))
    elif action == "replace":
        print(memory_mcp_server.tool_mem_core_memory_replace({
            "block": args.block,
            "new_content": args.new_content,
            "old_content": getattr(args, "old_content", "") or "",
            "agent": getattr(args, "agent", "developer"),
        }))
    return 0


def cmd_graph_communities(args: argparse.Namespace) -> int:
    import memory_mcp_server
    print(memory_mcp_server.tool_mem_graph_communities({}))
    return 0


def cmd_reflect(args: argparse.Namespace) -> int:
    import memory_mcp_server
    print(memory_mcp_server.tool_mem_reflect({}))
    return 0


def cmd_trap(args: argparse.Namespace) -> int:
    import memory_mcp_server
    action = getattr(args, "action", "list")
    if action == "create":
        print(memory_mcp_server.tool_mem_trap_create({
            "name": args.name,
            "pattern": args.pattern,
            "payload": args.payload,
            "trigger_type": getattr(args, "trigger_type", "keyword"),
            "recurring": getattr(args, "recurring", False),
            "agent": getattr(args, "agent", "developer"),
        }))
    elif action == "list":
        print(memory_mcp_server.tool_mem_trap_list({
            "active_only": getattr(args, "active_only", False)
        }))
    elif action == "eval":
        print(memory_mcp_server.tool_mem_trap_eval({
            "context": args.context
        }))
    elif action == "dismiss":
        print(memory_mcp_server.tool_mem_trap_dismiss({
            "name": args.name
        }))
    return 0


def cmd_speculative_prefetch(args: argparse.Namespace) -> int:
    import memory_mcp_server
    print(memory_mcp_server.tool_mem_speculative_prefetch({
        "active_file": getattr(args, "active_file", "") or "",
        "intent": getattr(args, "intent", "") or "",
        "project": getattr(args, "project", "") or "",
    }))
    return 0


def cmd_programmatic_guard(args: argparse.Namespace) -> int:
    import memory_mcp_server
    ctx = {}
    if getattr(args, "context", None):
        try:
            ctx = json.loads(args.context)
        except Exception:
            pass
    req_keys = [k.strip() for k in args.required_keys.split(",") if k.strip()] if getattr(args, "required_keys", None) else []
    print(memory_mcp_server.tool_mem_programmatic_guard({
        "guard_name": args.guard_name,
        "context": ctx,
        "required_keys": req_keys,
        "max_chars": getattr(args, "max_chars", 4000),
        "condition": getattr(args, "condition", True),
        "reason": getattr(args, "reason", "CLI programmatic guard"),
    }))
    return 0


def cmd_staleness_verify(args: argparse.Namespace) -> int:
    import memory_mcp_server
    print(memory_mcp_server.tool_mem_staleness_verify({
        "file_path": getattr(args, "file_path", "") or "",
        "stored_hash": getattr(args, "stored_hash", "") or "",
        "key": getattr(args, "key", "") or "",
    }))
    return 0


def cmd_causal_recall(args: argparse.Namespace) -> int:
    import memory_mcp_server
    print(memory_mcp_server.tool_mem_causal_recall({
        "query": getattr(args, "query", "") or "",
        "outcome_filter": getattr(args, "outcome", "resolved_fix") or "resolved_fix",
        "limit": getattr(args, "limit", 5),
    }))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Memory control CLI for global-memory skill.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p0 = sub.add_parser("start-context", help="Print startup context bundle from memory.")
    p0.set_defaults(fn=cmd_start_context)

    p1 = sub.add_parser("find", help="Search semantic memory with ripgrep.")
    p1.add_argument("pattern")
    p1.set_defaults(fn=cmd_find)

    p2 = sub.add_parser("log", help="Append episodic milestone entry.")
    p2.add_argument("--agent", required=True)
    p2.add_argument("--title", required=True)
    p2.add_argument("--note", required=True)
    p2.set_defaults(fn=cmd_log)

    p3 = sub.add_parser("lesson-add", help="Append global lesson.")
    p3.add_argument("text")
    p3.set_defaults(fn=cmd_lesson_add)

    p4 = sub.add_parser("fact-set", help="Set semantic fact key/value in facts.json.")
    p4.add_argument("key")
    p4.add_argument("value")
    p4.set_defaults(fn=cmd_fact_set)

    p4_1 = sub.add_parser("fact-validate", help="Validate active facts against registered schema contracts.")
    p4_1.set_defaults(fn=cmd_fact_validate)

    p5 = sub.add_parser("index-build", help="Build FAISS episodic index using Ollama embeddings.")
    p5.add_argument("--model", default=DEFAULT_EMBED_MODEL)
    p5.add_argument("--drift-threshold", type=float, default=0.05, help="Angular-distance alert threshold for drift snapshots.")
    p5.set_defaults(fn=cmd_index_build)

    p6 = sub.add_parser("index-query", help="Query FAISS episodic index.")
    p6.add_argument("query")
    p6.add_argument("-k", type=int, default=5)
    p6.add_argument("--model", default=DEFAULT_EMBED_MODEL)
    p6.add_argument("--decay-rate", type=float, default=0.002, help="Exponential decay rate per day.")
    p6.add_argument("--no-decay", action="store_true", help="Disable temporal decay.")
    p6.add_argument("--branch-boost", type=float, default=1.15, help="Active branch text match boost multiplier.")
    p6.add_argument("--no-boost", action="store_true", help="Disable git branch boost.")
    p6.add_argument("--no-hybrid", action="store_true", help="Disable BM25 hybrid search RRF.")
    p6.add_argument("--rerank", action="store_true", default=True, help="Enable Stage-2 Cross-Encoder reranking (default).")
    p6.add_argument("--no-rerank", action="store_true", help="Disable Stage-2 Cross-Encoder reranking.")
    p6.add_argument("--rerank-model", default=DEFAULT_RERANK_MODEL, help=f"Cross-encoder model for FlashRank (default: {DEFAULT_RERANK_MODEL}).")
    p6.add_argument("--rerank-k", type=int, default=25, help="Candidate pool size to pass to cross-encoder reranker.")
    p6.set_defaults(fn=cmd_index_query)

    p7 = sub.add_parser("trust-list", help="List all agent reputations.")
    p7.set_defaults(fn=cmd_trust_list)

    p8 = sub.add_parser("quarantine-list", help="List all quarantined facts.")
    p8.set_defaults(fn=cmd_quarantine_list)

    p9 = sub.add_parser("quarantine-resolve", help="Resolve a quarantined fact.")
    p9.add_argument("key", help="The fact key to resolve.")
    p9.add_argument("agent_id", help="The agent who proposed the fact.")
    p9.add_argument("action", choices=["promote", "discard"], help="Resolution action.")
    p9.add_argument("--resolver", default="CLI", help="The resolving agent identity.")
    p9.set_defaults(fn=cmd_quarantine_resolve)

    p9_1 = sub.add_parser("quarantine-review-add", help="Add a reviewer endorsement, rejection, or abstention for a quarantined item.")
    p9_1.add_argument("key", help="The fact key.")
    p9_1.add_argument("agent_id", help="The agent who proposed the fact.")
    p9_1.add_argument("rating", choices=["endorse", "reject", "abstain"], help="Witness stance for the quarantined item.")
    p9_1.add_argument("--reviewer", required=True, help="The reviewer agent identity.")
    p9_1.add_argument("--rationale", default="", help="Optional rationale.")
    p9_1.set_defaults(fn=cmd_quarantine_review_add)

    p9_2 = sub.add_parser("quarantine-review-list", help="List all reviews for a quarantined item.")
    p9_2.add_argument("key", help="The fact key.")
    p9_2.add_argument("agent_id", help="The agent who proposed the fact.")
    p9_2.set_defaults(fn=cmd_quarantine_review_list)

    p9_3 = sub.add_parser("quarantine-recommendation", help="Get a weighted recommendation summary for a quarantined item.")
    p9_3.add_argument("key", help="The fact key.")
    p9_3.add_argument("agent_id", help="The agent who proposed the fact.")
    p9_3.set_defaults(fn=cmd_quarantine_recommendation)

    p10 = sub.add_parser("claims-list", help="List all recorded claims in the versioned claim ledger.")
    p10.add_argument("--kind", help="Filter by memory kind.")
    p10.add_argument("--key", help="Filter by memory key.")
    p10.add_argument("--status", help="Filter by claim status.")
    p10.set_defaults(fn=cmd_claims_list)

    p11 = sub.add_parser("drift-status", help="Report semantic drift status from the latest index snapshots.")
    p11.add_argument("--threshold", type=float, default=0.05, help="Angular-distance alert threshold.")
    p11.add_argument("--json", action="store_true", help="Retained for compatibility; output is always JSON.")
    p11.set_defaults(fn=cmd_drift_status)

    p12 = sub.add_parser("calibration-report", help="Summarize observer overlap, agreement, and disagreement from the claim ledger.")
    p12.add_argument("--json", action="store_true", help="Output raw JSON.")
    p12.set_defaults(fn=cmd_calibration_report)

    p13 = sub.add_parser("retention-report", help="Report stale low-confidence active facts and stale quarantines.")
    p13.add_argument("--low-confidence", type=float, default=0.35, help="Confidence threshold for archival candidates.")
    p13.add_argument("--stale-active-days", type=int, default=30, help="Minimum age in days for low-confidence active claims.")
    p13.add_argument("--stale-quarantine-days", type=int, default=14, help="Minimum age in days for stale quarantines.")
    p13.add_argument("--json", action="store_true", help="Output raw JSON.")
    p13.set_defaults(fn=cmd_retention_report)

    p14 = sub.add_parser("retention-prune", help="Archive stale low-confidence active facts and flush stale quarantines.")
    p14.add_argument("--low-confidence", type=float, default=0.35, help="Confidence threshold for archival candidates.")
    p14.add_argument("--stale-active-days", type=int, default=30, help="Minimum age in days for low-confidence active claims.")
    p14.add_argument("--stale-quarantine-days", type=int, default=14, help="Minimum age in days for stale quarantines.")
    p14.add_argument("--json", action="store_true", help="Output raw JSON.")
    p14.set_defaults(fn=cmd_retention_prune)

    p15 = sub.add_parser("tui", help="Launch the SSH-friendly terminal UI.")
    p15.set_defaults(fn=cmd_tui)

    p16 = sub.add_parser("task-create", help="Create a durable project-scoped task for cross-agent work.")
    p16.add_argument("task_id")
    p16.add_argument("title")
    p16.add_argument("--agent", required=True)
    p16.add_argument("--project", default="")
    p16.add_argument("--objective", default="")
    p16.add_argument("--parent-task-id", default="")
    p16.set_defaults(fn=cmd_task_create)

    p17 = sub.add_parser("task-claim", help="Atomically claim a task at its current revision.")
    p17.add_argument("task_id")
    p17.add_argument("expected_revision", type=int)
    p17.add_argument("--agent", required=True)
    p17.add_argument("--lease-seconds", type=int, default=1800)
    p17.set_defaults(fn=cmd_task_claim)

    p18 = sub.add_parser("task-checkpoint", help="Save an immutable JSON state checkpoint for an owned task.")
    p18.add_argument("task_id")
    p18.add_argument("expected_revision", type=int)
    p18.add_argument("--agent", required=True)
    p18.add_argument("--state", required=True, help="JSON object")
    p18.add_argument("--label", default="")
    p18.add_argument("--artifact-refs", default="[]", help="JSON array")
    p18.add_argument("--claim-refs", default="[]", help="JSON array")
    p18.add_argument("--episode-refs", default="[]", help="JSON array")
    p18.set_defaults(fn=cmd_task_checkpoint)

    p19 = sub.add_parser("task-handoff", help="Release an owned task with a structured handoff package.")
    p19.add_argument("task_id")
    p19.add_argument("expected_revision", type=int)
    p19.add_argument("--source-agent", required=True)
    p19.add_argument("--target-agent", default="")
    p19.add_argument("--objective", default="")
    p19.add_argument("--completed-work", default="")
    p19.add_argument("--next-action", default="")
    p19.add_argument("--blockers", default="")
    p19.add_argument("--acceptance-criteria", default="")
    p19.add_argument("--context", default="{}", help="JSON object")
    p19.add_argument("--artifact-refs", default="[]", help="JSON array")
    p19.set_defaults(fn=cmd_task_handoff)

    p20 = sub.add_parser("task-resume", help="Build or verify agent resumption bundle, or read a task's handoff.")
    p20.add_argument("action_or_task_id", nargs="?", default=None, help="Action ('build', 'verify') or task_id")
    p20.add_argument("--task-id", dest="task_id_flag", default=None, help="Explicit task ID")
    p20.add_argument("--project", default=None, help="Project identifier")
    p20.add_argument("--format", choices=["antigravity", "codex", "gemini", "json"], default="antigravity", help="Target agent prompt format")
    p20.add_argument("--as-of", default=None, help="Point-in-time timestamp")
    p20.set_defaults(fn=cmd_task_resume)

    p21 = sub.add_parser("task-complete", help="Mark an owned task completed at its current revision.")
    p21.add_argument("task_id")
    p21.add_argument("expected_revision", type=int)
    p21.add_argument("--agent", required=True)
    p21.set_defaults(fn=cmd_task_complete)

    p22 = sub.add_parser("project-state", help="Show current tasks and latest handoffs/checkpoints for a project.")
    p22.add_argument("project")
    p22.add_argument("--include-completed", action="store_true")
    p22.set_defaults(fn=cmd_project_state)

    p23 = sub.add_parser("graph-build", help="Batch extract triples from active claims, facts, and episodic history into SQLite graph tables.")
    p23.set_defaults(fn=cmd_graph_build)

    p24 = sub.add_parser("graph-query", help="Query 1-hop & 2-hop Knowledge Graph relationships for an entity.")
    p24.add_argument("entity")
    p24.add_argument("--hops", type=int, default=2)
    p24.add_argument("--as-of", default=None, help="Point-in-time timestamp for time-travel queries")
    p24.add_argument("--include-expired", action="store_true", help="Include historically invalidated/expired edges")
    p24.set_defaults(fn=cmd_graph_query)

    p25 = sub.add_parser("graph-show", help="Render ASCII Knowledge Graph topology for an entity in the terminal.")
    p25.add_argument("entity")
    p25.add_argument("--hops", type=int, default=2)
    p25.add_argument("--as-of", default=None, help="Point-in-time timestamp for time-travel queries")
    p25.add_argument("--include-expired", action="store_true", help="Include historically invalidated/expired edges")
    p25.set_defaults(fn=cmd_graph_show)

    p25_1 = sub.add_parser("graph-invalidate", help="Invalidate active relationship edges in the Knowledge Graph.")
    p25_1.add_argument("subject", help="Subject entity name")
    p25_1.add_argument("predicate", help="Relationship predicate")
    p25_1.add_argument("--object", default=None, help="Target object (optional)")
    p25_1.add_argument("--valid-to", default=None, help="Expiration timestamp (defaults to current time)")
    p25_1.set_defaults(fn=cmd_graph_invalidate)

    p26 = sub.add_parser("latest", help="Fetch the latest N episodic milestones and fact updates across memory.")
    p26.add_argument("--limit", type=int, default=10)
    p26.add_argument("--kind", default="all", choices=["episodic", "facts", "claims", "all"])
    p26.set_defaults(fn=cmd_latest)

    p27 = sub.add_parser("project-init", help="Initialize a Cline Memory Bank style project structure (brief, patterns, tech, active, progress).")
    p27.add_argument("project")
    p27.set_defaults(fn=cmd_project_init)

    p28 = sub.add_parser("project-get", help="Get a project memory bank section or all sections.")
    p28.add_argument("project")
    p28.add_argument("--section", default="all", choices=["brief", "patterns", "tech", "active", "progress", "all"])
    p28.set_defaults(fn=cmd_project_get)

    p29 = sub.add_parser("project-update", help="Update a section in a project's memory bank.")
    p29.add_argument("project")
    p29.add_argument("--section", default="active", choices=["brief", "patterns", "tech", "active", "progress"])
    p29.add_argument("--content", required=True)
    p29.add_argument("--overwrite", action="store_true", help="Overwrite section instead of appending.")
    p29.set_defaults(fn=cmd_project_update)

    p30 = sub.add_parser("project-list", help="List all initialized project memory banks.")
    p30.set_defaults(fn=cmd_project_list)

    p31 = sub.add_parser("synthesize", help="Synthesize executive project or system snapshot using local Ollama LLM.")
    p31.add_argument("--project", default="")
    p31.add_argument("--topic", default="")
    p31.add_argument("--model", default="qwen3.5:9b")
    p31.set_defaults(fn=cmd_synthesize)

    p32 = sub.add_parser("audit", help="Audit semantic facts and claim ledgers for contradictions using local Ollama LLM or rules.")
    p32.add_argument("--model", default="qwen3.5:9b")
    p32.set_defaults(fn=cmd_audit)

    p33 = sub.add_parser("link-memory", help="Explicitly link a memory item (claim, fact, task, episode) to a Knowledge Graph entity.")
    p33.add_argument("--ref", required=True, help="Memory reference (e.g. claim:292, fact:key, task:id)")
    p33.add_argument("--entity", required=True, help="Target entity name or entity_id")
    p33.add_argument("--rel", default="references", help="Relationship type (references, affects, configures, documents)")
    p33.set_defaults(fn=cmd_link_memory)

    p34 = sub.add_parser("entity-memories", help="Retrieve all memory references linked to a specific Knowledge Graph entity.")
    p34.add_argument("--entity", required=True, help="Entity name or entity_id")
    p34.set_defaults(fn=cmd_entity_memories)

    p35 = sub.add_parser("session-harvest", help="Perform automated post-session micro-consolidation ('Agentic Sleep').")
    p35.add_argument("--agent", default="Antigravity", help="Agent name")
    p35.add_argument("--summary", required=True, help="Session summary")
    p35.add_argument("--text", default=None, help="Optional text context")
    p35.add_argument("--no-index", action="store_true", help="Skip incremental vector indexing")
    p35.set_defaults(fn=cmd_session_harvest)

    p36 = sub.add_parser("backfill", help="Idempotently backfill SQLite tables, vectors, claims, procedures, and graph.")
    p36.add_argument("--root", default=None, help="Custom memory root directory.")
    p36.add_argument("--dry-run", action="store_true", help="Preview backfill without modifying database.")
    p36.add_argument("--skip-embeddings", action="store_true", help="Skip vector embedding backfill.")
    p36.add_argument("--skip-graph", action="store_true", help="Skip knowledge graph relationship backfill.")
    p36.add_argument("--json", action="store_true", help="Output result as JSON.")
    p36.set_defaults(fn=cmd_backfill)

    p37 = sub.add_parser("backup", help="Perform atomic online backup of gms_trust.sqlite using SQLite native backup API.")
    p37.add_argument("--root", default=None, help="Custom memory root directory.")
    p37.add_argument("--dest", default=None, help="Custom destination backup file path.")
    p37.add_argument("--json", action="store_true", help="Output result as JSON.")
    p37.set_defaults(fn=cmd_backup)

    p_sync = sub.add_parser("sync-stores", help="Reconcile facts.json and gms_claims in SQLite.")
    p_sync.add_argument("--root", default=None, help="Custom memory root directory.")
    p_sync.add_argument("--json", action="store_true", help="Output result as JSON.")
    p_sync.set_defaults(fn=cmd_sync_stores)

    p38 = sub.add_parser("ui", help="Launch Mbrain Desktop Control Center (macOS Electron App).")
    p38.set_defaults(fn=cmd_ui)

    p39 = sub.add_parser("apple", help="Safe Apple ecosystem automation (Reminders, Notes, Calendar).")
    p39.add_argument("app_type", choices=["reminder", "note", "calendar"], help="Apple app to interact with")
    p39.add_argument("action", nargs="?", default="list", choices=["list", "add"], help="Action: list or add")
    p39.add_argument("--title", default="", help="Title / name of reminder or note")
    p39.add_argument("--notes", "--body", dest="notes", default="", help="Body or notes text")
    p39.add_argument("--due", default="", help="Due date string for reminder")
    p39.set_defaults(fn=cmd_apple)

    p_hs = sub.add_parser("harvest-status", help="Show context harvesting and review queue status.")
    p_hs.set_defaults(fn=cmd_harvest_status)

    p_hc = sub.add_parser("harvest-candidates", help="Query staged context harvest candidates.")
    p_hc.add_argument("--project", default=None, help="Filter by project")
    p_hc.add_argument("--type", default=None, help="Filter by record type")
    p_hc.add_argument("--status", default="proposed", help="Filter by review status (proposed, accepted, rejected, deferred, all)")
    p_hc.add_argument("--limit", type=int, default=50, help="Max results")
    p_hc.add_argument("--offset", type=int, default=0, help="Pagination offset")
    p_hc.set_defaults(fn=cmd_harvest_candidates)

    p_hshow = sub.add_parser("harvest-show", help="Show candidate details and diff against active memory.")
    p_hshow.add_argument("candidate_id", help="Candidate ID to inspect")
    p_hshow.set_defaults(fn=cmd_harvest_show)

    p_hr = sub.add_parser("harvest-review", help="Review a staged candidate (accept, edit, merge, supersede, reject, defer).")
    p_hr.add_argument("candidate_id", help="Candidate ID to review")
    p_hr.add_argument("--action", required=True, choices=["accept", "edit", "merge", "supersede", "reject", "defer"], help="Review action")
    p_hr.add_argument("--reviewer", default="mihir", help="Reviewer identity (e.g. mihir, antigravity, codex, gemini, cli)")
    p_hr.add_argument("--rationale", default="", help="Substantive review rationale (>=10 chars)")
    p_hr.add_argument("--edited-payload", default=None, help="JSON string for edited payload")
    p_hr.add_argument("--merge-with", type=int, default=None, help="Claim ID to merge with or supersede")
    p_hr.add_argument("--expected-hash", default=None, help="Expected candidate content hash for optimistic concurrency")
    p_hr.set_defaults(fn=cmd_harvest_review)

    p_hmf = sub.add_parser("harvest-migrate-flat", help="Migrate legacy flat facts into typed context records.")
    p_hmf.add_argument("--apply", action="store_true", help="Stage candidates in SQLite")
    p_hmf.add_argument("--dry-run", action="store_true", default=True, help="Preview migration without staging (default)")
    p_hmf.set_defaults(fn=cmd_harvest_migrate_flat)

    p_hrun = sub.add_parser("harvest-run", help="Run context harvesting pipeline.")
    p_hrun.add_argument("--dry-run", action="store_true", help="Dry run extraction")
    p_hrun.add_argument("--smoke", action="store_true", help="Run bounded local preflight smoke check")
    p_hrun.add_argument("--report", default=None, help="Output machine-readable report JSON to file")
    p_hrun.add_argument("--json", action="store_true", help="Print report JSON to stdout")
    p_hrun.add_argument("--provider", default=None, help="Force LLM provider")
    p_hrun.add_argument("--model", default=None, help="Force LLM model")
    p_hrun.set_defaults(fn=cmd_harvest_run)

    p_hcur = sub.add_parser("harvest-curate", help="Evidence-gated system decisions for pending candidates (preview by default).")
    p_hcur.add_argument("--apply", action="store_true", help="Apply the system decisions with an audit trail")
    p_hcur.add_argument("--limit", type=int, default=100, help="Maximum candidates to adjudicate")
    p_hcur.set_defaults(fn=cmd_harvest_curate)

    p_hcontest = sub.add_parser("harvest-contest", help="Contest a system-accepted candidate and restore prior truth.")
    p_hcontest.add_argument("candidate_id", help="System-accepted candidate ID")
    p_hcontest.add_argument("--rationale", required=True, help="Why the system decision is incorrect (>=10 chars)")
    p_hcontest.add_argument("--apply", action="store_true", help="Apply the contest; otherwise preview")
    p_hcontest.set_defaults(fn=cmd_harvest_contest)

    p_pa = sub.add_parser("pollution-audit", help="Read-only scan of suspected test fixtures and synthetic pollution.")
    p_pa.set_defaults(fn=cmd_pollution_audit)

    p_pc = sub.add_parser("pollution-cleanup", help="Surgically clean test fixtures and synthetic pollution.")
    p_pc.add_argument("--dry-run", action="store_true", default=True, help="Preview cleanup without mutation (default)")
    p_pc.add_argument("--apply", action="store_true", help="Apply cleanup with audit record")
    p_pc.set_defaults(fn=cmd_pollution_cleanup)

    p_sv = sub.add_parser("source-verify", help="Verify source file existence, anchors, and excerpt hashes for a candidate.")
    p_sv.add_argument("candidate_id", help="Candidate ID to verify")
    p_sv.set_defaults(fn=cmd_source_verify)

    p_eh = sub.add_parser("eval-harvesting", help="Evaluate local model harvesting against checked-in corpus and installed models.")
    p_eh.add_argument("--live", action="store_true", help="Run live inference and test explicit model unload")
    p_eh.set_defaults(fn=cmd_eval_harvesting)

    p_ca = sub.add_parser("convention-audit", help="Read-only memory convention and fixture-warning audit.")
    p_ca.set_defaults(fn=cmd_convention_audit)
    p_cc = sub.add_parser("convention-cleanup", help="Preview exact fixture cleanup; apply is fail-closed.")
    p_cc.add_argument("--apply",action="store_true"); p_cc.add_argument("--reviewer",default="")
    p_cc.add_argument("--rationale",default=""); p_cc.add_argument("--expected-hash",default="")
    p_cc.set_defaults(fn=cmd_convention_cleanup)
    p_mi = sub.add_parser("migration-inventory", help="Preview migration of every legacy flat fact.")
    p_mi.set_defaults(fn=cmd_migration_inventory)
    p_ma = sub.add_parser("migration-action", help="Preview/stage or rollback selected legacy migrations.")
    p_ma.add_argument("migration_action",choices=["stage","rollback"]); p_ma.add_argument("--keys",required=True)
    p_ma.add_argument("--actor",required=True); p_ma.add_argument("--rationale",required=True); p_ma.add_argument("--expected-hash",default="")
    p_ma.add_argument("--apply",action="store_true"); p_ma.set_defaults(fn=cmd_migration_action)
    p_al = sub.add_parser("aliases", help="List aliases/collisions or resolve one key without merging.")
    p_al.add_argument("--resolve",default=""); p_al.set_defaults(fn=cmd_aliases)
    p_al.add_argument("--consolidate",default=""); p_al.add_argument("--preferred",default="")
    p_al.add_argument("--actor",default="system"); p_al.add_argument("--rationale",default="")
    p_al.add_argument("--apply",action="store_true")
    p_rp = sub.add_parser("retrieval-plan", help="Inspect deterministic multi-lane retrieval.")
    p_rp.add_argument("query"); p_rp.add_argument("--project",default=""); p_rp.add_argument("--as-of",default=None)
    p_rp.add_argument("--assurance",default="standard",choices=["low","standard","high"])
    p_rp.add_argument("--token-budget",type=int,default=2400)
    p_rp.add_argument("--indexed-vector", action="store_true", help="Use the local indexed embedding lane (loads the embedding model lazily).")
    p_rp.add_argument("--embedding-model", default=DEFAULT_EMBED_MODEL)
    p_rp.add_argument("--rerank", action="store_true", help="Rerank fused candidates with the local FlashRank cross-encoder.")
    p_rp.add_argument("--rerank-model", default=DEFAULT_RERANK_MODEL)
    p_rp.add_argument("--rerank-k", type=int, default=25)
    p_rp.set_defaults(fn=cmd_retrieval_plan)
    p_cp = sub.add_parser("context-packet", help="Generate an explainable deterministic context packet.")
    p_cp.add_argument("query"); p_cp.add_argument("--project",default=""); p_cp.add_argument("--as-of",default=None)
    p_cp.add_argument("--profile",default="standard",choices=["small","standard","deep"]); p_cp.set_defaults(fn=cmd_context_packet)
    p_lc = sub.add_parser("lifecycle", help="Preview/apply a lifecycle request or inspect history.")
    p_lc.add_argument("lifecycle_action",choices=["transition","history"]); p_lc.add_argument("record_id",nargs="?",default="")
    p_lc.add_argument("--request",default="{}"); p_lc.add_argument("--apply",action="store_true"); p_lc.set_defaults(fn=cmd_lifecycle)

    p_pb = sub.add_parser("project-briefing", help="Generate or explain operational project briefing.")
    p_pb.add_argument("action", nargs="?", default="get", choices=["get", "generate", "explain"])
    p_pb.add_argument("--project", required=True, help="Project identifier")
    p_pb.add_argument("--as-of", default=None, help="Historical point-in-time timestamp")
    p_pb.add_argument("--profile", default="standard", choices=["standard", "condensed", "deep"])
    p_pb.set_defaults(fn=cmd_project_briefing)

    p_pt = sub.add_parser("project-timeline", help="Unified stream of project history and lifecycle events.")
    p_pt.add_argument("action", nargs="?", default="list", choices=["list", "event"])
    p_pt.add_argument("--project", default="", help="Project identifier")
    p_pt.add_argument("--event-id", default="", help="Event ID for 'event' action")
    p_pt.add_argument("--type", "--event-type", dest="event_type", default=None, help="Filter by event type")
    p_pt.add_argument("--agent", default=None, help="Filter by agent ID")
    p_pt.add_argument("--limit", type=int, default=50, help="Max events to return")
    p_pt.add_argument("--as-of", default=None, help="Historical point-in-time timestamp")
    p_pt.set_defaults(fn=cmd_project_timeline)

    p_dec = sub.add_parser("decision", help="Query and inspect binding project decisions and rationale.")
    p_dec.add_argument("action", choices=["list", "get", "impact"], help="Decision action")
    p_dec.add_argument("--project", default=None, help="Project identifier")
    p_dec.add_argument("--decision-id", default="", help="Decision ID for get/impact")
    p_dec.add_argument("--status", default=None, help="Status filter (active, superseded, proposed)")
    p_dec.set_defaults(fn=cmd_decision)

    p_ainbox = sub.add_parser("action-inbox", help="Consequence-ranked action inbox for unresolved memory states.")
    p_ainbox.add_argument("action", nargs="?", default="list", choices=["list", "preview", "apply"])
    p_ainbox.add_argument("--project", default=None, help="Project identifier")
    p_ainbox.add_argument("--inbox-id", default="", help="Item ID for preview/apply")
    p_ainbox.add_argument("--category", default=None, help="Category filter")
    p_ainbox.add_argument("--apply", action="store_true", help="Apply executable inbox action")
    p_ainbox.add_argument("--reviewer", default="cli", help="Reviewer identity for candidate reviews")
    p_ainbox.add_argument("--rationale", default="Applied from action inbox", help="Review rationale")
    p_ainbox.add_argument("--expected-hash", default=None, help="Expected content hash")
    p_ainbox.set_defaults(fn=cmd_action_inbox)

    p_mrep = sub.add_parser("memory-repair", help="Discover source evidence and repair incomplete memory records.")
    p_mrep.add_argument("action", choices=["evidence", "questions", "analyze", "stage", "archive"], help="Repair action")
    p_mrep.add_argument("--key", required=True, help="Fact key to repair")
    p_mrep.add_argument("--payload", default=None, help="Repaired JSON payload for staging")
    p_mrep.add_argument("--apply", action="store_true", help="Persist staged candidate")
    p_mrep.add_argument("--actor", default="cli", help="Actor identity")
    p_mrep.add_argument("--rationale", default="Repaired from source evidence", help="Repair rationale")
    p_mrep.set_defaults(fn=cmd_memory_repair)

    p_mb = sub.add_parser("morning-briefing", help="Generate or list morning operational briefings.")
    p_mb.add_argument("action", nargs="?", default="get", choices=["get", "list"])
    p_mb.add_argument("--project", default=None, help="Project identifier")
    p_mb.add_argument("--as-of", default=None, help="Historical point-in-time timestamp")
    p_mb.set_defaults(fn=cmd_morning_briefing)

    p_evr = sub.add_parser("eval-resumption", help="Evaluate project resumption fidelity against benchmark scenarios.")
    p_evr.add_argument("action", nargs="?", default="run", choices=["run", "report"])
    p_evr.add_argument("--project", default=None, help="Project identifier filter")
    p_evr.add_argument("--indexed-vector", action="store_true", help="Explicitly use the installed embedding model and SQLite vector index; never used by desktop navigation.")
    p_evr.add_argument("--live-agent", action="store_true", help="Run and score one fresh local-model continuation answer; opt-in and unloads the model afterward.")
    p_evr.add_argument("--model", default="qwen3:8b", help="Installed Ollama model for --live-agent; models are never downloaded automatically.")
    p_evr.set_defaults(fn=cmd_eval_resumption)

    p_evlab = sub.add_parser("eval-lab", help="Run academic memory evaluations (LongMemEval, MemoryAgentBench, Ablations).")
    p_evlab.add_argument("action", nargs="?", default="run", choices=["run", "ablate"], help="Action to perform (run or ablate)")
    p_evlab.add_argument("--suite", choices=["all", "longmemeval", "agentbench", "continuation"], default="all", help="Evaluation suite to run")
    p_evlab.add_argument("--no-export", action="store_true", help="Do not write JSON report")
    p_evlab.add_argument("--live", action="store_true", help="Evaluate live ~/memories instead of sandbox")
    p_evlab.set_defaults(fn=cmd_eval_lab)

    p_fc = sub.add_parser("file-context", help="Pre-edit file risk and gotcha audit for coding agents.")
    p_fc.add_argument("file_path", help="Path of the file to inspect")
    p_fc.add_argument("--project", default=None, help="Optional project identifier")
    p_fc.set_defaults(fn=cmd_file_context)

    p_le = sub.add_parser("learn-error", help="Crystallize a terminal/test/compiler error trace into a procedural lesson.")
    p_le.add_argument("error_trace", help="Raw terminal error trace or traceback")
    p_le.add_argument("--command", default=None, help="Command that failed")
    p_le.add_argument("--resolution", default=None, help="Recommended fix or explanation")
    p_le.add_argument("--project", default=None, help="Optional project identifier")
    p_le.add_argument("--agent", default="developer", help="Agent identifier")
    p_le.set_defaults(fn=cmd_learn_error)

    p_cm = sub.add_parser("core-memory", help="MemGPT/Letta SOTA: Manage agent core memory blocks (persona, human, scratchpad).")
    cm_sub = p_cm.add_subparsers(dest="action", required=False)
    p_cm_get = cm_sub.add_parser("get", help="Get core memory blocks")
    p_cm_get.set_defaults(action="get")
    p_cm_app = cm_sub.add_parser("append", help="Append to a core memory block")
    p_cm_app.add_argument("block", choices=["persona", "human", "scratchpad"], help="Target core memory block")
    p_cm_app.add_argument("content", help="Text content to append")
    p_cm_app.add_argument("--agent", default="developer", help="Agent identifier")
    p_cm_app.set_defaults(action="append")
    p_cm_rep = cm_sub.add_parser("replace", help="Replace content in a core memory block")
    p_cm_rep.add_argument("block", choices=["persona", "human", "scratchpad"], help="Target core memory block")
    p_cm_rep.add_argument("new_content", help="Replacement text")
    p_cm_rep.add_argument("--old-content", default="", help="Optional substring to replace")
    p_cm_rep.add_argument("--agent", default="developer", help="Agent identifier")
    p_cm_rep.set_defaults(action="replace")
    p_cm.set_defaults(fn=cmd_core_memory)

    p_gc = sub.add_parser("graph-communities", help="Microsoft GraphRAG SOTA: Detect modular entity communities using Louvain clustering.")
    p_gc.set_defaults(fn=cmd_graph_communities)

    p_ref = sub.add_parser("reflect", help="Stanford Generative Agents SOTA: Synthesize reflective insights across recent episodic milestones.")
    p_ref.set_defaults(fn=cmd_reflect)

    p_trap = sub.add_parser("trap", help="Frontier Invention: Manage prospective attention traps (create, list, eval, dismiss).")
    trap_sub = p_trap.add_subparsers(dest="action", required=False)
    p_trap_create = trap_sub.add_parser("create", help="Create a prospective attention trap")
    p_trap_create.add_argument("name", help="Trap name")
    p_trap_create.add_argument("pattern", help="Match pattern / regex")
    p_trap_create.add_argument("payload", help="Directive / alert payload")
    p_trap_create.add_argument("--type", dest="trigger_type", default="keyword", help="Trigger type (file_path, command, keyword)")
    p_trap_create.add_argument("--recurring", action="store_true", help="Keep active across multiple matches")
    p_trap_create.add_argument("--agent", default="developer", help="Agent identifier")
    p_trap_create.set_defaults(action="create")

    p_trap_list = trap_sub.add_parser("list", help="List prospective attention traps")
    p_trap_list.add_argument("--active-only", action="store_true", help="Filter active only")
    p_trap_list.set_defaults(action="list")

    p_trap_eval = trap_sub.add_parser("eval", help="Evaluate context against active traps")
    p_trap_eval.add_argument("context", help="Text/command/file to evaluate")
    p_trap_eval.set_defaults(action="eval")

    p_trap_dismiss = trap_sub.add_parser("dismiss", help="Dismiss/disarm a trap")
    p_trap_dismiss.add_argument("name", help="Trap name to disarm")
    p_trap_dismiss.set_defaults(action="dismiss")
    p_trap.set_defaults(fn=cmd_trap)

    p_pref = sub.add_parser("prefetch", help="Frontier Invention: Anticipatory cognitive branch predictor prefetching active traps, prior regrets, and invariants.")
    p_pref.add_argument("--file", dest="active_file", default="", help="Active file path")
    p_pref.add_argument("--intent", default="", help="Pending command or action goal")
    p_pref.add_argument("--project", default="", help="Project identifier")
    p_pref.set_defaults(fn=cmd_speculative_prefetch)

    p_grd = sub.add_parser("guard", help="Frontier Invention: Run deterministic programmatic memory validation assertions.")
    p_grd.add_argument("guard_name", help="Guard name (schema_keys, budget_limit, sqlite_concurrency, custom)")
    p_grd.add_argument("--context", default="", help="JSON string representing runtime context")
    p_grd.add_argument("--required-keys", default="", help="Comma-separated required keys")
    p_grd.add_argument("--max-chars", type=int, default=4000, help="Max character budget")
    p_grd.add_argument("--condition", action="store_true", help="Boolean condition for custom assertion")
    p_grd.add_argument("--reason", default="CLI guard verification", help="Reason or rule description")
    p_grd.set_defaults(fn=cmd_programmatic_guard)

    p_stale = sub.add_parser("staleness", help="Open Research (STALE): Verify whether physical files bound to memory have mutated.")
    p_stale.add_argument("file_path", nargs="?", default="", help="File path to check")
    p_stale.add_argument("--stored-hash", default="", help="Recorded hash from memory creation time")
    p_stale.add_argument("--key", default="", help="Semantic fact key with file metadata")
    p_stale.set_defaults(fn=cmd_staleness_verify)

    p_cr = sub.add_parser("causal-recall", help="Open Research (Episodic Missing Piece): Retrieve memories with causal outcome polarity gating.")
    p_cr.add_argument("query", nargs="?", default="", help="Search query")
    p_cr.add_argument("--outcome", default="resolved_fix", choices=["resolved_fix", "failed_attempt", "observation", "any"], help="Filter by outcome polarity")
    p_cr.add_argument("--limit", type=int, default=5, help="Result limit")
    p_cr.set_defaults(fn=cmd_causal_recall)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
