#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare current decisions with policy-event adjusted decisions."""

from __future__ import annotations

import argparse
import copy
import os
import sys
from typing import Dict, List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
AUTOMATION_DIR = os.path.dirname(os.path.dirname(__file__))
for candidate in (ROOT_DIR, AUTOMATION_DIR):
    if candidate not in sys.path:
        sys.path.append(candidate)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from automation.policy_research import common
    import automation.ds_scanner as ds_scanner
else:
    from . import common
    from .. import ds_scanner


def load_latest_delta() -> Dict:
    latest = common.load_json(common.SNAPSHOT_DIR / "last_delta.json", {})
    if latest:
        return latest
    candidates = sorted(common.DELTA_DIR.glob("*.json"))
    return common.load_json(candidates[-1], {}) if candidates else {}


def adjusted_base_scores(base_scores: Dict, delta_report: Dict) -> Dict:
    adjusted = {}
    themes = delta_report.get("themes") or {}
    for theme, value in base_scores.items():
        if str(theme).startswith("_"):
            continue
        active = int((themes.get(theme) or {}).get("active_delta") or 0)
        adjusted[theme] = max(0, min(15, int(value) + active))
    return adjusted


def apply_shadow_rows(etf_rows: List[Dict], adjusted_scores: Dict) -> List[Dict]:
    rows = copy.deepcopy(etf_rows)
    for row in rows:
        adjusted_base = adjusted_scores.get(row.get("category"), row.get("base_score", 0))
        old_base = row.get("base_score", 0)
        score = copy.deepcopy(row["score"])
        old_policy = score.get("policy_catalyst", 0)
        new_policy = max(0, min(30, round(float(adjusted_base) * 2)))
        score["policy_catalyst"] = new_policy
        score["total"] = score.get("total", 0) - old_policy + new_policy
        row["base_score"] = adjusted_base
        row["policy_delta_applied"] = adjusted_base - old_base
        row["score"] = score
        row["signal_grade"] = ds_scanner.determine_signal_grade(row)
    return rows


def op_map(decision: Dict) -> Dict[str, Dict]:
    return {row["symbol"]: row for row in decision.get("operations", [])}


def grade_rank(grade: str) -> int:
    return {"S": 3, "A": 2, "B": 1, "无效": 0}.get(grade or "无效", 0)


def compare_decisions(base_decision: Dict, shadow_decision: Dict) -> Dict:
    base_ops = op_map(base_decision)
    shadow_ops = op_map(shadow_decision)
    symbols = sorted(set(base_ops) | set(shadow_ops))
    diffs = []
    upgrades = 0
    downgrades = 0
    new_buy = new_add = new_sell = new_risk_stop = 0
    for symbol in symbols:
        old = base_ops.get(symbol, {})
        new = shadow_ops.get(symbol, {})
        if not old and new:
            changed = True
        elif old and not new:
            changed = True
        else:
            changed = any(
                old.get(key) != new.get(key)
                for key in ("action", "rule_code", "target_position_pct", "signal_grade")
            )
        if not changed:
            continue
        old_grade = old.get("signal_grade", "无效")
        new_grade = new.get("signal_grade", "无效")
        if grade_rank(new_grade) > grade_rank(old_grade):
            upgrades += 1
        elif grade_rank(new_grade) < grade_rank(old_grade):
            downgrades += 1
        if new.get("action") == "BUY" and old.get("action") != "BUY":
            new_buy += 1
        if new.get("action") == "ADD" and old.get("action") != "ADD":
            new_add += 1
        if new.get("action") == "SELL" and old.get("action") != "SELL":
            new_sell += 1
        if new.get("rule_code") == "RISK_STOP" and old.get("rule_code") != "RISK_STOP":
            new_risk_stop += 1
        diffs.append(
            {
                "symbol": symbol,
                "name": new.get("name") or old.get("name", ""),
                "baseline": compact_op(old),
                "policy_shadow": compact_op(new),
            }
        )

    target_delta = (
        shadow_decision.get("portfolio", {}).get("target_equity_position_pct", 0)
        - base_decision.get("portfolio", {}).get("target_equity_position_pct", 0)
    )
    aggression_index = (
        new_buy * 3
        + new_add * 2
        + upgrades
        + target_delta / 5
        - new_sell * 2
        - new_risk_stop * 4
    )
    if aggression_index < -4:
        verdict = "过度防守"
    elif aggression_index <= 3:
        verdict = "可接受"
    elif aggression_index <= 7:
        verdict = "偏激进，可观察"
    else:
        verdict = "过激，自动降权或仅报告"
    return {
        "operation_changes": len(diffs),
        "grade_upgrades": upgrades,
        "grade_downgrades": downgrades,
        "new_buy_count": new_buy,
        "new_add_count": new_add,
        "new_sell_count": new_sell,
        "new_risk_stop_count": new_risk_stop,
        "target_position_delta_pct": round(target_delta, 1),
        "aggression_index": round(aggression_index, 2),
        "verdict": verdict,
        "diffs": diffs,
    }

