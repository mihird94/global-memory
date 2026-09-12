import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add tools directory to sys.path
tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import concept_enrichment


class TestConceptEnrichment(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "gms_trust.sqlite"
        concept_enrichment.init_concept_tables(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_idempotent_enqueue(self):
        q1 = concept_enrichment.enqueue_concept_source(
            source_kind="daily_note",
            source_ref="2026-09-08.md",
            text="Today we deployed infra.minipc to run AlphaOS.",
            db_path=self.db_path,
        )
        self.assertGreater(q1, 0)

        # Re-enqueuing exact same content should be idempotent (return 0 or existing)
        q2 = concept_enrichment.enqueue_concept_source(
            source_kind="daily_note",
            source_ref="2026-09-08.md",
            text="Today we deployed infra.minipc to run AlphaOS.",
            db_path=self.db_path,
        )
        self.assertEqual(q2, 0)

    def test_lease_batch_and_recovery(self):
        concept_enrichment.enqueue_concept_source(
            source_kind="session",
            source_ref="session-1",
            text="Session 1 content test excerpt.",
            db_path=self.db_path,
        )

        # Lease batch
        batch = concept_enrichment.lease_batch(batch_size=5, lease_owner="worker-1", db_path=self.db_path)
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["source_ref"], "session-1")
        self.assertEqual(batch[0]["attempts"], 1)

        # Immediate second lease should find nothing pending
        empty_batch = concept_enrichment.lease_batch(batch_size=5, lease_owner="worker-2", db_path=self.db_path)
        self.assertEqual(len(empty_batch), 0)

        # Recover expired leases with 0 timeout (immediate expire)
        recovered = concept_enrichment.recover_expired_leases(timeout_minutes=-1, db_path=self.db_path)
        self.assertEqual(recovered, 1)

        # Re-lease should now succeed
        re_batch = concept_enrichment.lease_batch(batch_size=5, lease_owner="worker-3", db_path=self.db_path)
        self.assertEqual(len(re_batch), 1)
        self.assertEqual(re_batch[0]["attempts"], 2)

    def test_structured_output_validation_and_evidence_quote(self):
        source_text = "The mini pc cluster runs AlphaOS to execute swing trades."

        # Valid payload matching source excerpt
        valid_payload = {
            "schema_version": "concept-enrichment-v1",
            "entities": [
                {
                    "surface_form": "mini pc",
                    "canonical_name": "infra.minipc",
                    "entity_type": "INFRA",
                    "summary": "Local cluster node",
                    "aliases": ["mini pc"],
                    "evidence_quote": "mini pc cluster",
                    "evidence_strength": "explicit",
                    "action": "review"
                }
            ],
            "relationships": [
                {
                    "subject": "infra.minipc",
                    "predicate": "runs",
                    "object": "AlphaOS",
                    "evidence_quote": "runs AlphaOS",
                    "evidence_strength": "explicit",
                    "action": "review"
                }
            ]
        }

        is_valid, err, cleaned = concept_enrichment.validate_enrichment_output(valid_payload, source_text)
        self.assertTrue(is_valid)
        self.assertEqual(len(cleaned["entities"]), 1)
        self.assertEqual(len(cleaned["relationships"]), 1)

        # Fabricated quote should be filtered out
        fabricated_payload = {
            "schema_version": "concept-enrichment-v1",
            "entities": [
                {
                    "surface_form": "Quantum Computer",
                    "canonical_name": "quantum.node",
                    "entity_type": "INFRA",
                    "summary": "Fabricated quantum device",
                    "evidence_quote": "This string does not exist in source text anywhere",
                }
            ],
            "relationships": []
        }
        is_val2, err2, cleaned2 = concept_enrichment.validate_enrichment_output(fabricated_payload, source_text)
        self.assertTrue(is_val2)
        self.assertEqual(len(cleaned2["entities"]), 0)  # Dropped because quote not in source

    def test_batch_processing_with_mock_llm(self):
        concept_enrichment.enqueue_concept_source(
            source_kind="daily_note",
            source_ref="2026-09-08.md",
            text="Deployed infra.minipc to run AlphaOS.",
            db_path=self.db_path,
        )

        def mock_llm(text: str):
            return {
                "schema_version": "concept-enrichment-v1",
                "entities": [
                    {
                        "surface_form": "infra.minipc",
                        "canonical_name": "infra.minipc",
                        "entity_type": "INFRA",
                        "summary": "Local compute cluster node",
                        "evidence_quote": "infra.minipc",
                    }
                ],
                "relationships": [
                    {
                        "subject": "infra.minipc",
                        "predicate": "runs",
                        "object": "AlphaOS",
                        "evidence_quote": "run AlphaOS",
                    }
                ]
            }

        res = concept_enrichment.process_enrichment_batch(
            batch_size=4,
            llm_func=mock_llm,
            db_path=self.db_path,
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["processed"], 1)
        self.assertEqual(res["candidates"], 2)

        status = concept_enrichment.get_enrichment_status(self.db_path)
        self.assertEqual(status["queue_counts"].get("completed", 0), 1)
        self.assertEqual(status["pending_candidates"], 2)


if __name__ == "__main__":
    unittest.main()
