#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bs4 import BeautifulSoup

from policy_research import collect_policy_news as collect
from policy_research import common
from policy_research import extract_policy_events as extract
from policy_research import score_policy_delta as score


class PolicyResearchTests(unittest.TestCase):
    def test_extract_maps_theme_and_direction(self):
        rows = [
            {
                "raw_id": "1",
                "source": "工信部",
                "source_rank": "S",
                "title": "工信部发布支持人工智能和算力基础设施发展的专项政策",
                "url": "https://example.com/a",
                "published_at": "2026-07-10",
            }
        ]
        events, _ = extract.extract_events(rows)
        self.assertEqual(len(events), 1)
        self.assertIn("AI算力", events[0]["themes"])
        self.assertEqual(events[0]["direction"], "positive")
        self.assertGreaterEqual(events[0]["evidence_strength"], 2)

    def test_non_policy_personnel_news_is_ignored(self):
        rows = [
            {
                "raw_id": "personnel",
                "source": "证监会",
                "source_rank": "S",
                "title": "中国证监会原发审委委员接受监察调查",
                "url": "https://example.com/p",
                "published_at": "2026-07-10",
            }
        ]
        self.assertEqual(extract.extract_events(rows)[0], [])
    def test_s_level_strong_event_maps_to_plus_two(self):
        event = {
            "direction": "positive",
            "evidence_strength": 4,
            "policy_action": "funding_or_tax",
            "sources": [{"source_rank": "S"}],
        }
        self.assertEqual(score.event_raw_delta(event), 2)

    def test_event_direction_domain_keeps_negative_mixed_and_unknown_explicit(self):
        base = {
            "evidence_strength": 4,
            "policy_action": "funding_or_tax",
            "sources": [{"source_rank": "S"}],
        }
        self.assertEqual(score.event_raw_delta({**base, "direction": "negative"}), -2)
        self.assertEqual(score.event_raw_delta({**base, "direction": "mixed"}), 0)
        self.assertEqual(score.event_raw_delta({**base, "direction": "unexpected"}), 0)

    def test_event_decay_goes_to_zero_after_expiry(self):
        event = {
            "direction": "positive",
            "evidence_strength": 4,
            "policy_action": "funding_or_tax",
            "sources": [{"source_rank": "S"}],
            "published_at": "2026-01-01",
            "expires_at": "2026-01-10",
            "half_life_days": 3,
        }
        self.assertEqual(score.effective_event_delta(event, datetime(2026, 1, 20)), 0)

    def test_theme_active_delta_is_capped_at_two(self):
        events = []
        for idx in range(3):
            events.append(
                {
                    "event_id": str(idx),
                    "title": "支持半导体专项资金",
                    "themes": ["半导体"],
                    "direction": "positive",
                    "evidence_strength": 4,
                    "policy_action": "funding_or_tax",
                    "sources": [{"source_rank": "S"}],
                    "published_at": "2026-07-10",
                    "expires_at": "2026-09-10",
                    "half_life_days": 20,
                }
            )
        result = score.aggregate_deltas(events, datetime(2026, 7, 10))
        self.assertEqual(result["半导体"]["active_delta"], 2)

    def test_monthly_base_suggestion_requires_sustained_score(self):
        events = []
        for idx in range(3):
            events.append(
                {
                    "event_id": str(idx),
                    "themes": ["AI算力"],
                    "direction": "positive",
                    "evidence_strength": 4,
                    "policy_action": "funding_or_tax",
                    "sources": [{"source_rank": "S"}],
                    "published_at": "2026-07-10",
                }
            )
        suggestions = score.monthly_base_suggestions(events, datetime(2026, 7, 20))
        self.assertEqual(suggestions["AI算力"]["suggested_base_delta"], 1)


CSRC_SOURCE = {
    "id": "csrc_policy",
    "name": "证监会政策法规",
    "rank": "S",
    "region": "CN",
    "url": "http://www.csrc.gov.cn/csrc/c100028/common_list.shtml",
    "allowed_domains": ["www.csrc.gov.cn"],
}
KEYWORDS = {"global_policy_keywords": ["试点"], "themes": {}}
TITLE = "证监会同意开展证券公司账户管理功能优化试点"


