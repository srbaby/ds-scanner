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
    def test_execution_guidance_rounds_down_to_etf_lots(self):
        guidance = ds_scanner.calculate_execution_guidance(
            193155.64, 10, 2.328
        )
        self.assertEqual(guidance["recommended_shares"], 8200)
        self.assertEqual(guidance["recommended_lots"], 82)
        self.assertEqual(guidance["estimated_amount"], 19089.6)

    def test_target_execution_guidance_sells_all_for_zero_target(self):
        guidance = ds_scanner.calculate_target_execution_guidance(
            total_asset=194432.7,
            current_market_value=50720.0,
            target_position_pct=0,
            reference_price=1.647,
            current_qty=30800,
            action="SELL",
        )
        self.assertEqual(guidance["side"], "SELL")
        self.assertEqual(guidance["recommended_shares"], 30800)
        self.assertEqual(guidance["post_trade_shares"], 0)
        self.assertEqual(guidance["estimated_amount"], 50727.6)

    def test_target_execution_guidance_reduces_to_market_value_target(self):
        guidance = ds_scanner.calculate_target_execution_guidance(
            total_asset=100000,
            current_market_value=20000,
            target_position_pct=15,
            reference_price=10,
            current_qty=2000,
            action="REDUCE",
        )
        self.assertEqual(guidance["side"], "SELL")
        self.assertEqual(guidance["recommended_shares"], 500)
        self.assertEqual(guidance["post_trade_shares"], 1500)

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

    def test_sell_operation_keeps_actual_position_and_full_exit_guidance(self):
        row = signal(grade="无效", total=72)
        holding = {
            "symbol": "588000",
            "name": "测试ETF",
            "qty": 12000,
            "price": 1.0,
            "value": 12000,
            "profit_pct": 6,
            "policy_score": 20,
            "days": 10,
        }
        decision = ds_scanner.build_authoritative_decision([row], [holding], 12000, 88000)
        op = decision["operations"][0]
        self.assertEqual(op["action"], "SELL")
        self.assertEqual(op["current_position_pct"], 12.0)
        self.assertEqual(op["market_value"], 12000)
        self.assertEqual(op["execution_guidance"]["recommended_shares"], 12000)

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

    def test_unpriced_holding_is_reported_not_dropped(self):
        holdings_config = {
            "holdings": [
                {
                    "symbol": "sh588000",
                    "qty": 100,
                    "cost": 1.0,
                    "buy_date": "2026-01-01",
                    "wave_type": "快速波段",
                }
            ]
        }
        # 模拟新浪+腾讯双源都拿不到价（fetch_realtime 已经是新浪+腾讯合并后的结果）。
        with patch.object(ds_scanner, "fetch_realtime", return_value={}):
            holdings_data, wave_cards, total_value, unpriced = (
                ds_scanner.scan_holdings_with_wave_management(
                    holdings_config, {}, {}
                )
            )

        self.assertEqual(holdings_data, [])
        self.assertEqual(unpriced, ["588000"])

        decision = ds_scanner.build_authoritative_decision(
            [], holdings_data, total_value, 100000, unpriced
        )
        self.assertEqual(decision["portfolio"]["health"], "degraded")
        self.assertEqual(decision["portfolio"]["data_gap_holdings"], ["588000"])

    def test_partial_quote_cannot_produce_buy(self):
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
                "change_pct": 5.0,
                "volume": 0,
                "partial": True,
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

        self.assertIn("PARTIAL_QUOTE_NO_VOLUME", rows[0]["data_quality"]["issues"])
        self.assertEqual(rows[0]["signal_grade"], "无效")

        decision = ds_scanner.build_authoritative_decision(rows, [], 0, 100000)
        self.assertFalse(any(op["action"] == "BUY" for op in decision["operations"]))


if __name__ == "__main__":
    unittest.main()
