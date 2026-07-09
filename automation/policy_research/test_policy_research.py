#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

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
        events = extract.extract_events(rows)
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
        self.assertEqual(extract.extract_events(rows), [])
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


if __name__ == "__main__":
    unittest.main()



