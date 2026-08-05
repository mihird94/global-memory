import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import memory_mcp_server
import memoryctl


class TestKnowledgeGraph(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        
        self.old_env = os.environ.get("MEMORY_ROOT")
        os.environ["MEMORY_ROOT"] = str(self.temp_path)
        
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        self.old_db_path = memory_mcp_server.DB_PATH
        self.old_ctl_root = memoryctl.MEM_ROOT
        
        memory_mcp_server.MEM_ROOT = self.temp_path
        memory_mcp_server.DB_PATH = self.temp_path / "gms_trust.sqlite"
        memoryctl.MEM_ROOT = self.temp_path
        
        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "episodic" / "history").mkdir(parents=True, exist_ok=True)
        memory_mcp_server.init_db()

    def tearDown(self):
        if self.old_env is None:
            os.environ.pop("MEMORY_ROOT", None)
        else:
            os.environ["MEMORY_ROOT"] = self.old_env
            
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        memory_mcp_server.DB_PATH = self.old_db_path
        memoryctl.MEM_ROOT = self.old_ctl_root
        self.temp_dir.cleanup()

    def test_triple_extraction_and_graph_recording(self):
        # 1. Test triple extraction
        text = "Optimus depends on AlphaSignal for data feed"
        triples = memory_mcp_server.extract_graph_triples(text)
        self.assertTrue(len(triples) > 0)
        sub, pred, obj = triples[0]
        self.assertEqual(sub, "Optimus")
        self.assertEqual(pred, "depends_on")
        self.assertEqual(obj, "AlphaSignal")

        # 2. Record relationship in graph database
        rel_id = memory_mcp_server.record_graph_relationship(sub, pred, obj)
        self.assertTrue(rel_id > 0)

        # 3. Query graph
        graph_data = memory_mcp_server.query_entity_graph("Optimus", hops=2)
        self.assertTrue(graph_data["found"])
        self.assertEqual(graph_data["node_count"], 2)
        self.assertEqual(graph_data["edge_count"], 1)

        # 4. Format ASCII and Mermaid outputs
        ascii_out = memory_mcp_server.format_ascii_graph(graph_data)
        mermaid_out = memory_mcp_server.format_mermaid_graph(graph_data)
        self.assertIn("Optimus", ascii_out)
        self.assertIn("-->|\"depends_on\"|", mermaid_out)

    def test_lightrag_dual_level_search(self):
        # Seed graph relationship
        memory_mcp_server.record_graph_relationship("Codex", "implemented", "FAISS_Index")
        
        # Test mode="low" (low-level entity triples)
        res_low = memory_mcp_server.tool_mem_search({"query": "Codex", "mode": "low"})
        self.assertIn("LightRAG Low-Level Graph Triples", res_low)
        self.assertIn("FAISS_Index", res_low)

    def test_mcp_graph_tools(self):
        # Test tool_mem_graph_extract
        res_ext = memory_mcp_server.tool_mem_graph_extract({"text": "Antigravity targets Linux Mini PC"})
        self.assertIn("Knowledge Graph extracted", res_ext)

        # Test tool_mem_graph_entities
        res_ents = memory_mcp_server.tool_mem_graph_entities({})
        entities = json.loads(res_ents)
        self.assertTrue(len(entities) > 0)

        # Test tool_mem_graph_query
        res_q = memory_mcp_server.tool_mem_graph_query({"entity": "Antigravity", "format": "mermaid"})
        self.assertIn("```mermaid", res_q)


if __name__ == "__main__":
    unittest.main()