class PublishDateTests(unittest.TestCase):
    """发布日期必须来自源站，不能拿"今天"顶替。

    2026-07-27 现象：证券ETF那条试点公告从功能上线起一直挂在满权重不动。根因是
    采集端 published_at 恒为 None、抽取端兜底成 datetime.now()，加上 Actions 里
    事件目录每次都是全新的，等于每天把事件重刷成"今天发布"，衰减永远不生效。
    """

    def _html(self, date_text="", href="/csrc/c100028/c1605527/content.shtml"):
        return (
            f'<ul><li><a href="{href}">{TITLE}</a>'
            f"<span>{date_text}</span></li></ul>"
        )

    def test_published_date_is_read_from_listing_page(self):
        published = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        rows = collect.extract_links(
            CSRC_SOURCE, self._html(date_text=published), KEYWORDS
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["published_at"], published)

    def test_published_date_falls_back_to_url_path(self):
        day = datetime.now() - timedelta(days=5)
        href = f"/csrc/c100028/c1605527/t{day.strftime('%Y%m%d')}_123456.shtml"
        rows = collect.extract_links(CSRC_SOURCE, self._html(href=href), KEYWORDS)
        self.assertEqual(rows[0]["published_at"], day.strftime("%Y-%m-%d"))

    def test_missing_publish_date_is_left_none_not_faked(self):
        rows = collect.extract_links(CSRC_SOURCE, self._html(), KEYWORDS)
        self.assertIsNone(rows[0]["published_at"])

    def test_title_year_is_not_mistaken_for_publish_date(self):
        soup = BeautifulSoup(
            '<li><a href="/a.shtml">关于2019-01-01号文件的后续安排</a></li>',
            "html.parser",
        )
        anchor = soup.find("a")
        self.assertIsNone(
            collect.resolve_published_at(
                anchor, "/a.shtml", anchor.get_text(" "), today=datetime(2026, 7, 27)
            )
        )

    def test_month_day_without_year_is_parsed(self):
        """证监会要闻列表多数条目只写 07-24 这种月日，不带年份。"""
        got = collect.date_from_month_day("07-24", today=datetime(2026, 7, 29))
        self.assertEqual(got.strftime("%Y-%m-%d"), "2026-07-24")

    def test_month_day_rolls_back_a_year_when_it_would_be_future(self):
        got = collect.date_from_month_day("12-31", today=datetime(2026, 7, 29))
        self.assertEqual(got.strftime("%Y-%m-%d"), "2025-12-31")

    def test_month_day_ignores_number_ranges_in_prose(self):
        """只认"整行就是个日期"，正文里的数字范围不能当日期。"""
        self.assertIsNone(
            collect.date_from_month_day(
                "3-5家公司参与本次试点安排并逐步扩大范围", today=datetime(2026, 7, 29)
            )
        )
        self.assertIsNone(
            collect.date_from_month_day("07-24 来源：中国证监会办公厅发布", today=datetime(2026, 7, 29))
        )

    def test_neighbour_row_date_does_not_leak_into_this_row(self):
        """爬父容器会看到兄弟条目的日期，本行自己写了月日就必须用自己的。"""
        soup = BeautifulSoup(
            "<ul>"
            '<li><a href="/a.shtml">上一条公告</a><span>2026-07-22</span></li>'
            '<li><a href="/b.shtml">证监会同意热轧卷板、不锈钢期权注册</a><span>07-24</span></li>'
            "</ul>",
            "html.parser",
        )
        anchor = soup.find_all("a")[1]
        got = collect.date_from_neighbourhood(
            anchor, "证监会同意热轧卷板、不锈钢期权注册", today=datetime(2026, 7, 29)
        )
        self.assertEqual(got.strftime("%Y-%m-%d"), "2026-07-24")

    def test_old_date_is_returned_not_discarded_as_unknown(self):
        """曾有 3 年上限，把解析对的 2021-12-03 判成"没有日期"，下游再兜底成今天。

        护栏于是让 4.6 年前的旧闻变年轻了。旧日期照收，交给过期机制淘汰。
        """
        soup = BeautifulSoup(
            '<li><a href="/a.shtml">试点公告</a><span>2021-12-03</span></li>',
            "html.parser",
        )
        anchor = soup.find("a")
        got = collect.resolve_published_at(
            anchor, "/a.shtml", "试点公告", today=datetime(2026, 7, 29)
        )
        self.assertIsNotNone(got)
        self.assertEqual(got.strftime("%Y-%m-%d"), "2021-12-03")

    def test_future_dates_are_rejected(self):
        soup = BeautifulSoup(
            '<li><a href="/a.shtml">试点公告</a><span>2027-01-01</span></li>',
            "html.parser",
        )
        anchor = soup.find("a")
        self.assertIsNone(
            collect.resolve_published_at(
                anchor, "/a.shtml", "试点公告", today=datetime(2026, 7, 27)
            )
        )


