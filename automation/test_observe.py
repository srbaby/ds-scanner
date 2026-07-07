#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import unittest

import observe


def j(data):
    return json.dumps(data, ensure_ascii=False)


class ObserveTests(unittest.TestCase):
    def setUp(self):
        self.old_quotes = observe.fetch_sina_quotes
        self.old_index = observe.fetch_csindex_close
        observe.fetch_sina_quotes = lambda symbols: {
            symbol: {"price": 2.2 if symbol == "sh588800" else 1.0, "source": "test"}
            for symbol in symbols
            if symbol
        }
        observe.fetch_csindex_close = lambda code, day: 7200.0 if code == "H00300" else 10800.0

    def tearDown(self):
        observe.fetch_sina_quotes = self.old_quotes
        observe.fetch_csindex_close = self.old_index

    def test_first_run_builds_baseline_without_backfill_trade(self):
        files = {
            "holdings.json": j(
                {
                    "cash_available": 180000,
                    "holdings": [
                        {"symbol": "588800", "qty": 10000, "cost": 2.0, "buy_date": "2026-07-01"}
                    ],
                }
            )
        }
        out = observe.observe_once(files, "2026-07-07")
        trades = observe.parse_jsonl(out["trades.jsonl"])
        snapshots = observe.parse_jsonl(out["portfolio_snapshots.jsonl"])
        state = observe.parse_json(out["observer_state.json"], {})

        self.assertEqual(trades, [])
        self.assertEqual(len(snapshots), 1)
        self.assertTrue(state["initialized"])
        self.assertEqual(state["last_holdings"][0]["lot_id"], "sh588800#20260701#01")

    def test_second_run_generates_buy_once(self):
        files = {"holdings.json": j({"cash_available": 200000, "holdings": []})}
        out1 = observe.observe_once(files, "2026-07-07")
        files.update(out1)
        files["holdings.json"] = j(
            {
                "cash_available": 178000,
                "holdings": [
                    {
                        "symbol": "sh588800",
                        "qty": 10000,
                        "cost": 2.0,
                        "buy_date": "2026-07-07",
                        "_lot_id": "sh588800#20260707#01",
                    }
                ],
            }
        )
        files["observer_request.json"] = j(
            {
                "date": "2026-07-07",
                "holdings_canonical": observe.canonical_holdings(json.loads(files["holdings.json"])),
            }
        )

        out2 = observe.observe_once(files, "2026-07-07")
        trades = observe.parse_jsonl(out2["trades.jsonl"])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["action"], "BUY")
        self.assertEqual(trades[0]["confidence"], "high")

        files.update(out2)
        out3 = observe.observe_once(files, "2026-07-07")
        self.assertEqual(len(observe.parse_jsonl(out3["trades.jsonl"])), 1)

    def test_reduction_generates_sell_with_pnl(self):
        state = {
            "initialized": True,
            "last_holdings": [
                {
                    "symbol": "sh588800",
                    "name": "科创100ETF",
                    "qty": 10000,
                    "cost": 2.0,
                    "buy_date": "2026-07-01",
                    "lot_id": "sh588800#20260701#01",
                }
            ],
        }
        files = {
            "observer_state.json": j(state),
            "holdings.json": j(
                {
                    "cash_available": 191000,
                    "holdings": [
                        {
                            "symbol": "sh588800",
                            "qty": 5000,
                            "cost": 2.0,
                            "buy_date": "2026-07-01",
                        }
                    ],
                }
            ),
        }
        out = observe.observe_once(files, "2026-07-08")
        trades = observe.parse_jsonl(out["trades.jsonl"])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["action"], "SELL")
        self.assertEqual(trades[0]["qty"], 5000)
        self.assertGreater(trades[0]["pnl_amount"], 0)

    def test_excess_uses_observation_window(self):
        snapshots = [
            {
                "date": "2026-07-01",
                "total_asset": 183012.0,
                "benchmarks": {
                    "hs300_tr": {"close": 7200.0},
                },
            },
            {
                "date": "2026-07-10",
                "total_asset": 184842.12,
                "benchmarks": {
                    "hs300_tr": {"close": 7200.0},
                },
            },
        ]

        stats = observe.build_stats(snapshots, [], {"initialized": True}, [])
        hs300 = stats["benchmarks"]["hs300"]

        self.assertAlmostEqual(hs300["cumulative_excess_pct"], 1.0, places=4)
        self.assertAlmostEqual(hs300["rolling_3m_excess_pct"], 1.0, places=4)
        self.assertAlmostEqual(stats["summary"]["total_return_pct"], 1.0, places=4)
        self.assertEqual(stats["principal"], 183012.0)
        self.assertEqual(stats["return_base"]["basis"], "right_wheel_observation_start")
        self.assertIn("rolling_3m_window_insufficient", stats["data_quality"]["notes"])
        self.assertIn("return_base_observation_start", stats["data_quality"]["notes"])


    def test_normalize_symbol_corrects_wrong_market_prefix(self):
        self.assertEqual(observe.normalize_symbol("sz588800"), "sh588800")
        self.assertEqual(observe.normalize_symbol("588800"), "sh588800")


if __name__ == "__main__":
    unittest.main()
