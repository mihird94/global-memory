#!/usr/bin/env python3
"""
tests/test_scheduler_telemetry.py — Validate schedule detection and telemetry honesty.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import gms_desktop_api


class TestSchedulerTelemetry(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)
        self.api = gms_desktop_api.GMSDesktopAPI(mem_root=self.mem_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schedule_matches_checked_in_0310_plist(self):
        deploy_plist = Path(__file__).resolve().parent.parent / "deploy" / "com.user.gms-dream-cycle.plist"
        self.assertTrue(deploy_plist.exists(), "deploy plist must exist")
        schedule = self.api.get_effective_launchd_schedule(plist_path=deploy_plist)
        self.assertEqual(schedule, "03:10 AM (Launchd Nightly)")

    def test_schedule_unavailable_when_no_plist(self):
        nonexistent = self.mem_root / "nonexistent.plist"
        schedule = self.api.get_effective_launchd_schedule(plist_path=nonexistent)
        # Should fallback to system/deploy plist if available, or Unavailable
        self.assertIn(schedule, ("03:10 AM (Launchd Nightly)", "Unavailable"))

    def test_get_harvest_status_reports_honest_schedule(self):
        status = self.api.get_harvest_status()
        self.assertNotIn("02:00 AM", status["next_scheduled_run"])
        self.assertIn(status["next_scheduled_run"], ("03:10 AM (Launchd Nightly)", "Unavailable"))

    def test_linux_dream_cycle_units_are_headless_and_model_bounded(self):
        root = Path(__file__).resolve().parent.parent
        service = (root / "deploy" / "gms-dream-cycle.service").read_text()
        timer = (root / "deploy" / "gms-dream-cycle.timer").read_text()
        self.assertIn("OnCalendar=*-*-* 03:10:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("MEMORY_EMBED_MODEL=nomic-embed-text", service)
        self.assertIn("DREAM_LLM_MODEL=qwen3.5:9b", service)
        self.assertIn("CONCEPT_MODEL=qwen3.5:9b", service)
        self.assertIn("CONCEPT_KEEP_ALIVE=0", service)
        self.assertNotIn("desktop", service.lower())