class EstimatedDateDecayTests(unittest.TestCase):
    def _event(self, published_at):
        return {
            "raw_id": "csrc-1",
            "source": "证监会",
            "source_rank": "S",
            "title": TITLE,
            "url": "https://www.csrc.gov.cn/a.shtml",
            "published_at": published_at,
        }

    def test_event_without_publish_date_falls_back_to_collected_at(self):
        """源站没给日期时用抓取日期顶上，并标记 estimated（大亨 2026-07-29 决定）。

        近似的前提是源站是滚动列表；对停更归档页这么干会造出不死僵尸，
        所以标记必须留下——score 靠它把权重压到 0.5。
        """
        raw = self._event(None)
        raw["collected_at"] = "2026-07-20 09:00:00"
        events, skipped = extract.extract_events([raw])
        self.assertEqual(skipped, [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["published_at"], "2026-07-20")
        self.assertTrue(events[0]["published_at_estimated"])

    def test_event_without_any_date_at_all_is_excluded(self):
        """连抓取时间都没有才排除——绝不用"今天"顶替。"""
        events, skipped = extract.extract_events([self._event(None)])
        self.assertEqual(events, [])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["title"], TITLE)

    def test_event_with_publish_date_is_kept(self):
        events, skipped = extract.extract_events([self._event("2026-07-10")])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["published_at"], "2026-07-10")
        self.assertFalse(events[0]["published_at_estimated"])
        self.assertEqual(skipped, [])

    def test_old_but_real_date_is_kept_and_left_to_expire(self):
        """2026-07-29 的病根：真实旧日期被年龄护栏当脏数据丢弃，再被兜底成今天。

        4.6 年前的证监会试点公告因此天天以"今天发布"重生。旧日期必须照收，
        由半衰期/过期机制淘汰——那才是它该干的活。
        """
        events, skipped = extract.extract_events([self._event("2021-12-03")])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["published_at"], "2021-12-03")
        self.assertLess(events[0]["expires_at"], "2022-06-01")
        self.assertEqual(skipped, [])

    def test_estimated_date_never_gets_full_weight(self):
        """核心回归：日期存疑的事件不能天天满权重挂着。"""
        as_of = datetime(2026, 7, 27)
        event = {
            "direction": "positive",
            "evidence_strength": 3,
            "policy_action": "pilot",
            "sources": [{"source_rank": "S"}],
            "published_at": as_of.strftime("%Y-%m-%d"),
            "published_at_estimated": True,
            "expires_at": "2026-09-25",
            "half_life_days": 20,
        }
        self.assertEqual(score.decay_multiplier(event, as_of), 0.5)

        event["published_at_estimated"] = False
        self.assertEqual(score.decay_multiplier(event, as_of), 1.0)

    def test_known_date_still_decays_by_half_life(self):
        event = {
            "direction": "positive",
            "evidence_strength": 3,
            "policy_action": "pilot",
            "sources": [{"source_rank": "S"}],
            "published_at": "2026-07-01",
            "expires_at": "2026-12-31",
            "half_life_days": 10,
        }
        self.assertEqual(score.decay_multiplier(event, datetime(2026, 7, 6)), 1.0)
        self.assertEqual(score.decay_multiplier(event, datetime(2026, 7, 16)), 0.5)
        self.assertEqual(score.decay_multiplier(event, datetime(2026, 8, 16)), 0.25)

    def test_aggregated_event_exposes_publish_date_state(self):
        events = [
            {
                "event_id": "1",
                "title": TITLE,
                "themes": ["证券"],
                "direction": "positive",
                "evidence_strength": 3,
                "policy_action": "pilot",
                "sources": [{"source_rank": "S"}],
                "published_at": "2026-07-27",
                "published_at_estimated": True,
                "expires_at": "2026-09-25",
                "half_life_days": 20,
            }
        ]
        result = score.aggregate_deltas(events, datetime(2026, 7, 27))
        payload = result["证券"]["events"][0]
        self.assertEqual(payload["published_at"], "2026-07-27")
        self.assertTrue(payload["published_at_estimated"])
        self.assertEqual(payload["effective_delta"], 0.5)


