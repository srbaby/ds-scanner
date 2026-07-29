#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 ETF 板块核对政策源覆盖：每个板块至少要有 2 个源真正供数。

大亨 2026-07-29 定的口径：源的选择要以 ETF 为出发点，而不是"抓一堆政务网站
再看能映射到哪个主题"。这个脚本把口径变成可核对的数字。

跑法（需要先有 raw 数据，即先跑过 collect）：
    python3 automation/policy_research/check_etf_coverage.py
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

if __package__ in {None, ""}:
    from automation.policy_research import common
    from automation.policy_research import extract_policy_events as extract
else:
    from . import common
    from . import extract_policy_events as extract

MIN_SOURCES_PER_SECTOR = 2


def etf_sectors() -> dict:
    """ETF 池里真实存在的板块 -> 该板块的 ETF 名。

    以 etf_pool 为准而不是 etf_base_config：ds_scanner 取 base 分用的是 ETF 的
    category，base_config 里没有对应 ETF 的主题分永远取不到（2026-07-29 查出
    AI算力/储能/医药/大消费/银行 5 个主题就是这种情况，算了也白算）。
    """
    path = os.path.join(ROOT_DIR, "data", "etf_pool.json")
    with open(path, "r", encoding="utf-8") as f:
        pool = json.load(f).get("etfs") or {}
    sectors = collections.defaultdict(list)
    for code, row in pool.items():
        sectors[row.get("category")].append(row.get("name") or code)
    return dict(sectors)


def measure(days: int = 7) -> dict:
    config = extract.load_theme_config()
    raw_rows = common.read_recent_jsonl(common.RAW_DIR, days)
    sources_by_theme = collections.defaultdict(set)
    counts = collections.Counter()
    for raw in raw_rows:
        title = common.compact_text(raw.get("title", ""), 220)
        for theme in extract.map_themes(title, config):
            sources_by_theme[theme].add(raw.get("source"))
            counts[theme] += 1
    sectors = etf_sectors()
    rows = []
    for sector, etfs in sectors.items():
        names = sorted(s for s in sources_by_theme.get(sector, set()) if s)
        rows.append({
            "sector": sector,
            "etfs": etfs,
            "item_count": counts[sector],
            "source_count": len(names),
            "sources": names,
            "ok": len(names) >= MIN_SOURCES_PER_SECTOR,
        })
    rows.sort(key=lambda r: (r["source_count"], -r["item_count"]))
    return {"raw_count": len(raw_rows), "sectors": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    report = measure(args.days)
    print(f"原文 {report['raw_count']} 条，ETF 板块 {len(report['sectors'])} 个"
          f"（门槛：每个板块 ≥{MIN_SOURCES_PER_SECTOR} 个供数的源）\n")
    print(f"{'板块':<10}{'条数':<7}{'源数':<7}供数的源")
    print("-" * 84)
    for row in report["sectors"]:
        flag = " " if row["ok"] else "✗"
        print(f"{flag}{row['sector']:<9}{row['item_count']:<7}{row['source_count']:<7}"
              f"{'、'.join(row['sources'])[:46]}")
    bad = [r["sector"] for r in report["sectors"] if not r["ok"]]
    print()
    if bad:
        print(f"⚠️ 不达标（{len(bad)}）：{'、'.join(bad)}")
        # 覆盖是配置质量问题，不该拦住当天的扫描，所以只报不拦
        return 1
    print("✅ 全部板块达标")
    return 0


if __name__ == "__main__":
    sys.exit(main())
