#!/usr/bin/env python3

import unittest
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd

import ds_scanner


def signal(
    symbol="588000",
    grade="A",
    total=82,
    valid=True,
    deviation=3.0,
    fund_flow="💰流入",
):
    return {
        "symbol": symbol,
        "full_symbol": f"sh{symbol}",
        "name": "测试ETF",
        "price": 1.03,
        "ma20": 1.0,
        "ma20_deviation_pct": deviation,
        "change_pct": 1.5,
        "relative_strength_pct": 1.2,
        "vol_ratio": 1.3,
        "rsi": 60,
        "fund_flow": fund_flow,
        "policy": 20,
        "score": {
            "policy_catalyst": 24,
            "technical": 22,
            "sentiment_strength": 16,
            "risk_reward": 20,
            "total": total,
        },
        "signal_grade": grade,
        "data_quality": {"valid": valid, "issues": [] if valid else ["INVALID_ATR"]},
    }


class ScannerDecisionTests(unittest.TestCase):
    def test_four_dimensional_score_is_bounded_and_sums_to_total(self):
        score = ds_scanner.calculate_four_dimensional_score(
            15, 1.05, 1.0, 5, 1.5, "💰流入", 60, 2, 2, 0.02, 1.08
        )
        self.assertEqual(score["policy_catalyst"], 30)
        self.assertEqual(score["technical"], 25)
        self.assertEqual(score["sentiment_strength"], 20)
        self.assertEqual(
            score["total"],
            score["policy_catalyst"]
            + score["technical"]
            + score["sentiment_strength"]
            + score["risk_reward"],
        )

    def test_atr_uses_true_range(self):
        history = pd.DataFrame(
            {
                "high": [10 + i * 0.1 for i in range(16)],
                "low": [9 + i * 0.1 for i in range(16)],
                "close": [9.5 + i * 0.1 for i in range(16)],
            }
        )
        self.assertGreater(ds_scanner.calculate_atr(history), 0)

    def test_high_score_can_downgrade_from_s_to_a(self):
        row = signal(grade="无效", total=88)
        row["relative_strength_pct"] = 1.1
        row["fund_flow"] = "➖平衡"
        self.assertEqual(ds_scanner.determine_signal_grade(row), "A")

    def test_invalid_data_cannot_receive_signal(self):
        row = signal(total=90, valid=False)
        self.assertEqual(ds_scanner.determine_signal_grade(row), "无效")

    def test_hard_stop_wins_even_when_market_data_is_invalid(self):
        row = signal(valid=False)
        holding = {
            "symbol": "588000",
            "name": "测试ETF",
            "value": 10000,
            "profit_pct": -8.1,
            "policy_score": 20,
            "days": 2,
        }
        decision = ds_scanner.build_authoritative_decision([row], [holding], 10000, 90000)
        self.assertEqual(decision["operations"][0]["rule_code"], "RISK_STOP")
        self.assertEqual(decision["operations"][0]["action"], "SELL")

    def test_data_gap_holds_existing_position_and_blocks_add(self):
        row = signal(valid=False)
        holding = {
            "symbol": "588000",
            "name": "测试ETF",
            "value": 10000,
            "profit_pct": 1,
            "policy_score": 20,
            "days": 2,
        }
        decision = ds_scanner.build_authoritative_decision([row], [holding], 10000, 90000)
        op = decision["operations"][0]
        self.assertEqual(op["rule_code"], "WATCH_DATA_GAP")
        self.assertEqual(op["action"], "HOLD")
        self.assertEqual(op["target_position_pct"], 10)

    def test_new_positions_never_exceed_portfolio_cap(self):
        rows = [
            signal("588000", "S", 90),
            signal("512480", "S", 89),
            signal("515880", "A", 84),
            signal("515120", "A", 83),
        ]
        decision = ds_scanner.build_authoritative_decision(rows, [], 0, 100000)
        self.assertLessEqual(decision["portfolio"]["target_equity_position_pct"], 65)

    def test_time_fail_and_profit_weaken_are_deterministic(self):
        weak = signal(grade="无效", total=72)
        holding = {
            "symbol": "588000",
            "name": "测试ETF",
            "value": 10000,
            "profit_pct": 6,
            "policy_score": 20,
            "days": 10,
        }
        decision = ds_scanner.build_authoritative_decision([weak], [holding], 10000, 90000)
        self.assertEqual(decision["operations"][0]["rule_code"], "PROFIT_WEAKEN")

        holding["days"] = 21
        decision = ds_scanner.build_authoritative_decision([weak], [holding], 10000, 90000)
        self.assertEqual(decision["operations"][0]["rule_code"], "TIME_FAIL")

    def test_switch_out_replaces_weaker_holding_when_cap_is_full(self):
        held_signals = [
            signal("588000", "无效", 78),
            signal("512480", "S", 88),
            signal("515880", "S", 87),
        ]
        holdings = [
            {
                "symbol": row["symbol"],
                "name": row["name"],
                "value": 20000,
                "profit_pct": 1,
                "policy_score": 20,
                "days": 3,
            }
            for row in held_signals
        ]
        newcomer = signal("515120", "S", 90)
        decision = ds_scanner.build_authoritative_decision(
            held_signals + [newcomer], holdings, 60000, 40000
        )
        rules = {op["symbol"]: op["rule_code"] for op in decision["operations"]}
        self.assertEqual(rules["sh588000"], "SWITCH_OUT")
        self.assertEqual(rules["sh515120"], "S_INITIAL_BUY")

    def test_fixed_midday_sample_produces_score_for_every_valid_row(self):
        days = [date.today() - timedelta(days=value) for value in range(30, 0, -1)]
        history = pd.DataFrame(
            {
                "date": days,
                "open": [1 + i * 0.001 for i in range(30)],
                "high": [1.01 + i * 0.001 for i in range(30)],
                "low": [0.99 + i * 0.001 for i in range(30)],
                "close": [1 + i * 0.001 for i in range(30)],
                "volume": [1000] * 30,
            }
        )
        realtime = {
            "sh588000": {
                "price": 1.03,
                "last_close": history.iloc[-1]["close"],
                "change_pct": 1.2,
                "volume": 600,
            }
        }
        pool = {
            "sh588000": {
                "name": "科创50ETF",
                "category": "科技成长",
                "policy": 20,
                "_breakdown": {"base": 12},
            }
        }
        with patch.object(ds_scanner, "fetch_sina_history", return_value=history), patch.object(
            ds_scanner, "calc_volume_time_factor", return_value=2
        ):
            rows = ds_scanner.scan_etf_pool(
                pool, set(), realtime, {"科技成长": 12}, index_change=0
            )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["data_quality"]["valid"])
        self.assertIn("total", rows[0]["score"])


if __name__ == "__main__":
    unittest.main()
