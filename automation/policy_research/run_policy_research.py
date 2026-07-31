#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the full policy research pipeline."""

from __future__ import annotations

import argparse
import os
import sys
import time

if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from automation.policy_research import common
    from automation.policy_research.collect_policy_news import collect_all
    from automation.policy_research.extract_policy_events import run_extract
    from automation.policy_research.score_policy_delta import run_score
    from automation.policy_research.compare_policy_decision import (
        PollutedEtfPoolError,
        run_compare,
    )
else:
    from . import common
    from .collect_policy_news import collect_all
    from .extract_policy_events import run_extract
    from .score_policy_delta import run_score
    from .compare_policy_decision import PollutedEtfPoolError, run_compare


POLICY_STATUS_FILE = common.SNAPSHOT_DIR / "policy_observation_status.json"


def _write_github_output(name: str, value: str) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    with open(output_file, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def _write_observation_status(status: str, message: str = "", delta_as_of: str = "") -> None:
    payload = {"status": status, "updated_at": common.now_str()}
    if message:
        payload["message"] = message
    if delta_as_of:
        payload["delta_as_of"] = delta_as_of
    common.save_json(POLICY_STATUS_FILE, payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-collect", action="store_true", help="只处理已有 raw 数据")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--score-days", type=int, default=90)
    parser.add_argument("--no-ai", action="store_true", help="强制走关键词兜底，不调 AI")
    parser.add_argument(
        "--compare-only",
        action="store_true",
        help="主扫描器刷新 ETF 池后，只重新生成政策影响观察，不重复采集/评分",
    )
    args = parser.parse_args()

    _write_github_output("compare_deferred", "false")
    _write_github_output("all_sources_failed", "false")
    _write_observation_status("running", "本次政策影响观察尚未完成")

    if args.compare_only:
        try:
            compare = run_compare()
        except Exception as exc:
            _write_observation_status("failed", f"扫描后政策观察补生成失败: {exc}")
            raise
        _write_observation_status("ready", delta_as_of=compare.get("delta_as_of", ""))
        print(
            f"compare-only: {compare['impact']['operation_changes']} changes, "
            f"aggression {compare['impact']['aggression_index']:+.2f}"
        )
        return 0

    all_sources_failed = False
    timings = {"collect": 0.0, "ai_pass1": 0.0, "body_fetch": 0.0, "ai_pass2": 0.0,
               "score": 0.0, "compare": 0.0}
    if not args.skip_collect:
        started = time.perf_counter()
        collect = collect_all()
        timings["collect"] = time.perf_counter() - started
        all_sources_failed = bool(collect.get("all_sources_failed"))
        _write_github_output("all_sources_failed", str(all_sources_failed).lower())
        print(
            f"collect: {collect['collected_count']} new, "
            f"{collect['error_count']}/{collect['source_total']} errors"
        )
        print(f"timing: collect={timings['collect']:.3f}s")
        if all_sources_failed:
            print("⚠️ 政策源全部采集失败，本次 delta 不可信（扫描器会拒用并在 Bark 报警）")
        zero = collect.get("zero_yield_sources") or []
        if zero:
            print(f"ℹ️ 本次 0 产出的源（{len(zero)}/{collect['source_total']}）：{'、'.join(zero)}")
    else:
        print("timing: collect=skipped")
    extract = run_extract(args.days, use_ai=not args.no_ai, timings=timings)
    print(
        f"timing: AI 第一趟={timings['ai_pass1']:.3f}s "
        f"正文抓取={timings['body_fetch']:.3f}s "
        f"AI 第二趟={timings['ai_pass2']:.3f}s"
    )
    st = extract.get("ai_stats") or {}
    if extract.get("ai_ok"):
        print(
            f"classify: AI({extract.get('ai_model')}) 粗筛{st.get('prefiltered', 0)}条"
            f"→选读{st.get('picked', 0)}条(抓到正文{st.get('fetched', 0)})"
            f"→判定{st.get('classified', 0)}条"
        )
    else:
        print(f"⚠️ classify: 归类退回关键词兜底——{extract.get('ai_reason')}")
    print(
        f"extract: {extract['new_event_count']} new events"
        f"，{extract['skipped_no_date_count']} 条因无发布日期被排除"
    )
    started = time.perf_counter()
    score = run_score(args.score_days)
    timings["score"] = time.perf_counter() - started
    print(f"timing: score={timings['score']:.3f}s")
    active = sum(1 for row in score["themes"].values() if row.get("active_delta"))
    print(f"score: {active} active theme deltas")
    started = time.perf_counter()
    try:
        compare = run_compare()
    except PollutedEtfPoolError as exc:
        _write_observation_status("deferred", str(exc))
        _write_github_output("compare_deferred", "true")
        print(f"⚠️ 政策影响观察延期：{exc}")
        print("ℹ️ 主扫描器将先用人工 base 刷新 ETF 池，随后只补生成本次政策观察")
        return 1 if all_sources_failed else 0
    except Exception as exc:
        _write_observation_status("failed", f"政策影响观察失败: {exc}")
        raise
    timings["compare"] = time.perf_counter() - started
    print(f"timing: compare={timings['compare']:.3f}s")
    print(f"compare: {compare['impact']['operation_changes']} changes, aggression {compare['impact']['aggression_index']:+.2f}")
    _write_observation_status("ready", delta_as_of=compare.get("delta_as_of", ""))
    return 1 if all_sources_failed else 0


if __name__ == "__main__":
    sys.exit(main())
