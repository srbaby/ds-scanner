#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Score policy events into bounded, decaying theme deltas."""

from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime
from typing import Dict, List

if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from automation.policy_research import common
else:
    from . import common

BASE_CONFIG = common.ROOT / "data" / "etf_base_config.json"

# 发布日期存疑的事件最高只能拿到的衰减权重（等同于"已过一个半衰期"）
ESTIMATED_DATE_MAX_MULTIPLIER = 0.5


def load_base_scores() -> Dict[str, int]:
    config = common.load_json(BASE_CONFIG, {})
    scores = {}
    for key, value in (config.get("scores") or {}).items():
        if key.startswith("_"):
            continue
        try:
            scores[key] = int(value)
        except (TypeError, ValueError):
            continue
    return scores


def event_raw_delta(event: Dict) -> int:
    direction = event.get("direction")
    strength = int(event.get("evidence_strength") or 0)
    source_rank = max(common.rank_weight(src.get("source_rank")) for src in event.get("sources", [{}]))
    action = event.get("policy_action")

    if direction not in {"positive", "negative", "mixed"}:
        return 0
    sign = -1 if direction == "negative" else 1 if direction == "positive" else 0
    if sign == 0:
        return 0

    if source_rank >= 4 and strength >= 4:
        magnitude = 2
    elif source_rank >= 3 and strength >= 3:
        magnitude = 1
    elif source_rank >= 2 and len(event.get("sources", [])) >= 2 and strength >= 2:
        magnitude = 1
    else:
        magnitude = 0

    if action == "external_restriction" and source_rank >= 3:
        magnitude = max(magnitude, 1)
    return sign * magnitude


def decay_multiplier(event: Dict, as_of: datetime) -> float:
    published = common.parse_date(event.get("published_at")) or as_of
    expires = common.parse_date(event.get("expires_at"))
    if expires and as_of.date() > expires.date():
        return 0.0
    age_days = max(0, (as_of.date() - published.date()).days)
    half_life = max(1, int(event.get("half_life_days") or 10))
    if age_days <= half_life:
        multiplier = 1.0
    elif age_days <= half_life * 2:
        multiplier = 0.5
    else:
        multiplier = 0.25
    if event.get("published_at_estimated"):
        # 发布日期没抓到 → published_at 只能填当天，age 恒为0、权重恒为满分，
        # 下面这整套半衰期就被架空了。日期存疑就不发满权重。
        multiplier = min(multiplier, ESTIMATED_DATE_MAX_MULTIPLIER)
    return multiplier


def effective_event_delta(event: Dict, as_of: datetime) -> float:
    return event_raw_delta(event) * decay_multiplier(event, as_of)


def aggregate_deltas(events: List[Dict], as_of: datetime) -> Dict[str, Dict]:
    themes: Dict[str, Dict] = {}
    for event in events:
        raw = event_raw_delta(event)
        effective = effective_event_delta(event, as_of)
        if raw == 0 or effective == 0:
            continue
        for theme in event.get("themes") or []:
            row = themes.setdefault(
                theme,
                {
                    "raw_delta_sum": 0.0,
                    "active_delta": 0,
                    "positive_events": 0,
                    "negative_events": 0,
                    "events": [],
                },
            )
            row["raw_delta_sum"] += effective
            if effective > 0:
                row["positive_events"] += 1
            elif effective < 0:
                row["negative_events"] += 1
            row["events"].append(
                {
                    "event_id": event.get("event_id"),
                    "title": event.get("title"),
                    "direction": event.get("direction"),
                    "raw_delta": raw,
                    "effective_delta": round(effective, 2),
                    "confidence": event.get("confidence"),
                    "published_at": event.get("published_at"),
                    "published_at_estimated": bool(event.get("published_at_estimated")),
                    "expires_at": event.get("expires_at"),
                    "sources": event.get("sources", [])[:3],
                }
            )

    for theme, row in themes.items():
        if row["raw_delta_sum"] >= 1.5:
            active = 2
        elif row["raw_delta_sum"] >= 0.5:
            active = 1
        elif row["raw_delta_sum"] <= -1.5:
            active = -2
        elif row["raw_delta_sum"] <= -0.5:
            active = -1
        else:
            active = 0
        row["active_delta"] = max(-2, min(2, active))
        row["raw_delta_sum"] = round(row["raw_delta_sum"], 2)
    return themes


def monthly_base_suggestions(events: List[Dict], as_of: datetime) -> Dict[str, Dict]:
    month_events = []
    for event in events:
        published = common.parse_date(event.get("published_at"))
        if not published:
            continue
        if 0 <= (as_of.date() - published.date()).days <= 30:
            month_events.append(event)
    totals: Dict[str, float] = {}
    for event in month_events:
        raw = event_raw_delta(event)
        for theme in event.get("themes") or []:
            totals[theme] = totals.get(theme, 0.0) + raw
    suggestions = {}
    for theme, value in totals.items():
        if value >= 6:
            suggestions[theme] = {"suggested_base_delta": 1, "net_event_score_30d": value}
        elif value <= -6:
            suggestions[theme] = {"suggested_base_delta": -1, "net_event_score_30d": value}
    return suggestions


def run_score(days: int = 90, as_of_text: str | None = None) -> Dict:
    as_of = common.parse_date(as_of_text) if as_of_text else datetime.now()
    as_of = as_of or datetime.now()
    events = common.read_recent_jsonl(common.EVENT_DIR, days)
    deltas = aggregate_deltas(events, as_of)
    base_scores = load_base_scores()
    themes = {}
    for theme, base in base_scores.items():
        active = deltas.get(theme, {}).get("active_delta", 0)
        themes[theme] = {
            "base": base,
            "active_delta": active,
            "effective_base": max(0, min(15, base + active)),
            "policy_events": deltas.get(theme, {}).get("events", []),
            "raw_delta_sum": deltas.get(theme, {}).get("raw_delta_sum", 0.0),
        }
    report = {
        "generated_at": common.now_str(),
        "as_of": as_of.strftime("%Y-%m-%d"),
        # delta 由扫描器在运行时叠加到 base 分上，但绝不回写 etf_base_config.json
        # ——那个文件是人工维护的真理源，自动化只能在运行时加偏移，不能改它
        "mode": "runtime_delta_no_write_to_etf_base_config",
        "event_count": len(events),
        "themes": themes,
        "monthly_base_suggestions": monthly_base_suggestions(events, as_of),
    }
    output = common.DELTA_DIR / f"{as_of.strftime('%Y-%m-%d')}.json"
    common.save_json(output, report)
    common.save_json(common.SNAPSHOT_DIR / "last_delta.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--as-of")
    args = parser.parse_args()
    result = run_score(args.days, args.as_of)
    active = sum(1 for row in result["themes"].values() if row["active_delta"])
    print(f"policy score: {active} themes with active policy deltas from {result['event_count']} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
