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

    def test_probe_summary_keeps_last_revision_per_day(self):
        entries = [
            {
                "day": "2026-07-01",
                "version": "v1",
                "committed_at": "2026-07-01T06:00:00Z",
                "holdings_canonical": {"cash_available": 200000, "holdings": []},
            },
            {
                "day": "2026-07-01",
                "version": "v2",
                "committed_at": "2026-07-01T08:00:00Z",
                "holdings_canonical": {
                    "cash_available": 180000,
                    "holdings": [{"symbol": "sh588800", "qty": 10000}],
                },
            },
            {
                "day": "2026-07-02",
                "version": "v3",
                "committed_at": "2026-07-02T08:00:00Z",
                "holdings_canonical": {
                    "cash_available": 191000,
                    "holdings": [{"symbol": "sh588800", "qty": 5000}],
                },
            },
        ]

        summary = observe.summarize_probe_entries(entries)

        self.assertEqual(summary["revision_count"], 3)
        self.assertEqual(summary["distinct_days"], 2)
        self.assertEqual(summary["earliest_version"], "v2")
        self.assertEqual(summary["earliest_holdings"]["holdings"][0]["qty"], 10000)
        self.assertEqual(summary["inferred_trade_event_count"], 2)
        self.assertEqual(summary["inferred_trade_events"][0]["action"], "BUY_OR_ADD")
        self.assertEqual(summary["inferred_trade_events"][1]["action"], "SELL_OR_REDUCE")

    def test_normalize_symbol_corrects_wrong_market_prefix(self):
        self.assertEqual(observe.normalize_symbol("sz588800"), "sh588800")
        self.assertEqual(observe.normalize_symbol("588800"), "sh588800")

    def test_rebuild_history_uses_buy_date_before_first_snapshot(self):
        daily = [
            {
                "day": "2026-05-21",
                "holdings_canonical": {
                    "cash_available": 155535.07,
                    "holdings": [
                        {
                            "symbol": "sh512480",
                            "name": "半导体ETF",
                            "qty": 12900,
                            "cost": 2.13,
                            "buy_date": "2026-05-19",
                        }
                    ],
                },
            },
            {
                "day": "2026-05-25",
                "holdings_canonical": {
                    "cash_available": 169000,
                    "holdings": [
                        {
                            "symbol": "sh512480",
                            "name": "半导体ETF",
                            "qty": 6500,
                            "cost": 2.13,
                            "buy_date": "2026-05-19",
                        }
                    ],
                },
            },
        ]
        price_cache = {"sh512480": {"2026-05-21": 2.2, "2026-05-25": 2.3}}
        index_cache = {
            "H00300": {"2026-05-21": 7000.0, "2026-05-25": 7100.0},
            "H00905": {"2026-05-21": 10000.0, "2026-05-25": 10100.0},
        }

        updates = observe.rebuild_history_outputs(daily, price_cache, index_cache)
        trades = observe.parse_jsonl(updates["trades.jsonl"])
        snapshots = observe.parse_jsonl(updates["portfolio_snapshots.jsonl"])
        stats = observe.parse_json(updates["stats.json"], {})

        self.assertEqual(trades[0]["date"], "2026-05-19")
        self.assertEqual(trades[0]["action"], "BUY")
        self.assertEqual(snapshots[0]["date"], "2026-05-21")
        self.assertEqual(len(trades), 2)
        self.assertTrue(stats["data_quality"]["history_rebuilt"])
        self.assertIn("initial_position_before_first_snapshot", stats["data_quality"]["notes"])


if __name__ == "__main__":
    unittest.main()