class AIClassifyTests(unittest.TestCase):
    """AI 归类（X-Plan.md 模块11）。重点守两件事：不越权、失败必须吭声。"""

    def _raw(self, raw_id, title, url="https://x/a.htm"):
        return {"raw_id": raw_id, "source": "证监会政策法规", "source_rank": "S",
                "title": title, "url": url, "published_at": "2026-07-29"}

    def test_prefilter_drops_sectors_without_etf(self):
        """AI算力/大消费这类没有对应 ETF 的板块不送审——判了也影响不了任何操作。"""
        from policy_research import ai_classify
        cfg = extract.load_theme_config()
        rows = [self._raw("a", "证监会同意开展证券公司业务试点"),
                self._raw("b", "商务部关于开展绿色消费试点工作的通知")]
        items = ai_classify.prefilter(rows, extract.map_themes, cfg, ["证券"])
        self.assertEqual([i["id"] for i in items], ["a"])
        self.assertEqual(items[0]["candidate_sectors"], ["证券"])

    def test_sector_floor_backfills_without_cross_sector_substitution(self):
        """冷门板块靠 AI 自觉会被热门挤掉，保底只补不减，且不许跨板块顶替。"""
        from policy_research import ai_classify
        items = [
            {"id": "s1", "candidate_sectors": ["证券"]},
            {"id": "s2", "candidate_sectors": ["证券"]},
            {"id": "s3", "candidate_sectors": ["证券"]},
            {"id": "c1", "candidate_sectors": ["煤炭"]},
            {"id": "c2", "candidate_sectors": ["煤炭"]},
        ]
        chosen = ai_classify.ensure_sector_floor(items, ["s1", "s2", "s3"])
        self.assertEqual(chosen[:3], ["s1", "s2", "s3"])   # AI 的选择一条不减
        self.assertIn("c1", chosen)
        self.assertIn("c2", chosen)

    def test_pass2_rejects_out_of_bound_and_unknown_sector(self):
        """模型给越界强度或不存在的板块时必须丢掉，不能溢出到下游打分。"""
        from policy_research import ai_classify
        from unittest.mock import patch
        payload = {"results": [
            {"id": "a", "sector": "证券", "direction": "positive", "strength": 99},
            {"id": "b", "sector": "不存在的板块", "direction": "positive", "strength": 3},
            {"id": "c", "sector": "证券", "direction": "neutral", "strength": 3},
            {"id": "zzz", "sector": "证券", "direction": "positive", "strength": 3},
        ]}
        items = [{"id": x, "candidate_sectors": ["证券"], "title": "t", "excerpt": ""}
                 for x in ("a", "b", "c")]
        with patch.object(ai_classify, "_chat",
                          return_value={"ok": True, "text": json.dumps(payload), "error": None}):
            got = ai_classify.pass2_classify(items, ["证券"])
        self.assertTrue(got["ok"])
        self.assertEqual(set(got["results"]), {"a"})      # b越界板块/c中性/zzz非入参 全丢
        self.assertEqual(got["results"]["a"]["strength"], 5)  # 99 夹回 5

    def test_request_disables_thinking_and_forces_json(self):
        """2026-07-29 首次上线就栽在这：thinking 默认开启，推理吃光 max_tokens，
        结果落在 reasoning_content，content 为空 → "第一趟失败: 返回内容为空"。
        """
        from policy_research import ai_classify
        from unittest.mock import patch, MagicMock
        sent = {}

        def fake_post(url, headers=None, json=None, proxies=None, timeout=None):
            sent.update(json)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [
                {"message": {"content": '{"read":[]}'}, "finish_reason": "stop"}]}
            return resp

        with patch.object(ai_classify, "DEEPSEEK_API_KEY", "k"), \
             patch.object(ai_classify.requests, "post", fake_post):
            got = ai_classify._chat("含 JSON 样例的系统提示", "{}", max_tokens=4096)
        self.assertTrue(got["ok"])
        self.assertEqual(sent["thinking"], {"type": "disabled"})
        self.assertEqual(sent["response_format"], {"type": "json_object"})
        self.assertEqual(sent["temperature"], 0)

    def test_empty_content_error_carries_diagnosis(self):
        """空返回的报错必须带 finish_reason / reasoning 长度，否则下次还得再猜一轮。"""
        from policy_research import ai_classify
        from unittest.mock import patch, MagicMock

        def fake_post(url, headers=None, json=None, proxies=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": "", "reasoning_content": "想了很久"},
                             "finish_reason": "length"}],
                "usage": {"completion_tokens": 2048}}
            return resp

        with patch.object(ai_classify, "DEEPSEEK_API_KEY", "k"), \
             patch.object(ai_classify, "DEEPSEEK_RETRIES", 0), \
             patch.object(ai_classify.requests, "post", fake_post):
            got = ai_classify._chat("sys", "{}", max_tokens=2048)
        self.assertFalse(got["ok"])
        self.assertIn("finish_reason=length", got["error"])
        self.assertIn("reasoning=4字", got["error"])
        self.assertIn("completion_tokens=2048", got["error"])

    def test_parse_json_survives_code_fence_and_chatter(self):
        from policy_research import ai_classify
        self.assertEqual(
            ai_classify.parse_json_object('```json\n{"read": ["a"]}\n```'), {"read": ["a"]})
        self.assertEqual(
            ai_classify.parse_json_object('好的，结果如下：\n{"read": ["b"]}\n希望有帮助'),
            {"read": ["b"]})
        self.assertIsNone(ai_classify.parse_json_object("完全不是 JSON"))

    def test_ai_failure_falls_back_to_keyword_with_reason(self):
        """AI 挂了要退回关键词并带上原因——绝不静默（红线 4）。"""
        from policy_research import ai_classify
        from unittest.mock import patch
        cfg = extract.load_theme_config()
        with patch.object(ai_classify, "DEEPSEEK_API_KEY", ""):
            got = ai_classify.classify([self._raw("a", TITLE)], extract.map_themes, cfg)
        self.assertFalse(got["ok"])
        self.assertIn("DEEPSEEK_API_KEY", got["reason"])
        self.assertEqual(got["verdicts"], {})

    def test_only_ai_judged_items_become_events(self):
        """AI 判过的才成为事件；没被选读的是噪音，不能用关键词捞回来。"""
        rows = [self._raw("a", TITLE), self._raw("b", "证监会同意开展证券公司业务试点")]
        verdicts = {"a": {"sector": "证券", "direction": "negative", "strength": 3,
                          "duplicate_of": None}}
        events, _ = extract.extract_events(rows, ai_verdicts=verdicts)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["themes"], ["证券"])
        self.assertEqual(events[0]["direction"], "negative")
        self.assertEqual(events[0]["evidence_strength"], 3)

    def test_none_verdicts_keeps_keyword_path(self):
        """ai_verdicts 为 None 时行为与改造前一致（兜底路径）。"""
        events, _ = extract.extract_events([self._raw("a", TITLE)], ai_verdicts=None)
        self.assertEqual(len(events), 1)