def signal_gap(row: Dict) -> Dict:
    """Explain how close a row is to the first actionable B signal."""
    score = (row.get("score") or {}).get("total", 0)
    blockers = []
    if score < 75:
        blockers.append(f"评分差{75 - score:.0f}")
    if row.get("price", 0) <= row.get("ma20", 0):
        blockers.append("未站上MA20")
    if row.get("ma20_deviation_pct", 99) > 15:
        blockers.append("MA20偏离过热")
    if row.get("vol_ratio", 0) < 1.2:
        blockers.append(f"量能{row.get('vol_ratio', 0):.2f}<1.20")
    if "流出" in str(row.get("fund_flow", "")):
        blockers.append("资金流出")
    return {"score_to_b": max(0, round(75 - score, 1)), "blockers": blockers[:4]}


def compact_watch_row(base: Dict, shadow: Dict, active_delta: int, holding: bool, shadow_ops: Dict) -> Dict:
    symbol = shadow.get("full_symbol") or base.get("full_symbol") or shadow.get("symbol") or base.get("symbol")
    numeric_symbol = str(symbol).replace("sh", "").replace("sz", "")
    op = shadow_ops.get(symbol) or shadow_ops.get(numeric_symbol) or {}
    base_score = (base.get("score") or {}).get("total", 0)
    shadow_score = (shadow.get("score") or {}).get("total", 0)
    gap = signal_gap(shadow)
    seen_events = set()
    events = []
    for event in (shadow.get("policy_events") or []) + (base.get("policy_events") or []):
        event_id = event.get("event_id") or event.get("title")
        if event_id in seen_events:
            continue
        seen_events.add(event_id)
        events.append(event)
        if len(events) >= 2:
            break
    return {
        "symbol": symbol,
        "name": shadow.get("name") or base.get("name", ""),
        "theme": shadow.get("category") or base.get("category", ""),
        "holding": holding,
        "policy_delta": active_delta,
        "base_score": base_score,
        "shadow_score": shadow_score,
        "score_change": round(shadow_score - base_score, 1),
        "base_grade": base.get("signal_grade", "无效"),
        "shadow_grade": shadow.get("signal_grade", "无效"),
        "shadow_action": op.get("action", ""),
        "shadow_rule": op.get("rule_code", ""),
        "target_position_pct": op.get("target_position_pct", 0),
        "gap": gap,
        "note": op.get("reason") or ("接近B级触发" if gap["score_to_b"] <= 5 else "政策偏移已生效，等待技术/量能确认"),
        "events": events,
    }


