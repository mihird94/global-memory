import os
import sys
import unittest
import tempfile
import json
from pathlib import Path

# Add tools directory to sys.path
tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import schemas
import memory_mcp_server


class TestSchemaContracts(unittest.TestCase):
    def test_list_contracts(self):
        contracts = schemas.list_contracts()
        self.assertIn("InfraNodeContract", contracts)
        self.assertIn("TradingSignalContract", contracts)
        self.assertIn("ModelMetadataContract", contracts)
        self.assertIn("OperationalPolicyContract", contracts)
        self.assertIn("ProceduralTaskContract", contracts)

    def test_infra_contract_valid(self):
        valid_payload = {
            "host": "minipc",
            "ip": "100.85.120.45",
            "port": 22,
            "user": "mihir",
            "role": "compute",
            "status": "online"
        }
        is_valid, norm, err = schemas.validate_fact("infra.minipc", valid_payload)
        self.assertTrue(is_valid)
        self.assertIsNone(err)
        self.assertEqual(norm["host"], "minipc")
        self.assertEqual(norm["port"], 22)

    def test_infra_contract_invalid(self):
        invalid_payload = {
            "host": "minipc",
            "port": "not_an_int"
        }
        is_valid, norm, err = schemas.validate_fact("infra.minipc", invalid_payload)
        self.assertFalse(is_valid)
        self.assertIsNotNone(err)
        self.assertIn("port", err)

    def test_trading_contract_valid(self):
        valid_trade = {
            "ticker": "NVDA",
            "action": "buy",
            "price": 140.50,
            "stop_loss": 135.0,
            "target_price": 160.0,
            "timeframe": "swing",
            "thesis": "Earnings breakout",
            "status": "open"
        }
        is_valid, norm, err = schemas.validate_fact("trading.nvda", valid_trade)
        self.assertTrue(is_valid)
        self.assertIsNone(err)
        self.assertEqual(norm["ticker"], "NVDA")
        self.assertEqual(norm["action"], "buy")

    def test_trading_contract_invalid_action(self):
        invalid_trade = {
            "ticker": "NVDA",
            "action": "moon_shot"  # Not a valid action
        }
        is_valid, norm, err = schemas.validate_fact("trading.nvda", invalid_trade)
        self.assertFalse(is_valid)
        self.assertIn("action", err)

    def test_model_metadata_contract(self):
        valid_model = {
            "name": "qwen3:0.6b",
            "context_window": 32768,
            "device": "mps",
            "eval_metric": "MRR",
            "benchmark_score": 0.96
        }
        is_valid, norm, err = schemas.validate_fact("ml.qwen3", valid_model)
        self.assertTrue(is_valid)
        self.assertIsNone(err)
        self.assertEqual(norm["context_window"], 32768)

    def test_untyped_permissive_fallback(self):
        # Keys not matching any registered namespace must be accepted as untyped
        custom_val = "just an arbitrary string note"
        is_valid, norm, err = schemas.validate_fact("custom_random_note", custom_val)
        self.assertTrue(is_valid)
        self.assertIsNone(err)
        self.assertEqual(norm, custom_val)

    def test_mcp_save_typed_schema_rejection(self):
        temp_dir = tempfile.TemporaryDirectory()
        temp_path = Path(temp_dir.name)
        old_root = memory_mcp_server.MEM_ROOT
        old_db = memory_mcp_server.DB_PATH
        memory_mcp_server.MEM_ROOT = temp_path
        memory_mcp_server.DB_PATH = temp_path / "gms_trust.sqlite"
        (temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        memory_mcp_server.init_db()

        try:
            # Bad trade payload should be rejected with schema error
            bad_trade = json.dumps({"ticker": "ADI", "action": "fly_to_mars"})
            res = memory_mcp_server.tool_mem_save_typed({
                "key": "trading.adi",
                "value": bad_trade,
                "agent": "TestAgent"
            })
            self.assertIn("ERROR: Schema validation failed", res)
            self.assertIn("Contract: TradingSignalContract", res)

            # Valid trade payload should be accepted
            good_trade = json.dumps({"ticker": "ADI", "action": "buy", "price": 295.0})
            res2 = memory_mcp_server.tool_mem_save_typed({
                "key": "trading.adi",
                "value": good_trade,
                "agent": "TestAgent"
            })
            self.assertIn("Fact saved", res2)
        finally:
            memory_mcp_server.MEM_ROOT = old_root
            memory_mcp_server.DB_PATH = old_db
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
