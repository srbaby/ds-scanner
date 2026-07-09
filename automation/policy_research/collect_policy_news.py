#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect whitelisted policy/news items for X-Plan policy research."""

from __future__ import annotations

import argparse
import os
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
        row = {
            "raw_id": common.stable_id(source["id"], url, title),
            "collected_at": common.now_str(),
            "source_id": source["id"],
            "source": source["name"],
            "source_rank": source["rank"],
            "region": source.get("region", ""),
            "title": title,
            "url": url,
            "published_at": None,
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

    for source in config.get("sources") or []:
        if not source.get("enabled", True):
            continue
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
        "collected_count": written,
        "error_count": len(errors),
        "errors": errors,
    }
    common.save_json(common.SNAPSHOT_DIR / "last_collect.json", snapshot)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    result = collect_all()
    print(f"policy collect: {result['collected_count']} new items, {result['error_count']} source errors")
    return 0 if result["collected_count"] or result["error_count"] >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
