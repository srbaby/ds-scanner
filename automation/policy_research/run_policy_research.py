#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the full policy research pipeline."""

from __future__ import annotations

import argparse
import os
import sys

if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from automation.policy_research.collect_policy_news import collect_all
    from automation.policy_research.extract_policy_events import run_extract
    from automation.policy_research.score_policy_delta import run_score
    from automation.policy_research.compare_policy_decision import run_compare
else:
    from .collect_policy_news import collect_all
    from .extract_policy_events import run_extract
    from .score_policy_delta import run_score
    from .compare_policy_decision import run_compare


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-collect", action="store_true", help="只处理已有 raw 数据")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--score-days", type=int, default=90)
    args = parser.parse_args()

    if not args.skip_collect:
        collect = collect_all()
        print(f"collect: {collect['collected_count']} new, {collect['error_count']} errors")
    extract = run_extract(args.days)
    print(f"extract: {extract['new_event_count']} new events")
    score = run_score(args.score_days)
    active = sum(1 for row in score["themes"].values() if row.get("active_delta"))
    print(f"score: {active} active theme deltas")
    compare = run_compare()
    print(f"compare: {compare['impact']['operation_changes']} changes, aggression {compare['impact']['aggression_index']:+.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