def build_policy_watchlist(base_rows: List[Dict], shadow_rows: List[Dict], holdings_data: List[Dict], delta_report: Dict, shadow_decision: Dict, impact: Dict) -> Dict:
    active = {theme: int(row.get("active_delta") or 0) for theme, row in (delta_report.get("themes") or {}).items() if row.get("active_delta")}
    event_map = {theme: (row.get("policy_events") or [])[:2] for theme, row in (delta_report.get("themes") or {}).items()}
    holding_symbols = {str(row.get("symbol")) for row in holdings_data if row.get("qty", 0) > 0 or row.get("value", 0) > 0}
    base_map = {str(row.get("symbol")): row for row in base_rows}
    shadow_ops = op_map(shadow_decision)
    holdings_risk = []
    near_triggers = []
    near_downgrades = []

    for shadow in shadow_rows:
        symbol = str(shadow.get("symbol"))
        base = base_map.get(symbol, {})
        theme = shadow.get("category") or base.get("category")
        delta = active.get(theme, 0)
        if not delta:
            continue
        base["policy_events"] = event_map.get(theme, [])
        shadow["policy_events"] = event_map.get(theme, [])
        row = compact_watch_row(base, shadow, delta, symbol in holding_symbols, shadow_ops)
        if symbol in holding_symbols and delta < 0:
            row["priority"] = "持仓政策转弱"
            holdings_risk.append(row)
        elif symbol in holding_symbols and grade_rank(row["shadow_grade"]) < grade_rank(row["base_grade"]):
            row["priority"] = "持仓信号降级"
            near_downgrades.append(row)
        elif symbol not in holding_symbols and delta > 0:
            row["priority"] = "政策正偏移接近触发" if row["shadow_action"] == "BUY" or row["shadow_grade"] in {"B", "A", "S"} or row["gap"]["score_to_b"] <= 6 else "政策正偏移观察"
            near_triggers.append(row)

    def sort_key(row: Dict):
        return (0 if row.get("shadow_action") in {"BUY", "ADD", "SELL", "REDUCE"} else 1, row.get("gap", {}).get("score_to_b", 99), -abs(row.get("policy_delta", 0)), -row.get("shadow_score", 0))

    holdings_risk = sorted(holdings_risk, key=sort_key)[:5]
    near_triggers = sorted(near_triggers, key=sort_key)[:6]
    near_downgrades = sorted(near_downgrades, key=sort_key)[:5]
    active_policy_deltas = [
        {"theme": theme, "delta": delta, "event_count": len(event_map.get(theme, [])), "sample_event": (event_map.get(theme) or [{}])[0].get("title", "")}
        for theme, delta in sorted(active.items(), key=lambda item: (-abs(item[1]), item[0]))
    ]
    return {
        "generated_at": common.now_str(),
        "updated_frequency": "随每日扫描工作流更新；页面顶部 logo + Stock X 可强制重新读取最新 dashboard.json",
        "mode": "policy_event_shadow_watch_only",
        "summary": {
            "holdings_risk_count": len(holdings_risk),
            "near_trigger_count": len(near_triggers),
            "near_downgrade_count": len(near_downgrades),
            "active_delta_count": len(active_policy_deltas),
            "aggression_index": impact.get("aggression_index", 0),
            "verdict": impact.get("verdict", "可接受"),
        },
        "active_policy_deltas": active_policy_deltas,
        "holdings_risk": holdings_risk,
        "near_triggers": near_triggers,
        "near_downgrades": near_downgrades,
    }

def compact_op(row: Dict) -> str:
    if not row:
        return "无操作"
    return f"{row.get('action', '-')}/{row.get('rule_code', '-')}/{row.get('signal_grade', '-')}/目标{row.get('target_position_pct', 0)}%/评分{row.get('score', 0)}"


