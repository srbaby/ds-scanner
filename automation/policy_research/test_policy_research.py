#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bs4 import BeautifulSoup

from policy_research import collect_policy_news as collect
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


if __name__ == "__main__":
    unittest.main()



