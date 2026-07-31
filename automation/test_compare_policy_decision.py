#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch

from automation.policy_research import compare_policy_decision as compare


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
        ), patch.object(compare.ds_scanner, "scan_market") as scan_market:
            with self.assertRaisesRegex(RuntimeError, "基础分校验失败.*拒绝执行政策对比"):
                compare.run_compare()

        scan_market.assert_not_called()


if __name__ == "__main__":
    unittest.main()
