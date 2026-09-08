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


def _embed(text: str, model: str) -> List[float]:
    last_err: Exception | None = None
    for attempt in range(1, EMBED_RETRIES + 1):
        try:
            payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
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
    if daily.exists():
        episodic = daily
    elif history_dir.exists() and list(history_dir.glob("*.md")):
        episodic = sorted(history_dir.glob("*.md"))[-1]
    else:
        episodic = MEM_ROOT / "episodic" / "journal.md"

    print(f"[index]\n{idx}\n")
    print(_read(idx)[:2000])
    print(f"\n[preferences]\n{prefs}\n")
    print(_read(prefs)[:2000])
    print(f"\n[projects]\n{projects}\n")
    print(_read(projects)[:2000])
    print(f"\n[lessons]\n{lessons}\n")
    print(_read(lessons)[:2000])
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
    json_path = MEM_ROOT / "semantic" / "facts.json"
    _json_update(json_path, args.key, val_to_save)
    print(f"updated: {json_path}")
    return 0


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
    if not docs:
        print("no episodic docs found")
        return 1

    meta = []
    texts = []
    for src, raw in docs:
        chunks = _chunk_text(raw)
        for i, chunk in enumerate(chunks):
            meta.append({"source": src, "chunk": i, "text": chunk})
            texts.append(chunk)

    vectors = [_embed(t, args.model) for t in texts]

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
                decay_factor = math.exp(-args.decay_rate * days_ago)

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
                decay_factor = math.exp(-args.decay_rate * days_ago)

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
    return _call_memory_tool("mem_task_resume", {"task_id": args.task_id})


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
            triples = memory_mcp_server.extract_graph_triples(f"{key}: {val}")
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
                triples = memory_mcp_server.extract_graph_triples(f"{k}: {v}")
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
        else:
            print(f"[{datetime.now().isoformat()}] GMS DB Backup FAILED: {report.get('message', 'Unknown error')}")
    return 0 if report.get("status") == "success" else 1


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

    p20 = sub.add_parser("task-resume", help="Read a task's latest checkpoint and handoff package.")
    p20.add_argument("task_id")
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

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
