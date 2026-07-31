#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest
import json
import os
import sys
import tempfile
from unittest.mock import patch

from automation import generate_dashboard
from automation.policy_research import compare_policy_decision as compare
from automation.policy_research import run_policy_research


class ComparePoolValidationTests(unittest.TestCase):
    def test_run_compare_rejects_polluted_pool_before_market_scan(self):
        polluted_pool = {
            "sh512880": {
                "name": "证券ETF",
                "category": "证券",
                "policy": 8,
                "_breakdown": {"base": 2, "tech": 6, "strength": 0},
            }
        }

        with patch.object(compare, "load_latest_delta", return_value={"as_of": "2026-07-31"}), patch.object(
            compare.ds_scanner, "load_base_scores", return_value={"证券": 3}
        ), patch.object(
            compare.ds_scanner, "load_etf_pool", return_value=polluted_pool
        ), patch.object(
            compare.ds_scanner, "refresh_etf_pool"
        ) as refresh_pool, patch.object(compare.ds_scanner, "scan_market") as scan_market:
            with self.assertRaisesRegex(compare.PollutedEtfPoolError, "基础分校验失败.*拒绝执行政策对比"):
                compare.run_compare()

        refresh_pool.assert_not_called()
        scan_market.assert_not_called()


class PolicyObservationRecoveryTests(unittest.TestCase):
    def test_compare_only_marks_observation_ready(self):
        report = {
            "delta_as_of": "2026-07-31",
            "impact": {"operation_changes": 0, "aggression_index": 0.0},
        }
        with patch.object(sys, "argv", ["run_policy_research.py", "--compare-only"]), patch.object(
            run_policy_research, "run_compare", return_value=report
        ), patch.object(run_policy_research, "_write_observation_status") as write_status, patch.object(
            run_policy_research, "_write_github_output"
        ):
            result = run_policy_research.main()

        self.assertEqual(result, 0)
        write_status.assert_any_call("ready", delta_as_of="2026-07-31")

    def test_polluted_compare_is_deferred_without_action_error(self):
        polluted_error = compare.PollutedEtfPoolError("旧池污染")
        extract = {
            "ai_ok": False,
            "ai_reason": "test",
            "new_event_count": 0,
            "skipped_no_date_count": 0,
        }
        with patch.object(sys, "argv", ["run_policy_research.py", "--skip-collect"]), patch.object(
            run_policy_research, "run_extract", return_value=extract
        ), patch.object(run_policy_research, "run_score", return_value={"themes": {}}), patch.object(
            run_policy_research, "run_compare", side_effect=polluted_error
        ), patch.object(run_policy_research, "_write_observation_status") as write_status, patch.object(
            run_policy_research, "_write_github_output"
        ) as write_output:
            result = run_policy_research.main()

        self.assertEqual(result, 0)
        write_status.assert_any_call("deferred", "旧池污染")
        write_output.assert_any_call("compare_deferred", "true")

    def test_dashboard_rejects_stale_watchlist_when_observation_is_not_ready(self):
        old_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                snapshot_dir = os.path.join("data", "policy_research", "snapshots")
                os.makedirs(snapshot_dir)
                with open(os.path.join(snapshot_dir, "policy_watchlist.json"), "w", encoding="utf-8") as f:
                    json.dump({"generated_at": "2026-07-29", "active_policy_deltas": [{"theme": "旧数据"}]}, f)
                with open(
                    os.path.join(snapshot_dir, "policy_observation_status.json"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump({"status": "deferred", "message": "等待扫描器刷新"}, f)

                result = generate_dashboard.load_policy_research()
        finally:
            os.chdir(old_cwd)

        self.assertFalse(result["ok"])
        self.assertIn("等待扫描器刷新", result["error"])

    def test_dashboard_loads_watchlist_when_observation_is_ready(self):
        old_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                snapshot_dir = os.path.join("data", "policy_research", "snapshots")
                os.makedirs(snapshot_dir)
                with open(os.path.join(snapshot_dir, "policy_watchlist.json"), "w", encoding="utf-8") as f:
                    json.dump({"generated_at": "2026-07-31", "active_policy_deltas": [{"theme": "通信"}]}, f)
                with open(
                    os.path.join(snapshot_dir, "policy_observation_status.json"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump({"status": "ready"}, f)

                result = generate_dashboard.load_policy_research()
        finally:
            os.chdir(old_cwd)

        self.assertTrue(result["ok"])
        self.assertEqual(result["active_policy_deltas"][0]["theme"], "通信")


if __name__ == "__main__":
    unittest.main()
