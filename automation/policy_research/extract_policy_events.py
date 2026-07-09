#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract deterministic policy events from collected raw items."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, List

if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from automation.policy_research import common
else:
    from . import common


def load_theme_config() -> Dict:
    return common.load_json(common.THEMES_FILE, {"themes": {}})


def normalize_title(title: str) -> str:
    text = re.sub(r"[\s\W_]+", "", str(title).lower())
    return text[:80]


def map_themes(title: str, config: Dict) -> List[str]:
    themes = []
    for theme, keywords in (config.get("themes") or {}).items():
        if common.contains_any(title, keywords):
            themes.append(theme)
    return themes


def classify_direction(title: str, config: Dict) -> str:
    positive = common.contains_any(title, config.get("positive_keywords") or [])
    negative = common.contains_any(title, config.get("negative_keywords") or [])
    if positive and not negative:
        return "positive"
    if negative and not positive:
        return "negative"
    if positive and negative:
        return "mixed"
    return "neutral"


def classify_action(title: str, config: Dict) -> str:
    text = title.lower()
    if common.contains_any(text, ["出口管制", "制裁", "关税", "export control", "sanction", "tariff"]):
        return "external_restriction"
    if common.contains_any(text, ["补贴", "专项资金", "税收", "采购", "funding", "subsidy", "tax credit"]):
        return "funding_or_tax"
    if common.contains_any(text, ["规划", "方案", "意见", "计划", "plan", "guideline"]):
        return "plan_or_guideline"
    if common.contains_any(text, ["监管", "整治", "处罚", "禁止", "准入", "标准", "regulation", "ban"]):
        return "regulation_or_standard"
    if common.contains_any(text, ["试点", "示范", "pilot"]):
        return "pilot"
    return "statement"


def evidence_strength(title: str, source_rank: str, action: str, direction: str, config: Dict) -> int:
    strength = 0
    rank = common.rank_weight(source_rank)
    if rank >= 4:
        strength += 2
    elif rank >= 3:
        strength += 1
    if action in {"funding_or_tax", "external_restriction", "regulation_or_standard"}:
        strength += 2
    elif action in {"plan_or_guideline", "pilot"}:
        strength += 1
    if common.contains_any(title, config.get("strong_action_keywords") or []):
        strength += 1
    if direction == "neutral":
        strength = max(0, strength - 1)
    return max(0, min(5, strength))


def default_decay(source_rank: str, action: str) -> Dict:
    rank = common.rank_weight(source_rank)
    if action == "statement" and rank <= 2:
        return {"decay_mode": "news_3d", "expires_in_days": 3, "half_life_days": 2}
    if rank >= 4:
        return {"decay_mode": "national_60d", "expires_in_days": 60, "half_life_days": 20}
    if rank >= 3:
        return {"decay_mode": "policy_20d", "expires_in_days": 20, "half_life_days": 10}
    return {"decay_mode": "news_7d", "expires_in_days": 7, "half_life_days": 3}


def extract_events(raw_rows: List[Dict]) -> List[Dict]:
    config = load_theme_config()
    by_key: Dict[str, Dict] = {}
    for raw in raw_rows:
        title = common.compact_text(raw.get("title", ""), 220)
        if common.contains_any(title, config.get("non_policy_keywords") or []):
            continue
        themes = map_themes(title, config)
        if not themes:
            continue
        direction = classify_direction(title, config)
        if direction == "neutral":
            continue
        action = classify_action(title, config)
        strength = evidence_strength(title, raw.get("source_rank", ""), action, direction, config)
        if strength <= 0:
            continue
        published = common.parse_date(raw.get("published_at")) or datetime.now()
        decay = default_decay(raw.get("source_rank", ""), action)
        key = common.stable_id(normalize_title(title), ",".join(sorted(themes)), direction, action)
        event = by_key.get(key)
        source_payload = {
            "source": raw.get("source"),
            "source_rank": raw.get("source_rank"),
            "url": raw.get("url"),
            "title": title,
        }
        if not event:
            event = {
                "event_id": key,
                "created_at": common.now_str(),
                "published_at": published.strftime("%Y-%m-%d"),
                "title": title,
                "themes": themes,
                "direction": direction,
                "policy_action": action,
                "evidence_strength": strength,
                "confidence": "high" if strength >= 4 else "medium" if strength >= 2 else "low",
                "decay_mode": decay["decay_mode"],
                "half_life_days": decay["half_life_days"],
                "expires_at": (published + timedelta(days=decay["expires_in_days"])).strftime("%Y-%m-%d"),
                "summary": title,
                "sources": [source_payload],
            }
            by_key[key] = event
        else:
            event["sources"].append(source_payload)
            event["evidence_strength"] = max(event["evidence_strength"], strength)
            event["confidence"] = "high" if event["evidence_strength"] >= 4 or len(event["sources"]) >= 2 else event["confidence"]
    return list(by_key.values())


def existing_ids(path) -> set:
    return {row.get("event_id") for row in common.read_jsonl(path) if row.get("event_id")}


def run_extract(days: int = 7) -> Dict:
    raw_rows = common.read_recent_jsonl(common.RAW_DIR, days)
    events = extract_events(raw_rows)
    output_path = common.EVENT_DIR / f"{common.month_key()}.jsonl"
    seen = existing_ids(output_path)
    fresh = [row for row in events if row["event_id"] not in seen]
    written = common.append_jsonl(output_path, fresh)
    snapshot = {
        "generated_at": common.now_str(),
        "events_path": str(output_path.relative_to(common.ROOT)),
        "raw_count": len(raw_rows),
        "event_count": len(events),
        "new_event_count": written,
    }
    common.save_json(common.SNAPSHOT_DIR / "last_extract.json", snapshot)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    result = run_extract(args.days)
    print(f"policy extract: {result['new_event_count']} new events from {result['raw_count']} raw items")
    return 0


if __name__ == "__main__":
    sys.exit(main())

