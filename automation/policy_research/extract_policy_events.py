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
    from automation.policy_research import ai_classify
else:
    from . import common
    from . import ai_classify


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


def extract_events(raw_rows: List[Dict], ai_verdicts: Dict[str, Dict] = None):
    """返回 (事件列表, 因无发布日期被排除的条目)。

    排除项必须一并返回：静默丢弃和静默兜底是同一类错误的两面。

    ai_verdicts 非空时走 AI 判定（X-Plan.md 模块11）：**只有 AI 读过并判过的条目
    才成为事件**——AI 第一趟就是在回答"哪些最可能是实质利好/利空"，没被选中的
    本就是噪音，再用关键词把它们捞回来等于绕开了这次改造。
    ai_verdicts 为空则整条走关键词兜底，即改造前的行为。
    """
    config = load_theme_config()
    by_key: Dict[str, Dict] = {}
    skipped_no_date: List[Dict] = []
    for raw in raw_rows:
        title = common.compact_text(raw.get("title", ""), 220)
        verdict = (ai_verdicts or {}).get(raw.get("raw_id"))
        if ai_verdicts is not None:
            if not verdict:
                continue
            themes = [verdict["sector"]]
            direction = verdict["direction"]
            action = classify_action(title, config)
            strength = int(verdict["strength"])
        else:
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
        published = common.parse_date(raw.get("published_at"))
        published_estimated = published is None
        if published_estimated:
            # 源站没给发布日期时，用抓取日期顶上（大亨 2026-07-29 决定：商务部这类
            # 滚动很快的新闻列表，条目在榜时间就是几天，抓取日 ≈ 发布日，宁可近似
            # 也不要丢掉）。必须标记 estimated，score 会把权重压到 0.5。
            #
            # ⚠️ 这个近似只对"滚动列表"成立，对停更的归档页是灾难：条目永远在榜，
            # 每天被重新标成"今天"，就成了不死的僵尸。2026-07-29 那条 2021-12-03 的
            # 证监会试点公告就是这么来的（源 URL 指向 2021 年归档页，见 docs/03 2.4.1）。
            # 换源 URL 是前提，不是可选项。
            published = common.parse_date(raw.get("collected_at"))
        if published is None:
            skipped_no_date.append({"title": title, "source": raw.get("source"), "url": raw.get("url")})
            continue
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
                # True = 这个日期来自抓取时间而非源站，score 会把衰减权重压到 0.5
                "published_at_estimated": published_estimated,
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
            # 置信度按"几个不同的源报了这件事"算，不能按条目数。
            # 证监会一天挂 6 份标题都叫《行政处罚决定书》的文件，标题归一后并成一条，
            # 按 len(sources) 算就成了"6 个源佐证"，置信度被凭空抬到 high。
            distinct = {row.get("source") for row in event["sources"] if row.get("source")}
            event["confidence"] = (
                "high" if event["evidence_strength"] >= 4 or len(distinct) >= 2 else event["confidence"]
            )
    return list(by_key.values()), skipped_no_date


def existing_ids(path) -> set:
    return {row.get("event_id") for row in common.read_jsonl(path) if row.get("event_id")}


def run_extract(days: int = 7, use_ai: bool = True) -> Dict:
    raw_rows = common.read_recent_jsonl(common.RAW_DIR, days)
    config = load_theme_config()
    ai = {"ok": False, "reason": "未启用", "verdicts": {}, "stats": {}}
    if use_ai:
        ai = ai_classify.classify(raw_rows, map_themes, config)
    events, skipped_no_date = extract_events(raw_rows, ai["verdicts"] if ai["ok"] else None)
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
        # 分类是 AI 判的还是关键词兜底的，必须随快照出仓：下游要据此在
        # report 和 Bark 里显式标注，绝不能让兜底悄悄发生（红线 4）
        "classifier": "ai" if ai["ok"] else "keyword",
        "ai_ok": bool(ai["ok"]),
        "ai_reason": ai.get("reason") or "",
        "ai_model": ai.get("model") or "",
        "ai_stats": ai.get("stats") or {},
        # 被排除的条目要留痕：数量突然变大 = 某个源改版导致日期解析失效
        "skipped_no_date_count": len(skipped_no_date),
        "skipped_no_date": skipped_no_date[:20],
    }
    common.save_json(common.SNAPSHOT_DIR / "last_extract.json", snapshot)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    result = run_extract(args.days)
    print(
        f"policy extract: {result['new_event_count']} new events from {result['raw_count']} raw items"
        f"（{result['skipped_no_date_count']} 条无发布日期被排除）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

