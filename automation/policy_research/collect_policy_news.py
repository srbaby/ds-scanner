#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect whitelisted policy/news items for X-Plan policy research."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from automation.policy_research import common
else:
    from . import common

HEADERS = {
    "User-Agent": "Mozilla/5.0 X-Plan policy research bot; research-only",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
PROXIES = {"http": None, "https": None}


def load_keywords() -> Dict:
    return common.load_json(common.THEMES_FILE, {"global_policy_keywords": [], "themes": {}})


def item_matches(title: str, keywords: Dict) -> bool:
    all_keywords: List[str] = list(keywords.get("global_policy_keywords") or [])
    for values in (keywords.get("themes") or {}).values():
        all_keywords.extend(values)
    return common.contains_any(title, all_keywords)


# 政务列表页几乎都会在链接旁标注发布日期，URL 里也常内嵌 /202607/t20260710_ 这类日期段。
URL_DATE_PATTERNS = (
    re.compile(r"[t_](20\d{2})(\d{2})(\d{2})\D"),
    re.compile(r"/(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})(?:\D|$)"),
)
MAX_PUBLISHED_AGE_DAYS = 1095


def date_from_url(url: str):
    """从 URL 路径里解析发布日期；只有年月的形态（/202607/）取不到日，不算。"""
    for pattern in URL_DATE_PATTERNS:
        match = pattern.search(url or "")
        if not match:
            continue
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            )
        except ValueError:
            continue
    return None


def date_from_neighbourhood(anchor, title: str):
    """在链接周围找发布日期：逐层上溯父容器，并剔除标题自身文字避免误读。"""
    node = anchor
    for _ in range(3):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = common.compact_text(node.get_text(" "), 400)
        if title:
            text = text.replace(title, " ")
        found = common.parse_date(text)
        if found:
            return found
    return None


def resolve_published_at(anchor, url: str, title: str, today: datetime = None):
    """确定发布日期，取不到返回 None——绝不用"今天"顶替。

    早期实现把 published_at 直接写死 None，下游 extract_policy_events 再兜底成
    datetime.now()，导致每次跑都把事件重新标成"今天发布"，age 恒为0、衰减权重恒
    为1.0，score_policy_delta 里整套半衰期/过期逻辑成了死代码。2026-07-27 证券ETF
    那条"账户管理功能优化试点"就是这样从上线起一直挂在满权重不动。
    """
    today = today or datetime.now()
    for candidate in (date_from_url(url), date_from_neighbourhood(anchor, title)):
        if not candidate:
            continue
        age_days = (today.date() - candidate.date()).days
        if 0 <= age_days <= MAX_PUBLISHED_AGE_DAYS:
            return candidate
    return None


def extract_links(source: Dict, html: str, keywords: Dict) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for anchor in soup.find_all("a"):
        title = common.compact_text(anchor.get_text(" "), 160)
        href = anchor.get("href")
        if not title or not href:
            continue
        url = common.normalize_url(source["url"], href)
        if not common.allowed_url(url, source.get("allowed_domains") or []):
            continue
        if not item_matches(title, keywords):
            continue
        published = resolve_published_at(anchor, url, title)
        row = {
            "raw_id": common.stable_id(source["id"], url, title),
            "collected_at": common.now_str(),
            "source_id": source["id"],
            "source": source["name"],
            "source_rank": source["rank"],
            "region": source.get("region", ""),
            "title": title,
            "url": url,
            "published_at": published.strftime("%Y-%m-%d") if published else None,
            "summary": "",
        }
        rows.append(row)
    return common.dedupe_rows(rows, "raw_id")


def collect_source(source: Dict, keywords: Dict, timeout: int) -> List[Dict]:
    response = requests.get(
        source["url"],
        headers=HEADERS,
        proxies=PROXIES,
        timeout=timeout,
    )
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    return extract_links(source, response.text, keywords)


def existing_ids(path) -> set:
    return {row.get("raw_id") for row in common.read_jsonl(path) if row.get("raw_id")}


def collect_all() -> Dict:
    config = common.load_json(common.SOURCES_FILE, {})
    policy = config.get("policy") or {}
    timeout = int(policy.get("default_timeout_seconds", 12))
    max_items = int(policy.get("max_items_per_source", 30))
    keywords = load_keywords()
    output_path = common.RAW_DIR / f"{common.month_key()}.jsonl"
    seen = existing_ids(output_path)
    collected = []
    errors = []
    source_total = 0

    for source in config.get("sources") or []:
        if not source.get("enabled", True):
            continue
        source_total += 1
        try:
            rows = collect_source(source, keywords, timeout)[:max_items]
            fresh = [row for row in rows if row["raw_id"] not in seen]
            seen.update(row["raw_id"] for row in fresh)
            collected.extend(fresh)
        except Exception as exc:
            errors.append({"source_id": source.get("id"), "source": source.get("name"), "error": str(exc)[:300]})

    written = common.append_jsonl(output_path, collected)
    snapshot = {
        "generated_at": common.now_str(),
        "raw_path": str(output_path.relative_to(common.ROOT)),
        # source_total 必须落盘：只记 error_count 无法区分"3 个源挂了"和"总共就 3 个源全挂了"，
        # 而后者是全线故障。下游靠这两个数判断政策数据能不能信。
        "source_total": source_total,
        "collected_count": written,
        "error_count": len(errors),
        "all_sources_failed": bool(source_total) and len(errors) >= source_total,
        "errors": errors,
    }
    common.save_json(common.SNAPSHOT_DIR / "last_collect.json", snapshot)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    result = collect_all()
    print(
        f"policy collect: {result['collected_count']} new items, "
        f"{result['error_count']}/{result['source_total']} source errors"
    )
    # 只有"全部源都挂了"才算失败。采集 0 条新条目是正常的（周末政务站不发文，
    # 且 collected_count 统计的是去重后的新增），拿它当故障信号会天天误报。
    return 1 if result["all_sources_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
