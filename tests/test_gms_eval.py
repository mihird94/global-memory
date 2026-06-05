import json
import sys
import tempfile
import unittest
from pathlib import Path

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import gms_eval


class TestGMSEvalHarness(unittest.TestCase):
    def test_run_evaluation_reports_all_foundational_scenarios(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = gms_eval.run_evaluation(Path(temp_dir))

        self.assertEqual(report["suite"], "gms_phase8_foundation")
        self.assertEqual(report["summary"]["total"], 4)
        self.assertEqual(report["summary"]["failed"], 0)

        categories = {result["category"] for result in report["results"]}
        self.assertEqual(
            categories,
            {"knowledge_update", "quarantine", "episodic_recall", "abstention"},
        )

    def test_main_emits_machine_readable_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = gms_eval.run_evaluation(Path(temp_dir))

        payload = json.dumps(report)
        parsed = json.loads(payload)
        self.assertEqual(parsed["summary"]["passed"], 4)
        self.assertTrue(all("details" in result for result in parsed["results"]))


if __name__ == "__main__":
    unittest.main()
