#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
import math
import subprocess
from typing import Dict, List, Tuple
from urllib import request

MEM_ROOT = Path(os.environ.get("MEMORY_ROOT", "/home/mihir/memories"))
INDEX_ROOT = MEM_ROOT / "episodic" / "index"
DEFAULT_EMBED_MODEL = os.environ.get("MEMORY_EMBED_MODEL", "qwen3-embedding:0.6b")
OLLAMA_EMBED_URL = os.environ.get("OLLAMA_EMBED_URL", "http://127.0.0.1:11434/api/embeddings")
EMBED_TIMEOUT_SEC = int(os.environ.get("MEMORY_EMBED_TIMEOUT_SEC", "180"))
EMBED_RETRIES = int(os.environ.get("MEMORY_EMBED_RETRIES", "3"))


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
    history_daily = datetime.now().strftime("%Y-%m-%d")
    daily = MEM_ROOT / "episodic" / "history" / f"{history_daily}.md"
    journal = MEM_ROOT / "episodic" / "journal.md"
    episodic = daily if daily.exists() else journal

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
    if not daily.exists():
        daily = MEM_ROOT / "episodic" / "journal.md"

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
    json_path = MEM_ROOT / "semantic" / "facts.json"
    _json_update(json_path, args.key, args.value)
    print(f"updated: {json_path}")
    return 0


def cmd_index_build(args: argparse.Namespace) -> int:
    import numpy as np
    import faiss

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
    mat = np.array(vectors, dtype=np.float32)
    faiss.normalize_L2(mat)
    index = faiss.IndexFlatIP(mat.shape[1])
    index.add(mat)

    INDEX_ROOT.mkdir(parents=True, exist_ok=True)
    idx_path = INDEX_ROOT / "episodic.faiss"
    meta_path = INDEX_ROOT / "episodic_meta.json"
    faiss.write_index(index, str(idx_path))
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"built: {idx_path}")
    print(f"meta:  {meta_path}")
    print(f"docs={len(docs)} chunks={len(texts)} dim={mat.shape[1]} model={args.model}")
    return 0


def cmd_index_query(args: argparse.Namespace) -> int:
    import numpy as np
    import faiss

    idx_path = INDEX_ROOT / "episodic.faiss"
    meta_path = INDEX_ROOT / "episodic_meta.json"
    if not idx_path.exists() or not meta_path.exists():
        print("index missing: run index-build first")
        return 1

    meta = json.loads(meta_path.read_text())
    index = faiss.read_index(str(idx_path))
    qvec = np.array([_embed(args.query, args.model)], dtype=np.float32)
    faiss.normalize_L2(qvec)
    
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
                
        # Query a larger candidate pool from FAISS
        search_k = min(len(meta), 100)
        scores, ids = index.search(qvec, search_k)
        vector_rank_map = {}
        vector_score_map = {}
        for rank, doc_id in enumerate(ids[0], 1):
            if doc_id >= 0:
                vector_rank_map[int(doc_id)] = rank
                vector_score_map[int(doc_id)] = float(scores[0][rank-1])
                
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
        # Fallback: Vector-Only Search with Decay and Boost
        search_k = max(args.k * 3, 20)
        scores, ids = index.search(qvec, search_k)
        for rank, doc_id in enumerate(ids[0], 1):
            if doc_id < 0:
                continue
            row = meta[int(doc_id)]
            
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
                    
            final_score = float(scores[0][rank-1] * decay_factor * boost_factor)
            reranked.append({
                "doc_id": doc_id,
                "row": row,
                "rrf_score": None,
                "rank_vec": rank,
                "rank_bm25": None,
                "raw_score": float(scores[0][rank-1]),
                "decay_factor": decay_factor,
                "days_ago": days_ago,
                "boost_factor": boost_factor,
                "branch_matched": branch_matched,
                "final_score": final_score
            })

    # Sort descending by final score
    reranked.sort(key=lambda x: x["final_score"], reverse=True)
    
    # Print top k
    for rank, item in enumerate(reranked[:args.k], 1):
        row = item["row"]
        snippet = row["text"].replace("\n", " ")
        if len(snippet) > 180:
            snippet = snippet[:180] + "..."
            
        details = []
        if item["rrf_score"] is not None:
            details.append(f"rrf={item['rrf_score']:.4f}")
            v_rank = "n/a" if item["rank_vec"] == 1000 else str(item["rank_vec"])
            k_rank = "n/a" if item["rank_bm25"] == 1000 else str(item["rank_bm25"])
            details.append(f"ranks=[v:{v_rank}, k:{k_rank}]")
        else:
            details.append(f"raw={item['raw_score']:.4f}")
            
        if not args.no_decay:
            details.append(f"decay={item['decay_factor']:.3f} ({item['days_ago']}d ago)")
        if active_branch:
            details.append(f"boost={item['boost_factor']:.2f}" + (" (branch match)" if item['branch_matched'] else ""))
            
        details_str = f" ({', '.join(details)})" if details else ""
        print(f"{rank}. score={item['final_score']:.4f}{details_str} src={row['source']} chunk={row['chunk']}")
        print(f"   {snippet}")
        
    return 0


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

    p5 = sub.add_parser("index-build", help="Build FAISS episodic index using Ollama embeddings.")
    p5.add_argument("--model", default=DEFAULT_EMBED_MODEL)
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

    p10 = sub.add_parser("claims-list", help="List all recorded claims in the versioned claim ledger.")
    p10.add_argument("--kind", help="Filter by memory kind.")
    p10.add_argument("--key", help="Filter by memory key.")
    p10.add_argument("--status", help="Filter by claim status.")
    p10.set_defaults(fn=cmd_claims_list)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
