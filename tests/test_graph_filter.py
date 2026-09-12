import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Add tools directory to sys.path
tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import gms_desktop_api
import memory_mcp_server


class TestGraphFilterAndEvidence(unittest.TestCase):
    def setUp(self):
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        self.old_mcp_db = memory_mcp_server.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)
        (self.mem_root / "semantic").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "operational").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "procedural").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "episodic" / "history").mkdir(parents=True, exist_ok=True)

        memory_mcp_server.MEM_ROOT = self.mem_root
        memory_mcp_server.DB_PATH = self.mem_root / "gms_trust.sqlite"
        memory_mcp_server.init_db()

        self.api = gms_desktop_api.GMSDesktopAPI(mem_root=self.mem_root)

        # Seed rich graph:
        # Node 1: infra.minipc (INFRA)
        # Node 2: AlphaOS (AGENT)
        # Node 3: qwen2.5:7b (MODEL)
        # Node 4: Isolated Node (CONCEPT)
        # Node 5: http://example.com/long/url/literal/value/test (literal-like)
        memory_mcp_server.tool_mem_upsert_entity({
            "name": "infra.minipc", "entity_type": "INFRA", "summary": "Local compute cluster node"
        })
        memory_mcp_server.tool_mem_upsert_entity({
            "name": "AlphaOS", "entity_type": "AGENT", "summary": "Autonomous trading system"
        })
        memory_mcp_server.tool_mem_upsert_entity({
            "name": "qwen2.5:7b", "entity_type": "MODEL", "summary": "Local Ollama reasoning model"
        })
        memory_mcp_server.tool_mem_upsert_entity({
            "name": "Isolated Node", "entity_type": "CONCEPT", "summary": "An isolated idea"
        })
        memory_mcp_server.tool_mem_upsert_entity({
            "name": "https://api.github.com/repos/mihir/long-url-literal",
            "entity_type": "CONCEPT",
            "summary": "Literal URL"
        })

        # Relationships
        # AlphaOS runs_on infra.minipc
        # AlphaOS uses qwen2.5:7b
        memory_mcp_server.record_graph_relationship("AlphaOS", "runs_on", "infra.minipc")
        memory_mcp_server.record_graph_relationship("AlphaOS", "uses", "qwen2.5:7b")

        # Record a claim for AlphaOS
        memory_mcp_server.tool_mem_save_typed({
            "key": "trading.alphaos",
            "value": json.dumps({"status": "active", "risk_cap": 0.05}),
            "kind": "semantic",
            "agent": "AlphaOS"
        })

    def tearDown(self):
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        memory_mcp_server.DB_PATH = self.old_mcp_db
        self.temp_dir.cleanup()

    def test_enriched_graph_data(self):
        graph = self.api.get_graph_data()
        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)
        self.assertIn("facets", graph)
        self.assertIn("totals", graph)

        # Totals
        self.assertEqual(graph["totals"]["nodes"], 5)
        self.assertEqual(graph["totals"]["edges"], 2)

        # Facets
        self.assertIn("types", graph["facets"])
        self.assertIn("predicates", graph["facets"])
        self.assertEqual(graph["facets"]["predicates"]["runs_on"], 1)
        self.assertEqual(graph["facets"]["predicates"]["uses"], 1)
        self.assertEqual(graph["facets"]["types"]["INFRA"], 1)
        self.assertEqual(graph["facets"]["types"]["AGENT"], 1)

        # Nodes degrees and literal-like classification
        nodes_by_label = {n["label"]: n for n in graph["nodes"]}
        alpha = nodes_by_label["AlphaOS"]
        self.assertEqual(alpha["active_degree"], 2)
        self.assertFalse(alpha["literal_like"])

        literal_node = nodes_by_label["https://api.github.com/repos/mihir/long-url-literal"]
        self.assertTrue(literal_node["literal_like"])

        isolated = nodes_by_label["Isolated Node"]
        self.assertEqual(isolated["active_degree"], 0)

    def test_entity_evidence(self):
        graph = self.api.get_graph_data()
        alpha_node = next(n for n in graph["nodes"] if n["label"] == "AlphaOS")
        evidence = self.api.get_entity_evidence(alpha_node["id"])

        self.assertTrue(evidence["found"])
        self.assertEqual(evidence["name"], "AlphaOS")
        self.assertEqual(evidence["type"], "AGENT")
        self.assertGreaterEqual(evidence["active_relationships_count"], 2)
        self.assertIn("relationships", evidence)
        self.assertIn("quality_status", evidence)

    def test_relationship_evidence(self):
        graph = self.api.get_graph_data()
        self.assertGreaterEqual(len(graph["edges"]), 1)
        edge = graph["edges"][0]

        rel_ev = self.api.get_relationship_evidence(edge["id"])
        self.assertTrue(rel_ev["found"])
        self.assertEqual(rel_ev["predicate"], edge["label"])
        self.assertIn("timeline", rel_ev)
        self.assertIn("subject", rel_ev)
        self.assertIn("object", rel_ev)

    def test_entity_duplicates(self):
        # Insert duplicate variations
        memory_mcp_server.tool_mem_upsert_entity({"name": "mini-pc", "entity_type": "INFRA", "summary": "Mini PC dash"})
        memory_mcp_server.tool_mem_upsert_entity({"name": "Mini PC", "entity_type": "INFRA", "summary": "Mini PC space"})

        dups = self.api.get_entity_duplicates()
        self.assertIsInstance(dups, list)
        self.assertGreaterEqual(len(dups), 1)
        # Check reasons
        reasons = [d["reason"] for d in dups]
        self.assertTrue(any("Normalized" in r or "Exact" in r for r in reasons))

    def test_pure_graph_filter_via_node(self):
        js_test = """
        const GraphFilter = require('./desktop/src/graph_filter.js');
        const rawGraph = {
          nodes: [
            { id: 1, label: 'AlphaOS', type: 'AGENT' },
            { id: 2, label: 'infra.minipc', type: 'INFRA' },
            { id: 3, label: 'qwen2.5:7b', type: 'MODEL' },
            { id: 4, label: 'Isolate', type: 'CONCEPT' },
            { id: 5, label: 'https://literal.example.com/very/long/url', type: 'CONCEPT', literal_like: true }
          ],
          edges: [
            { id: 101, from: 1, to: 2, label: 'runs_on', active: true },
            { id: 102, from: 1, to: 3, label: 'uses', active: true }
          ]
        };

        // Test 1: Min connections 2 (Default)
        // AlphaOS has 2 connections -> passes. Node 2 and 3 each have 1 connection -> degree < 2.
        // Wait: If node 2 and 3 are filtered out by degree >= 2, their edges with AlphaOS drop, so only nodes with >= 2 pass.
        // When minConnections = 1, nodes 1, 2, 3 pass; node 4 and 5 are isolates -> filtered by hideIsolates.
        const resMin1 = GraphFilter.filterGraph(rawGraph, { minConnections: 1, hideIsolates: true });
        if (resMin1.nodes.length !== 3) {
          console.error('Failed test 1: expected 3 nodes, got ' + resMin1.nodes.length);
          process.exit(1);
        }

        // Test 2: Hide isolates = false, minConnections = 0
        const resAll = GraphFilter.filterGraph(rawGraph, { minConnections: 0, hideIsolates: false });
        if (resAll.nodes.length !== 5) {
          console.error('Failed test 2: expected 5 nodes, got ' + resAll.nodes.length);
          process.exit(1);
        }

        // Test 3: Search reveal for low-degree / isolated node
        const resReveal = GraphFilter.filterGraph(rawGraph, { minConnections: 2, focusNodeId: 4, forceRevealFocus: true });
        const revealed = resReveal.nodes.find(n => n.id === 4);
        if (!revealed || !revealed.revealed) {
          console.error('Failed test 3: node 4 should be revealed');
          process.exit(1);
        }

        // Test 4: Type filter (only INFRA)
        const resType = GraphFilter.filterGraph(rawGraph, { minConnections: 0, hideIsolates: false, selectedTypes: ['INFRA'] });
        if (resType.nodes.length !== 1 || resType.nodes[0].label !== 'infra.minipc') {
          console.error('Failed test 4: type filter failed');
          process.exit(1);
        }

        console.log('ALL_JS_TESTS_PASSED');
        """
        res = subprocess.run(["node", "-e", js_test], cwd=str(Path(__file__).parent.parent), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"JS test failed: {res.stderr}\n{res.stdout}")
        self.assertIn("ALL_JS_TESTS_PASSED", res.stdout)


if __name__ == "__main__":
    unittest.main()
