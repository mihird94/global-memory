"""Ollama dense embeddings + ONNX cross-encoder reranking with graceful fallback."""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_EMBED_MODEL = "qwen3-embedding:0.6b"
DEFAULT_RERANK_MODEL = "jinaai/jina-reranker-v1-turbo-en"

_RERANKER_CACHE: dict[str, Any] = {}


def ollama_url() -> str:
    return os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_URL).rstrip("/")


def embed_model() -> str:
    return os.environ.get("GM_EMBED_MODEL", DEFAULT_EMBED_MODEL)


def rerank_model() -> str:
    return os.environ.get("GM_RERANK_MODEL", DEFAULT_RERANK_MODEL)


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm > 1e-12:
        return (vec / norm).astype(np.float32)
    return vec.astype(np.float32)


def embed_texts(texts: list[str], timeout: float = 30.0) -> list[np.ndarray] | None:
    """Embed a batch of texts via local Ollama /api/embed. Returns None if offline."""
    if not texts or os.environ.get("GM_NO_EMBED") == "1":
        return None
    # Keep each doc compact for fast, reliable local Ollama batching
    clipped = [t[:2500] for t in texts]
    payload = json.dumps({"model": embed_model(), "input": clipped}).encode("utf-8")
    req = urllib.request.Request(
        f"{ollama_url()}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        embs = data.get("embeddings")
        if not embs or len(embs) != len(clipped):
            return None
        return [_normalize(np.asarray(v, dtype=np.float32)) for v in embs]
    except Exception:
        return None


def embed_query(query: str, timeout: float = 3.0) -> np.ndarray | None:
    res = embed_texts([query], timeout=timeout)
    return res[0] if res else None


def ollama_available() -> bool:
    if os.environ.get("GM_NO_EMBED") == "1":
        return False
    try:
        req = urllib.request.Request(f"{ollama_url()}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name", "") for m in data.get("models", [])]
        target = embed_model()
        return any(m == target or m.startswith(target.split(":")[0]) for m in models)
    except Exception:
        return False


def _get_reranker(cache_dir: Path) -> Any | None:
    if os.environ.get("GM_NO_RERANK") == "1":
        return None
    model = rerank_model()
    key = f"{cache_dir}:{model}"
    if key in _RERANKER_CACHE:
        return _RERANKER_CACHE[key]
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        cache_dir.mkdir(parents=True, exist_ok=True)
        enc = TextCrossEncoder(model_name=model, cache_dir=str(cache_dir))
        _RERANKER_CACHE[key] = enc
        return enc
    except Exception:
        return None


def rerank_candidates(
    query: str,
    documents: list[str],
    cache_dir: Path,
) -> list[float] | None:
    """Return sigmoid-normalized ONNX cross-encoder scores in (0, 1), or None on fallback."""
    if not documents:
        return []
    enc = _get_reranker(cache_dir)
    if enc is None:
        return None
    try:
        raw_scores = list(enc.rerank(query, documents))
        # Apply sigmoid so logits map cleanly to (0, 1)
        return [1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, float(s))))) for s in raw_scores]
    except Exception:
        return None


def vec_to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