def run_compare() -> Dict:
    delta_report = load_latest_delta()
    if not delta_report:
        raise RuntimeError("没有 policy delta，请先运行 score_policy_delta.py")
    base_scores = ds_scanner.load_base_scores()
    holdings_config = ds_scanner.load_holdings()
    cash_available = holdings_config.get("cash_available", 0)
    holding_symbols = {row["symbol"] for row in holdings_config.get("holdings", []) if row.get("qty", 0) > 0}

    market = ds_scanner.scan_market()
    index_change = market["index"].get("change_pct", 0) if market["index"].get("ok") else 0
    etf_pool = ds_scanner.load_etf_pool()
    if not etf_pool:
        raise RuntimeError("data/etf_pool.json 不可用")
    holdings_data, _, total_value = ds_scanner.scan_holdings_with_wave_management(
        holdings_config, market["realtime"], etf_pool
    )
    base_rows = ds_scanner.scan_etf_pool(etf_pool, holding_symbols, market["realtime"], base_scores, index_change)
    base_decision = ds_scanner.build_authoritative_decision(base_rows, holdings_data, total_value, cash_available)

    adjusted_scores = adjusted_base_scores(base_scores, delta_report)
    shadow_rows = apply_shadow_rows(base_rows, adjusted_scores)
    shadow_decision = ds_scanner.build_authoritative_decision(shadow_rows, holdings_data, total_value, cash_available)
    impact = compare_decisions(base_decision, shadow_decision)
    watchlist = build_policy_watchlist(base_rows, shadow_rows, holdings_data, delta_report, shadow_decision, impact)
    report = {
        "generated_at": common.now_str(),
        "mode": "policy_event_shadow_no_write_to_production",
        "delta_as_of": delta_report.get("as_of"),
        "impact": impact,
        "watchlist": watchlist,
        "active_theme_deltas": {
            theme: row
            for theme, row in (delta_report.get("themes") or {}).items()
            if row.get("active_delta")
        },
    }
    output = common.SNAPSHOT_DIR / "last_decision_compare.json"
    common.save_json(output, report)
    common.save_json(common.SNAPSHOT_DIR / "policy_watchlist.json", watchlist)
    common.save_json(common.DELTA_DIR / f"decision_compare_{common.today_str()}.json", report)
    render_report(report)
    return report


def render_report(report: Dict) -> None:
    impact = report["impact"]
    lines = [
        "# Policy Event Shadow 决策影响报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        "- 模式：政策/新闻事件旁路，不写正式配置，不改主扫描器。",
        f"- delta 日期：{report.get('delta_as_of')}",
        "",
        "## 激进度",
        "",
        f"- 操作变化：{impact['operation_changes']}",
        f"- 信号升级/降级：{impact['grade_upgrades']} / {impact['grade_downgrades']}",
        f"- 新增 BUY/ADD/SELL/RISK_STOP：{impact['new_buy_count']} / {impact['new_add_count']} / {impact['new_sell_count']} / {impact['new_risk_stop_count']}",
        f"- 目标仓位变化：{impact['target_position_delta_pct']:+.1f}%",
        f"- aggression_index：{impact['aggression_index']:+.2f}",
        f"- 结论：{impact['verdict']}",
        "",
        "## 活跃政策 delta",
        "",
    ]
    active = report.get("active_theme_deltas") or {}
    if active:
        lines.extend(["| 主题 | base | delta | effective | 证据数 |", "| --- | ---: | ---: | ---: | ---: |"])
        for theme, row in sorted(active.items()):
            lines.append(f"| {theme} | {row['base']} | {row['active_delta']:+d} | {row['effective_base']} | {len(row.get('policy_events') or [])} |")
    else:
        lines.append("无活跃政策 delta。")
    lines.extend(["", "## 操作差异", ""])
    if impact["diffs"]:
        lines.extend(["| 标的 | 名称 | 原规则 | 政策旁路 |", "| --- | --- | --- | --- |"])
        for row in impact["diffs"]:
            lines.append(f"| {row['symbol']} | {row['name']} | {row['baseline']} | {row['policy_shadow']} |")
    else:
        lines.append("无操作差异。")
    path = common.REPORT_DIR / f"{common.today_str()}-decision-impact.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    result = run_compare()
    print(f"policy compare: {result['impact']['operation_changes']} operation changes, aggression {result['impact']['aggression_index']:+.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())






