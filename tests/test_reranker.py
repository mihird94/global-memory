import os
import sys
import argparse
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add tools directory to path
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import memoryctl
import memory_mcp_server


def test_get_flashrank_cache_dir_default():
    with patch.dict(os.environ, {}, clear=True):
        cache_dir = memoryctl._get_flashrank_cache_dir()
        assert cache_dir == Path.home() / ".cache" / "flashrank"


def test_get_flashrank_cache_dir_custom():
    custom_path = "/tmp/custom_flashrank_cache"
    with patch.dict(os.environ, {"FLASHRANK_CACHE_DIR": custom_path}):
        cache_dir = memoryctl._get_flashrank_cache_dir()
        assert cache_dir == Path(custom_path)


def test_get_reranker_import_error():
    memoryctl._RERANKER_INSTANCE.clear()
    with patch.dict("sys.modules", {"flashrank": None}):
        ranker = memoryctl._get_reranker("test-model-missing")
        assert ranker is None


def test_get_reranker_singleton_caching():
    memoryctl._RERANKER_INSTANCE.clear()
    mock_module = MagicMock()
    mock_ranker = MagicMock()
    mock_module.Ranker.return_value = mock_ranker
    with patch.dict("sys.modules", {"flashrank": mock_module}):
        r1 = memoryctl._get_reranker("test-model")
        r2 = memoryctl._get_reranker("test-model")
        assert r1 is mock_ranker
        assert r2 is mock_ranker
        assert r1 is r2


def test_index_query_argument_parsing():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    p6 = sub.add_parser("index-query")
    p6.add_argument("query")
    p6.add_argument("-k", type=int, default=5)
    p6.add_argument("--rerank", action="store_true", default=True)
    p6.add_argument("--no-rerank", action="store_true")
    p6.add_argument("--rerank-model", default="ms-marco-TinyBERT-L-2-v2")
    p6.add_argument("--rerank-k", type=int, default=25)

    args = parser.parse_args(["index-query", "test"])
    assert args.rerank is True
    assert args.no_rerank is False
    assert args.rerank_model == "ms-marco-TinyBERT-L-2-v2"
    assert args.rerank_k == 25

    args = parser.parse_args(["index-query", "test", "--no-rerank", "--rerank-model", "custom-model", "--rerank-k", "10"])
    assert args.no_rerank is True
    assert args.rerank_model == "custom-model"
    assert args.rerank_k == 10


def test_tool_mem_search_passes_rerank_args():
    with patch("memory_mcp_server._run_memoryctl", return_value=(0, "mock output")) as mock_run:
        res = memory_mcp_server.tool_mem_search({
            "query": "alphaos workspace",
            "mode": "high",
            "rerank": False,
            "rerank_model": "test-model",
            "rerank_k": 15
        })
        assert "mock output" in res
        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0]
        assert "index-query" in cmd_args
        assert "--no-rerank" in cmd_args
        assert "--rerank-model" in cmd_args
        assert "test-model" in cmd_args
        assert "--rerank-k" in cmd_args
        assert "15" in cmd_args