class SourceHealthTests(unittest.TestCase):
    """全源采集失败必须留下痕迹，否则和"今天没新政策"长得一模一样。"""

    def _snapshot(self, tmpdir, payload):
        import json
        from pathlib import Path

        path = Path(tmpdir) / "last_collect.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return Path(tmpdir)

    def test_all_sources_failed_is_recorded(self):
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            snapdir = self._snapshot(
                tmpdir,
                {"source_total": 15, "error_count": 15, "collected_count": 0, "all_sources_failed": True},
            )
            with patch.object(score.common, "SNAPSHOT_DIR", snapdir):
                health = score.source_health()
        self.assertTrue(health["all_sources_failed"])
        self.assertEqual(health["source_total"], 15)

    def test_zero_new_items_is_not_a_failure(self):
        """周末政务站不发文，collected_count 天然为 0，不能当故障。"""
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            snapdir = self._snapshot(
                tmpdir,
                {"source_total": 15, "error_count": 0, "collected_count": 0, "all_sources_failed": False},
            )
            with patch.object(score.common, "SNAPSHOT_DIR", snapdir):
                health = score.source_health()
        self.assertFalse(health["all_sources_failed"])
        self.assertTrue(health["collect_ran"])

    def test_missing_collect_snapshot_is_flagged(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(score.common, "SNAPSHOT_DIR", Path(tmpdir)):
                health = score.source_health()
        self.assertFalse(health["collect_ran"])
        self.assertEqual(health["source_total"], 0)

    def test_confidence_counts_distinct_sources_not_entries(self):
        """同一个源的多份同名文件合并后不能算"多源佐证"。

        证监会一天挂 6 份都叫《行政处罚决定书》的文件，标题归一后并成一条事件，
        按条目数算就成了 6 个源佐证，置信度被凭空抬到 high。
        """
        def row(source, url):
            # 用 B 级源压低 evidence_strength，隔离出"多源佐证"这条提升路径本身，
            # 否则 strength>=4 会先把置信度抬成 high，测不到要测的东西
            return {
                "raw_id": url, "source": source, "source_rank": "B",
                "title": TITLE, "url": url, "published_at": "2026-07-29",
            }

        same, _ = extract.extract_events([row("证券时报", f"/a{i}.htm") for i in range(6)])
        self.assertEqual(len(same), 1)
        self.assertEqual(len(same[0]["sources"]), 6)
        self.assertLess(same[0]["evidence_strength"], 4)
        self.assertNotEqual(same[0]["confidence"], "high")

        cross, _ = extract.extract_events([row("证券时报", "/a.htm"), row("中国证券报", "/b.htm")])
        self.assertEqual(len(cross), 1)
        self.assertEqual(cross[0]["confidence"], "high")

    def test_zero_yield_source_is_recorded(self):
        """HTTP 200 但一条都没抓到的源必须留痕：error_count 永远看不出这种废源。

        2026-07-29 一查，5 个 rank-S 源里 4 个是哑的（JS 跳转壳页、子域名没进白名单），
        全部 HTTP 200、error_count 为 0，从健康度上完全看不出来。
        """
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        sources = {
            "sources": [
                {"id": "dead", "name": "工信部政策文件", "rank": "S", "url": "https://x/", "enabled": True},
                {"id": "live", "name": "证监会政策法规", "rank": "S", "url": "https://y/", "enabled": True},
                {"id": "boom", "name": "超时的源", "rank": "A", "url": "https://z/", "enabled": True},
            ]
        }

        def fake_collect(source, keywords, timeout):
            if source["id"] == "boom":
                raise RuntimeError("connect timeout")
            if source["id"] == "dead":
                return []
            return [{"raw_id": "r1", "title": "t"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(collect.common, "SOURCES_FILE", Path(tmpdir) / "sources.json"), \
                 patch.object(collect.common, "RAW_DIR", Path(tmpdir)), \
                 patch.object(collect.common, "SNAPSHOT_DIR", Path(tmpdir)), \
                 patch.object(collect.common, "load_json", lambda path, default=None: sources if str(path).endswith("sources.json") else default), \
                 patch.object(collect.common, "ROOT", Path(tmpdir)), \
                 patch.object(collect, "load_keywords", lambda: {}), \
                 patch.object(collect, "collect_source", fake_collect):
                snapshot = collect.collect_all()

        # 抓 0 条和抓取失败是两回事：后者已经进 errors，不该在这里重复报
        self.assertEqual(snapshot["zero_yield_sources"], ["工信部政策文件"])
        self.assertEqual(snapshot["error_count"], 1)
        self.assertEqual(snapshot["source_total"], 3)
        self.assertIsNone(snapshot["per_source"]["boom"]["matched"])

    def test_collect_exit_code_only_trips_on_total_failure(self):
        from unittest.mock import patch

        def exit_code(snapshot):
            # main() 会 parse_args()，unittest 下 sys.argv 带着测试名，必须清掉
            with patch.object(sys, "argv", ["collect_policy_news.py"]), patch.object(
                collect, "collect_all", return_value=snapshot
            ):
                return collect.main()

        self.assertEqual(
            exit_code({"collected_count": 0, "error_count": 15, "source_total": 15, "all_sources_failed": True}), 1
        )
        self.assertEqual(
            exit_code({"collected_count": 0, "error_count": 2, "source_total": 15, "all_sources_failed": False}), 0
        )

    def test_timeout_source_does_not_hide_other_sources(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        sources = {
            "sources": [
                {"id": "slow", "name": "超时源", "rank": "A", "url": "https://slow.example/", "enabled": True},
                {"id": "live", "name": "正常源", "rank": "S", "url": "https://live.example/", "enabled": True},
            ]
        }

        def fake_collect(source, keywords, timeout):
            if source["id"] == "slow":
                raise TimeoutError("request timed out")
            return [{"raw_id": "live-1", "title": "正常条目"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.dict(os.environ, {"POLICY_HTTP_CONCURRENCY": "2"}), \
                 patch.object(collect.common, "SOURCES_FILE", root / "sources.json"), \
                 patch.object(collect.common, "RAW_DIR", root), \
                 patch.object(collect.common, "SNAPSHOT_DIR", root), \
                 patch.object(collect.common, "ROOT", root), \
                 patch.object(collect.common, "load_json", lambda path, default=None: sources if str(path).endswith("sources.json") else default), \
                 patch.object(collect, "load_keywords", lambda: {}), \
                 patch.object(collect, "collect_source", fake_collect):
                snapshot = collect.collect_all()

        self.assertEqual(snapshot["collected_count"], 1)
        self.assertFalse(snapshot["all_sources_failed"])
        self.assertEqual(snapshot["per_source"]["live"]["matched"], 1)
        self.assertEqual(snapshot["per_source"]["slow"]["matched"], None)
        self.assertEqual(snapshot["errors"][0]["source_id"], "slow")
        self.assertIn("timed out", snapshot["errors"][0]["error"])

    def test_all_sources_failed_is_recorded_by_collect(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        sources = {
            "sources": [
                {"id": "a", "name": "源A", "rank": "A", "url": "https://a.example/", "enabled": True},
                {"id": "b", "name": "源B", "rank": "A", "url": "https://b.example/", "enabled": True},
            ]
        }

        def fake_collect(source, keywords, timeout):
            raise TimeoutError(f"{source['id']} timed out")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(collect.common, "SOURCES_FILE", root / "sources.json"), \
                 patch.object(collect.common, "RAW_DIR", root), \
                 patch.object(collect.common, "SNAPSHOT_DIR", root), \
                 patch.object(collect.common, "ROOT", root), \
                 patch.object(collect.common, "load_json", lambda path, default=None: sources if str(path).endswith("sources.json") else default), \
                 patch.object(collect, "load_keywords", lambda: {}), \
                 patch.object(collect, "collect_source", fake_collect):
                snapshot = collect.collect_all()

        self.assertTrue(snapshot["all_sources_failed"])
        self.assertEqual(snapshot["error_count"], 2)
        self.assertEqual([row["source_id"] for row in snapshot["errors"]], ["a", "b"])


class ConcurrencyDeterminismTests(unittest.TestCase):
    def test_collect_merges_in_config_order_and_dedupes_in_that_order(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        sources = {
            "sources": [
                {"id": "first", "name": "第一源", "rank": "A", "url": "https://one.example/", "enabled": True},
                {"id": "second", "name": "第二源", "rank": "A", "url": "https://two.example/", "enabled": True},
                {"id": "third", "name": "第三源", "rank": "A", "url": "https://three.example/", "enabled": True},
            ]
        }
        delays = {"first": 0.03, "second": 0.001, "third": 0.015}

        def fake_collect(source, keywords, timeout):
            time.sleep(delays[source["id"]])
            if source["id"] == "second":
                return [{"raw_id": "duplicate", "title": "第二源重复条目"}]
            if source["id"] == "first":
                return [{"raw_id": "duplicate", "title": "第一源条目"}]
            return [{"raw_id": "third-only", "title": "第三源条目"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(collect.common, "SOURCES_FILE", root / "sources.json"), \
                 patch.object(collect.common, "RAW_DIR", root), \
                 patch.object(collect.common, "SNAPSHOT_DIR", root), \
                 patch.object(collect.common, "ROOT", root), \
                 patch.object(collect.common, "load_json", lambda path, default=None: sources if str(path).endswith("sources.json") else default), \
                 patch.object(collect, "load_keywords", lambda: {}), \
                 patch.object(collect, "collect_source", fake_collect):
                snapshot = collect.collect_all()
                rows = common.read_jsonl(root / f"{common.month_key()}.jsonl")

        self.assertEqual(list(snapshot["per_source"]), ["first", "second", "third"])
        self.assertEqual([row["raw_id"] for row in rows], ["duplicate", "third-only"])
        self.assertEqual(rows[0]["title"], "第一源条目")

    def test_per_domain_limit_is_respected_and_can_be_configured(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        sources = {
            "sources": [
                {"id": f"same-{idx}", "name": f"同域{idx}", "rank": "A", "url": f"https://news.example/item-{idx}", "enabled": True}
                for idx in range(6)
            ]
        }
        lock = threading.Lock()
        active = {"total": 0, "domain": 0, "max_total": 0, "max_domain": 0}

        def fake_collect(source, keywords, timeout):
            with lock:
                active["total"] += 1
                active["domain"] += 1
                active["max_total"] = max(active["max_total"], active["total"])
                active["max_domain"] = max(active["max_domain"], active["domain"])
            time.sleep(0.01)
            with lock:
                active["total"] -= 1
                active["domain"] -= 1
            return [{"raw_id": source["id"], "title": source["id"]}]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.dict(os.environ, {
                "POLICY_HTTP_CONCURRENCY": "4",
                "POLICY_HTTP_PER_DOMAIN_CONCURRENCY": "2",
            }), \
                 patch.object(collect.common, "SOURCES_FILE", root / "sources.json"), \
                 patch.object(collect.common, "RAW_DIR", root), \
                 patch.object(collect.common, "SNAPSHOT_DIR", root), \
                 patch.object(collect.common, "ROOT", root), \
                 patch.object(collect.common, "load_json", lambda path, default=None: sources if str(path).endswith("sources.json") else default), \
                 patch.object(collect, "load_keywords", lambda: {}), \
                 patch.object(collect, "collect_source", fake_collect):
                collect.collect_all()

        self.assertGreater(active["max_total"], 1)
        self.assertLessEqual(active["max_total"], 4)
        self.assertLessEqual(active["max_domain"], 2)

    def test_body_failures_keep_titles_and_do_not_cross_wire_excerpts(self):
        from unittest.mock import patch
        from policy_research import ai_classify

        rows = [
            {"raw_id": "a", "source": "源", "source_rank": "S", "title": "事件A", "url": "https://a.example/a"},
            {"raw_id": "b", "source": "源", "source_rank": "S", "title": "事件B", "url": "https://b.example/b"},
        ]
        order = []
        captured = []

        def fake_pass1(items, sectors):
            order.append("pass1")
            return {"ok": True, "read": ["b", "a"], "error": None}

        def fake_fetch(url):
            time.sleep(0.02 if url.endswith("/a") else 0.001)
            return "" if url.endswith("/a") else "正文B"

        def fake_pass2(items, sectors):
            order.append("pass2")
            captured.extend(items)
            return {
                "ok": True,
                "results": {
                    item["id"]: {"sector": "证券", "direction": "positive", "strength": 1, "duplicate_of": None}
                    for item in items
                },
                "error": None,
            }

        with patch.object(ai_classify, "DEEPSEEK_API_KEY", "test-key"), \
             patch.object(ai_classify, "etf_sectors", return_value=["证券"]), \
             patch.object(ai_classify, "pass1_pick", fake_pass1), \
             patch.object(ai_classify, "fetch_excerpt", fake_fetch), \
             patch.object(ai_classify, "pass2_classify", fake_pass2):
            got = ai_classify.classify(rows, lambda title, config: ["证券"], {})

        by_id = {item["id"]: item for item in captured}
        self.assertEqual(order[0], "pass1")
        self.assertEqual(order[-1], "pass2")
        self.assertEqual([item["id"] for item in captured], ["b", "a"])
        self.assertEqual(by_id["a"]["excerpt"], "")
        self.assertEqual(by_id["a"]["title"], "事件A")
        self.assertEqual(by_id["b"]["excerpt"], "正文B")
        self.assertEqual(got["stats"]["fetched"], 1)


class PipelineStageTimingTests(unittest.TestCase):
    def test_run_extract_keeps_timing_out_of_snapshot_contract(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from policy_research import extract_policy_events as extract_module

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            timings = {}
            with patch.object(extract_module.common, "RAW_DIR", root), \
                 patch.object(extract_module.common, "EVENT_DIR", root), \
                 patch.object(extract_module.common, "SNAPSHOT_DIR", root), \
                 patch.object(extract_module.common, "ROOT", root), \
                 patch.object(extract_module, "load_theme_config", return_value={"themes": {}}), \
                 patch.object(extract_module.common, "read_recent_jsonl", return_value=[]), \
                 patch.object(extract_module.common, "append_jsonl", return_value=0), \
                 patch.object(extract_module.common, "save_json"):
                result = extract_module.run_extract(use_ai=False, timings=timings)

        self.assertEqual(timings, {"ai_pass1": 0.0, "body_fetch": 0.0, "ai_pass2": 0.0})
        self.assertNotIn("timings", result)


if __name__ == "__main__":
    unittest.main()
