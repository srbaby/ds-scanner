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
        trades = observe.parse_jsonl(out["trades_2026.jsonl"])
        snapshots = observe.parse_jsonl(out["portfolio_snapshots_2026.jsonl"])
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
        files["dashboard.json"] = j(
            {
                "methodology_version": "v3.1",
                "decision": {
                    "operations": [
                        {
                            "id": "OP-01",
                            "action": "BUY",
                            "symbol": "sh588800",
                            "name": "科创100ETF",
                            "current_target_position_pct": 0,
                            "target_position_pct": 10,
                            "adjustment_pct": 10,
                            "rule_code": "B_INITIAL_BUY",
                            "signal_grade": "B",
                            "reason": "普通信号首次建仓至10%",
                            "metrics": {
                                "score": 76,
                                "vol_ratio": 1.3,
                                "ma20_deviation_pct": 2.5,
                                "fund_flow": "💰流入",
                                "relative_hs300_strength_pct": 1.2,
                            },
                        }
                    ]
                },
                "ai": {"text": "【审计结论】\nPASS"},
            }
        )

        out2 = observe.observe_once(files, "2026-07-07")
        trades = observe.parse_jsonl(out2["trades_2026.jsonl"])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["action"], "BUY")
        self.assertEqual(trades[0]["confidence"], "high")
        self.assertEqual(trades[0]["methodology_version"], "v3.1")
        self.assertEqual(trades[0]["rule_code"], "B_INITIAL_BUY")
        self.assertEqual(trades[0]["entry_rule_code"], "B_INITIAL_BUY")
        self.assertEqual(trades[0]["signal_grade"], "B")
        self.assertEqual(trades[0]["target_position_after_pct"], 10)
        self.assertEqual(trades[0]["score"], 76)
        self.assertEqual(trades[0]["vol_ratio"], 1.3)
        self.assertEqual(trades[0]["ma20_deviation_pct"], 2.5)
        self.assertEqual(trades[0]["fund_flow"], "💰流入")
        self.assertEqual(trades[0]["relative_hs300_strength_pct"], 1.2)

        files.update(out2)
        out3 = observe.observe_once(files, "2026-07-07")
        self.assertEqual(len(observe.parse_jsonl(out3["trades_2026.jsonl"])), 1)

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
        trades = observe.parse_jsonl(out["trades_2026.jsonl"])
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

    def test_graduation_a_message_reached_when_excess_hits_line(self):
        snapshots = [
            {"date": "2026-05-21", "total_asset": 100000.0, "benchmarks": {"hs300_tr": {"close": 100.0}}},
            {"date": "2026-07-08", "total_asset": 105300.0, "benchmarks": {"hs300_tr": {"close": 100.0}}},
        ]

        stats = observe.build_stats(snapshots, [], {"initialized": True}, [])
        graduation = stats["graduation"]

        self.assertEqual(graduation["condition_a_progress_pct"], 100)
        self.assertEqual(graduation["status"], "milestone_reached")
        self.assertEqual(graduation["message"], "已达毕业A观察线，触发复盘评估")

    def test_graduation_a_message_observing_before_line(self):
        snapshots = [
            {"date": "2026-05-21", "total_asset": 100000.0, "benchmarks": {"hs300_tr": {"close": 100.0}}},
            {"date": "2026-07-08", "total_asset": 103000.0, "benchmarks": {"hs300_tr": {"close": 100.0}}},
        ]

        stats = observe.build_stats(snapshots, [], {"initialized": True}, [])
        graduation = stats["graduation"]

        self.assertEqual(graduation["condition_a_progress_pct"], 60)
        self.assertEqual(graduation["status"], "observing")
        self.assertEqual(graduation["message"], "未达毕业观察线")


    def test_normalize_symbol_corrects_wrong_market_prefix(self):
        self.assertEqual(observe.normalize_symbol("sz588800"), "sh588800")
        self.assertEqual(observe.normalize_symbol("588800"), "sh588800")

    def test_backfill_sell_breaching_stop_excluded_from_stats(self):
        # -8% 硬止损下不可能出现的 -50% 卖单（回捞反推伪值）应被剔除，
        # 只用可信卖单算胜率/盈亏比；剔除计数进 data_quality。
        trades = [
            {"action": "SELL", "pnl_amount": -21000, "pnl_pct": -50.0, "lot_id": "a", "date": "2026-06-29"},
            {"action": "SELL", "pnl_amount": 2000, "pnl_pct": 9.5, "lot_id": "b", "date": "2026-06-03"},
            {"action": "SELL", "pnl_amount": -1000, "pnl_pct": -6.0, "lot_id": "c", "date": "2026-05-29"},
        ]
        snapshots = [
            {"date": "2026-05-21", "total_asset": 100000.0, "benchmarks": {"hs300_tr": {"close": 100.0}}},
            {"date": "2026-07-07", "total_asset": 114000.0, "benchmarks": {"hs300_tr": {"close": 100.0}}},
        ]
        stats = observe.build_stats(snapshots, trades, {"initialized": True, "history_rebuilt": True}, [])
        s = stats["summary"]
        # 2 可信卖单：1 胜 1 负 → 胜率 50%，盈亏比 2000/1000=2.0；-50% 那笔不计入
        self.assertEqual(s["win_rate_pct"], 50.0)
        self.assertEqual(s["profit_loss_ratio"], 2.0)
        self.assertEqual(stats["data_quality"]["unreliable_backfill_sell_count"], 1)

    def test_execution_event_reason_correction_and_reverse(self):
        events = [
            {
                "event_id": "evt-1",
                "event_type": "BUY",
                "action": "BUY",
                "trade_date": "2026-07-09",
                "symbol": "sh588800",
                "rule_code": "B_INITIAL_BUY",
                "reason_zh": "普通信号建仓",
            },
            {
                "event_id": "evt-2",
                "event_type": "CORRECT_REASON",
                "target_event_id": "evt-1",
                "rule_code": "A_INITIAL_BUY",
                "reason_zh": "强信号建仓",
            },
        ]
        effective = observe.effective_execution_events(events)
        self.assertEqual(len(effective), 1)
        self.assertEqual(effective[0]["rule_code"], "A_INITIAL_BUY")
        self.assertEqual(effective[0]["reason_zh"], "强信号建仓")

        events.append(
            {
                "event_id": "evt-3",
                "event_type": "REVERSE_EVENT",
                "target_event_id": "evt-1",
            }
        )
        self.assertEqual(observe.effective_execution_events(events), [])

    def test_legacy_files_migrate_to_yearly_files_once(self):
        legacy_trade = {
            "trade_id": "t0001",
            "date": "2026-07-01",
            "action": "BUY",
            "symbol": "sh588800",
            "lot_id": "sh588800#20260701#01",
            "qty": 100,
            "price": 2.0,
        }
        legacy_snapshot = {
            "date": "2026-07-01",
            "cash": 100000,
            "positions_mv": 200,
            "total_asset": 100200,
            "benchmarks": {},
        }
        files = {
            "holdings.json": j({"cash_available": 100000, "holdings": []}),
            "trades.jsonl": json.dumps(legacy_trade, ensure_ascii=False) + "\n",
            "portfolio_snapshots.jsonl": json.dumps(legacy_snapshot, ensure_ascii=False) + "\n",
        }
        out = observe.observe_once(files, "2026-07-09")
        trades = observe.parse_jsonl(out["trades_2026.jsonl"])
        manifest = observe.parse_json(out["data_manifest.json"], {})
        self.assertEqual(len(trades), 1)
        self.assertEqual(manifest["files"]["trades_2026.jsonl"]["row_count"], 1)
        self.assertEqual(manifest["legacy_files"]["trades.jsonl"]["status"], "read_only_archive")


if __name__ == "__main__":
    unittest.main()
