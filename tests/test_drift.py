import argparse
import importlib
import io
import json
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import memoryctl


class _FakeVector:
    def __init__(self, values):
        self.values = [float(v) for v in values]

    def __iter__(self):
        return iter(self.values)

    def __getitem__(self, idx):
        return self.values[idx]

    def __len__(self):
        return len(self.values)

    def tolist(self):
        return list(self.values)


class _FakeMatrix:
    def __init__(self, rows):
        self.rows = [[float(v) for v in row] for row in rows]
        width = len(self.rows[0]) if self.rows else 0
        self.shape = (len(self.rows), width)

    def __iter__(self):
        return iter(self.rows)

    def __getitem__(self, idx):
        if isinstance(idx, tuple):
            row_idx, col_idx = idx
            if isinstance(row_idx, slice):
                selected = self.rows[row_idx]
                return [row[col_idx] for row in selected]
            return self.rows[row_idx][col_idx]
        return self.rows[idx]

    def __setitem__(self, idx, value):
        if isinstance(idx, tuple):
            row_idx, col_idx = idx
            if isinstance(row_idx, slice):
                selected = range(*row_idx.indices(len(self.rows)))
                for offset, row_num in enumerate(selected):
                    self.rows[row_num][col_idx] = value[offset]
                return
            self.rows[row_idx][col_idx] = value
            return
        self.rows[idx] = value

    def tolist(self):
        return [list(row) for row in self.rows]


class _FakeIndex:
    def __init__(self, dim: int):
        self.dim = dim
        self.rows = []

    def add(self, mat):
        self.rows.extend(mat.tolist())


class _FakeFaissModule:
    @staticmethod
    def normalize_L2(mat):
        for row in mat.rows:
            norm = math.sqrt(sum(value * value for value in row))
            if norm == 0.0:
                continue
            for idx, value in enumerate(row):
                row[idx] = value / norm

    @staticmethod
    def IndexFlatIP(dim: int):
        return _FakeIndex(dim)

    @staticmethod
    def write_index(index, path: str):
        Path(path).write_text(json.dumps({"dim": index.dim, "rows": index.rows}))


class _FakeNumpyModule:
    float32 = float

    @staticmethod
    def array(values, dtype=None):
        if values and isinstance(values[0], (list, tuple)):
            return _FakeMatrix(values)
        return _FakeVector(values)


class TestDriftFoundation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_mem_root = memoryctl.MEM_ROOT
        self.old_index_root = memoryctl.INDEX_ROOT
        self.old_drift_root = memoryctl.DRIFT_ROOT
        memoryctl.MEM_ROOT = self.root
        memoryctl.INDEX_ROOT = self.root / "episodic" / "index"
        memoryctl.DRIFT_ROOT = memoryctl.INDEX_ROOT / "drift"
        (self.root / "episodic" / "history").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        memoryctl.MEM_ROOT = self.old_mem_root
        memoryctl.INDEX_ROOT = self.old_index_root
        memoryctl.DRIFT_ROOT = self.old_drift_root
        self.temp_dir.cleanup()

    def _build(self, embeddings, threshold=0.05):
        args = argparse.Namespace(model="test-embed", drift_threshold=threshold)
        docs = [("history/2026-06-04.md", "alpha"), ("history/2026-06-05.md", "beta")]
        fake_faiss = _FakeFaissModule()
        fake_numpy = _FakeNumpyModule()
        with patch.object(memoryctl, "_iter_episodic_texts", return_value=docs), \
             patch.object(memoryctl, "_embed", side_effect=embeddings), \
             patch.dict(sys.modules, {"faiss": fake_faiss, "numpy": fake_numpy}):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = memoryctl.cmd_index_build(args)
        return code, buffer.getvalue()

    def test_index_build_persists_baseline_drift_snapshot(self):
        code, output = self._build([[1.0, 0.0], [1.0, 0.0]])
        self.assertEqual(code, 0)
        self.assertIn("drift_status=baseline", output)

        latest = json.loads((memoryctl.DRIFT_ROOT / "latest.json").read_text())
        status = json.loads((memoryctl.DRIFT_ROOT / "status.json").read_text())
        self.assertEqual(latest["embedding_model"], "test-embed")
        self.assertEqual(latest["vector_count"], 2)
        self.assertEqual(status["status"], "baseline")

    def test_second_build_reports_alert_when_centroid_shifts(self):
        self._build([[1.0, 0.0], [1.0, 0.0]], threshold=0.05)
        code, output = self._build([[0.0, 1.0], [0.0, 1.0]], threshold=0.05)
        self.assertEqual(code, 0)
        self.assertIn("drift_status=alert", output)

        report = memoryctl._read_drift_status(0.05)
        self.assertEqual(report["status"], "alert")
        self.assertGreater(report["drift"]["angular_distance"], 0.05)

    def test_drift_status_reports_missing_without_snapshot(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = memoryctl.cmd_drift_status(argparse.Namespace(threshold=0.05, json=False))
        self.assertEqual(code, 1)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "missing")

    def test_mcp_wrapper_returns_cli_output(self):
        memory_mcp_server = importlib.import_module("memory_mcp_server")
        with patch.object(memory_mcp_server, "_run_memoryctl", return_value=(0, "{\"status\": \"ok\"}")):
            out = memory_mcp_server.tool_mem_drift_status({"threshold": 0.1})
        self.assertIn("\"status\": \"ok\"", out)


if __name__ == "__main__":
    unittest.main()
