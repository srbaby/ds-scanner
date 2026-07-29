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


class PolicyDeltaInputTests(unittest.TestCase):
    """政策事件必须真的进四维评分（2026-07-27 前政策跑在扫描器下游，对建议零影响）。"""

    def _delta_file(self, tmpdir, as_of, themes):
        import json
        import os

        path = os.path.join(tmpdir, "last_delta.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"as_of": as_of, "themes": themes}, f)
        return path

    def test_fresh_delta_is_loaded(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._delta_file(
                tmpdir, "2026-07-27", {"证券": {"active_delta": 1}, "煤炭": {"active_delta": 0}}
            )
            with patch.object(ds_scanner, "POLICY_DELTA_FILE", path):
                state = ds_scanner.load_policy_deltas(today=date(2026, 7, 27))
        self.assertTrue(state["ok"])
        self.assertEqual(state["deltas"], {"证券": 1})

    def test_stale_delta_is_rejected_with_reason(self):
        """政策流水线在 scan.yml 里是 continue-on-error，挂了不能拿旧数据顶。"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._delta_file(tmpdir, "2026-07-01", {"证券": {"active_delta": 2}})
            with patch.object(ds_scanner, "POLICY_DELTA_FILE", path):
                state = ds_scanner.load_policy_deltas(today=date(2026, 7, 27))
        self.assertFalse(state["ok"])
        self.assertEqual(state["deltas"], {})
        self.assertIn("过期", state["reason"])

    def test_missing_delta_file_degrades_without_raising(self):
        with patch.object(ds_scanner, "POLICY_DELTA_FILE", "/nonexistent/last_delta.json"):
            state = ds_scanner.load_policy_deltas(today=date(2026, 7, 27))
        self.assertFalse(state["ok"])
        self.assertEqual(state["deltas"], {})

    def test_all_sources_failed_is_refused_not_read_as_no_news(self):
        """全源采集失败时 themes 是一片空 delta，与"今天没新政策"同形，必须拦下。"""
        import json
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "last_delta.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "as_of": "2026-07-29",
                        "event_count": 0,
                        "source_health": {
                            "source_total": 15,
                            "error_count": 15,
                            "all_sources_failed": True,
                        },
                        "themes": {"证券": {"active_delta": 0}},
                    },
                    f,
                )
            with patch.object(ds_scanner, "POLICY_DELTA_FILE", path):
                state = ds_scanner.load_policy_deltas(today=date(2026, 7, 29))
        self.assertFalse(state["ok"])
        self.assertIn("全部采集失败", state["reason"])
        self.assertIn("15/15", state["reason"])

    def test_zero_events_with_healthy_sources_stays_ok(self):
        """采集正常但今天确实没有政策事件——这是常态，不该报警。"""
        import json
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "last_delta.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "as_of": "2026-07-29",
                        "event_count": 0,
                        "source_health": {
                            "source_total": 15,
                            "error_count": 0,
                            "all_sources_failed": False,
                        },
                        "themes": {"证券": {"active_delta": 0}},
                    },
                    f,
                )
            with patch.object(ds_scanner, "POLICY_DELTA_FILE", path):
                state = ds_scanner.load_policy_deltas(today=date(2026, 7, 29))
        self.assertTrue(state["ok"])
        self.assertEqual(state["deltas"], {})

    def test_delta_without_source_health_still_loads(self):
        """向后兼容：上一版 score 写的 last_delta.json 没有 source_health，不能因此判死。"""
        import json
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "last_delta.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"as_of": "2026-07-29", "themes": {"证券": {"active_delta": 1}}}, f)
            with patch.object(ds_scanner, "POLICY_DELTA_FILE", path):
                state = ds_scanner.load_policy_deltas(today=date(2026, 7, 29))
        self.assertTrue(state["ok"])
        self.assertEqual(state["deltas"], {"证券": 1})

    def test_delta_is_clamped_into_base_range(self):
        adjusted, applied = ds_scanner.apply_policy_deltas(
            {"证券": 8, "半导体": 15, "煤炭": 0, "_meta": "忽略"},
            {"证券": 1, "半导体": 2, "煤炭": -2},
        )
        self.assertEqual(adjusted["证券"], 9)
        self.assertEqual(adjusted["半导体"], 15)  # 已到上限，加不上去
        self.assertEqual(adjusted["煤炭"], 0)  # 已到下限，减不下去
        # 实际生效量是夹紧之后的差值，base_score - applied 必须能还原原值
        self.assertEqual(applied, {"证券": 1})

    def test_policy_delta_moves_the_four_dimensional_score(self):
        days = [date.today() - timedelta(days=value) for value in range(30, 0, -1)]
        history = pd.DataFrame(
            {
                "date": days,
                "open": [1 + i * 0.001 for i in range(30)],
                "high": [1.01 + i * 0.001 for i in range(30)],
                "low": [0.99 + i * 0.001 for i in range(30)],
                "close": [1 + i * 0.001 for i in range(30)],
                "volume": [1000.0] * 30,
            }
        )
        realtime = {
            "sh512880": {
                "price": 1.05,
                "last_close": 1.029,
                "change_pct": 2.0,
                "volume": 1500,
            }
        }
        pool = {
            "sh512880": {
                "name": "证券ETF",
                "category": "证券",
                "policy": 20,
                "_breakdown": {"base": 8},
            }
        }

        def scan(base_scores, deltas):
            with patch.object(ds_scanner, "fetch_sina_history", return_value=history):
                return ds_scanner.scan_etf_pool(
                    pool, set(), realtime, base_scores, 0.5, deltas
                )[0]

        plain = scan({"证券": 8}, {})
        adjusted, applied = ds_scanner.apply_policy_deltas({"证券": 8}, {"证券": 1})
        with_policy = scan(adjusted, applied)

        # base 分 +1 → 政策催化位 +2 → 四维总分 +2
        self.assertEqual(with_policy["policy_delta"], 1)
        self.assertEqual(with_policy["base_score_before_policy"], 8)
        self.assertEqual(with_policy["base_score"], 9)
        self.assertEqual(
            with_policy["score"]["policy_catalyst"] - plain["score"]["policy_catalyst"], 2
        )
        self.assertEqual(with_policy["score"]["total"] - plain["score"]["total"], 2)
        # 政策不碰 policy 总分，因此不可能触发/压制 RISK_STOP
        self.assertEqual(with_policy["policy"], plain["policy"])

    def test_report_section_states_when_policy_did_not_apply(self):
        lines = ds_scanner.policy_adjustment_section(
            [], {"ok": False, "reason": "政策数据已过期（2026-07-01，距今26天）", "deltas": {}}
        )
        text = "\n".join(lines)
        self.assertIn("政策数据已过期", text)
        self.assertIn("纯手工 base 分", text)

    def test_report_section_lists_touched_symbols(self):
        rows = [
            {
                "name": "证券ETF",
                "category": "证券",
                "base_score": 9,
                "base_score_before_policy": 8,
                "policy_delta": 1,
                "score": {"policy_catalyst": 18, "total": 61},
            }
        ]
        text = "\n".join(
            ds_scanner.policy_adjustment_section(
                rows, {"ok": True, "as_of": "2026-07-27", "applied": {"证券": 1}}
            )
        )
        self.assertIn("证券 +1", text)
        self.assertIn("8→9", text)

    def test_decision_carries_policy_state_for_bark(self):
        """decision.json 必须带政策状态：Bark 只读 decision，读不到就等于没报警。"""
        block = ds_scanner.policy_decision_block(
            {"ok": True, "as_of": "2026-07-29", "reason": "", "applied": {"证券": 1}}
        )
        self.assertTrue(block["ok"])
        self.assertEqual(block["as_of"], "2026-07-29")
        self.assertEqual(block["applied"], {"证券": 1})

    def test_decision_policy_block_keeps_failure_reason(self):
        """走真实的缺文件路径：这正是 2026-07-27~29 停摆 2 天时的状态。"""
        with patch.object(ds_scanner, "POLICY_DELTA_FILE", "/nonexistent/last_delta.json"):
            state = ds_scanner.load_policy_deltas(today=date(2026, 7, 29))
        block = ds_scanner.policy_decision_block(state)
        self.assertFalse(block["ok"])
        self.assertIn("缺失", block["reason"])
        self.assertEqual(block["applied"], {})


def split_history(bars=30, break_at=15, pre=1.75, post=1.16, slope=0.005):
    """构造一段含份额折算断层的原始K线：断层前后价格体系不连续。"""
    closes = []
    for i in range(bars):
        if i < break_at:
            closes.append(round(pre - i * slope, 4))
        else:
            closes.append(round(post - (i - break_at) * slope, 4))
    days = [date.today() - timedelta(days=value) for value in range(bars, 0, -1)]
    return pd.DataFrame(
        {
            "date": days,
            "open": closes,
            "high": [round(value * 1.01, 4) for value in closes],
            "low": [round(value * 0.99, 4) for value in closes],
            "close": closes,
            "volume": [1000.0] * bars,
        }
    )


class PriceDiscontinuityTests(unittest.TestCase):
    """份额折算断层修正（2026-07-27 半导体ETF MA20偏离-29.64%却判"有效"）。"""

    def test_split_is_detected_and_series_becomes_continuous(self):
        raw = split_history()
        fixed, breaks = ds_scanner.repair_price_discontinuity(raw)

        self.assertEqual(len(breaks), 1)
        self.assertLess(breaks[0]["ratio"], 0.75)

        closes = fixed["close"].tolist()
        jumps = [
            abs(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))
        ]
        self.assertLess(max(jumps), ds_scanner.PRICE_JUMP_RATIO_LIMIT)
        # 断层之后的K线不该被动过
        self.assertAlmostEqual(closes[-1], raw["close"].tolist()[-1], places=6)

    def test_ma20_is_repaired_into_a_plausible_band(self):
        raw = split_history()
        raw_ma20 = float(raw["close"].tail(20).mean())
        fixed, _ = ds_scanner.repair_price_discontinuity(raw)
        fixed_ma20 = float(fixed["close"].tail(20).mean())
        price = float(raw["close"].iloc[-1])

        # 修正前 MA20 被断层前的高价体系拉高，偏离度严重失真
        self.assertLess((price / raw_ma20 - 1) * 100, -10)
        # 修正后回到可信区间
        self.assertGreater((price / fixed_ma20 - 1) * 100, -5)

    def test_normal_history_is_returned_untouched(self):
        days = [date.today() - timedelta(days=value) for value in range(30, 0, -1)]
        raw = pd.DataFrame(
            {
                "date": days,
                "open": [1 + i * 0.001 for i in range(30)],
                "high": [1.01 + i * 0.001 for i in range(30)],
                "low": [0.99 + i * 0.001 for i in range(30)],
                "close": [1 + i * 0.001 for i in range(30)],
                "volume": [1000.0] * 30,
            }
        )
        fixed, breaks = ds_scanner.repair_price_discontinuity(raw)
        self.assertEqual(breaks, [])
        self.assertIs(fixed, raw)

    def test_limit_move_is_not_mistaken_for_a_split(self):
        """单日20%涨跌停是真实行情，不能当成折算去缩放。"""
        raw = split_history(break_at=15, pre=1.30, post=1.079, slope=0.0)
        # 1.30 → 1.079 相当于单日 -17%，在涨跌停可能范围内
        _, breaks = ds_scanner.repair_price_discontinuity(raw)
        self.assertEqual(breaks, [])

    def test_volume_is_adjusted_inversely_to_price(self):
        raw = split_history()
        raw_closes = raw["close"].tolist()
        # breaks 里的 ratio 是展示用的四舍五入值，期望值要用原始收盘价算
        ratio = raw_closes[15] / raw_closes[14]
        fixed, _ = ds_scanner.repair_price_discontinuity(raw)
        volumes = fixed["volume"].tolist()
        self.assertAlmostEqual(volumes[0], 1000.0 / ratio, places=6)
        self.assertAlmostEqual(volumes[-1], 1000.0, places=6)

    def test_adjusted_symbol_stays_valid_and_is_flagged(self):
        raw = split_history()
        history, breaks = ds_scanner.repair_price_discontinuity(raw)
        history.attrs["price_breaks"] = breaks
        realtime = {
            "sh512480": {
                "price": float(raw["close"].iloc[-1]),
                "last_close": float(raw["close"].iloc[-1]),
                "change_pct": -0.9,
                "volume": 1200,
            }
        }
        pool = {
            "sh512480": {
                "name": "半导体ETF",
                "category": "半导体",
                "policy": 30,
                "_breakdown": {"base": 15},
            }
        }
        with patch.object(ds_scanner, "fetch_sina_history", return_value=history):
            rows = ds_scanner.scan_etf_pool(
                pool, set(), realtime, {"半导体": 15}, index_change=0
            )

        quality = rows[0]["data_quality"]
        # 断层已修正 → 不能因此被判死，但要留痕
        self.assertTrue(quality["valid"])
        self.assertEqual(quality["issues"], [])
        self.assertEqual(len(quality["adjustments"]), 1)
        self.assertGreater(rows[0]["ma20_deviation_pct"], -10)

    def test_quality_label_distinguishes_adjusted_from_clean(self):
        self.assertEqual(
            ds_scanner.data_quality_label({"valid": True, "issues": [], "adjustments": []}),
            "有效",
        )
        self.assertEqual(
            ds_scanner.data_quality_label(
                {"valid": True, "issues": [], "adjustments": [{"ratio": 0.69}]}
            ),
            "有效(已复权1处)",
        )
        self.assertEqual(
            ds_scanner.data_quality_label(
                {"valid": False, "issues": ["ABNORMAL_MA20_DEVIATION"], "adjustments": []}
            ),
            "ABNORMAL_MA20_DEVIATION",
        )


if __name__ == "__main__":
    unittest.main()
