#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch

import send_report
from versioning import METHODOLOGY_VERSION


class SendReportTests(unittest.TestCase):
    def dashboard(self, text=None, ok=True, error=None):
        text = text or "\n".join(
            [
                "【审计结论】",
                "PASS",
                "【发现】",
                "- 无",
                "【解释】",
                "扫描器决策一致。",
            ]
        )
        return {
            "generated_at": "2026-07-09 14:52:00",
            "methodology_version": "v3.1",
            "decision": {
                "operations": [
                    {
                        "id": "OP-01",
                        "action": "BUY",
                        "symbol": "sh588800",
                        "name": "科创100ETF",
                        "current_target_position_pct": 0,
                        "target_position_pct": 10,
                        "adjustment_pct": 10,
                        "rule_code": "B_INITIAL_BUY",
                        "signal_grade": "B",
                        "reason": "普通信号首次建仓",
                        "metrics": {"score": 76},
                        "execution_guidance": {
                            "reference_price": 2.328,
                            "target_amount": 19315.56,
                            "recommended_shares": 8200,
                            "recommended_lots": 82,
                            "estimated_amount": 19089.60,
                        },
                    }
                ]
            },
            "audit": {"ok": ok, "text": text if ok else "", "error": error},
            "ai": {"ok": ok, "text": text if ok else "", "error": error},
        }

    def test_main_bark_payload_is_v3_and_has_no_gemini_message(self):
        payload = send_report.build_payload(
            "扫描报告正文",
            "2026-07-09",
            self.dashboard(),
        )
        self.assertIn(METHODOLOGY_VERSION, payload["title"])
        self.assertNotIn("Gemini", payload["title"])
        self.assertIn("OP-01 BUY sh588800", payload["body"])
        self.assertIn("8,200份（82手）", payload["body"])
        self.assertNotIn("扫描报告正文", payload["body"])
        self.assertEqual(payload["group"], "X-Plan扫描")
        # 不能带 url：带了点通知就被 iOS 丢进浏览器，而实际要去的是桌面 web clip。
        self.assertNotIn("url", payload)
        # 看板地址仍以纯文本留在 body 末尾，作为显式入口。
        self.assertIn("https://stock.bailuzun.com", payload["body"])

    def test_long_multibyte_summary_stays_under_byte_budget(self):
        text = self.dashboard()["ai"]["text"] + "\n⚠️ " + ("超长异常说明" * 2000)
        payload = send_report.build_payload("原始报告" * 5000, dashboard_data=self.dashboard(text))
        self.assertLessEqual(
            len(payload["body"].encode("utf-8")),
            send_report.MAX_BARK_BODY_BYTES,
        )
        self.assertLess(len(json_bytes(payload)), 4096)

    def test_ai_failure_keeps_scanner_operation(self):
        report = "不可进入推送的超长原始报告" * 1000
        payload = send_report.build_payload(
            report,
            dashboard_data=self.dashboard(ok=False, error="Gemini HTTP 503"),
        )
        self.assertIn("OP-01 BUY sh588800", payload["body"])
        self.assertIn("AI审计不可用", payload["body"])
        self.assertIn("Gemini HTTP 503", payload["body"])
        self.assertNotIn(report[:100], payload["body"])

    def test_all_recipients_are_attempted_before_failure(self):
        calls = []

        class Response:
            def __init__(self, status_code):
                self.status_code = status_code
                self.text = "ok" if status_code == 200 else "failed"

            def raise_for_status(self):
                if self.status_code != 200:
                    raise RuntimeError(f"HTTP {self.status_code}")

        def fake_post(url, **kwargs):
            calls.append(url)
            return Response(500 if url.endswith("first") else 200)

        with self.assertRaises(RuntimeError):
            send_report.send_bark(
                "report",
                self.dashboard(),
                post=fake_post,
                keys=["first", "second"],
            )
        self.assertEqual(len(calls), 2)

    def test_default_delivery_ignores_wife_key(self):
        calls = []

        class Response:
            status_code = 200
            text = "ok"

            def raise_for_status(self):
                return None

        def fake_post(url, **kwargs):
            calls.append(url)
            return Response()

        with patch.dict(
            send_report.os.environ,
            {"BARK_KEY": "main-only", "BARK_KEY_WIFE": "must-not-send"},
            clear=False,
        ):
            send_report.send_bark(
                "report",
                self.dashboard(),
                post=fake_post,
            )
        self.assertEqual(calls, ["https://api.day.app/main-only"])

    def test_missing_dashboard_uses_decision_file_fallback(self):
        decision = self.dashboard()["decision"]
        recovered = send_report.dashboard_with_decision_fallback(None, decision)
        body = send_report.build_bark_body("report", recovered)
        self.assertIn("OP-01 BUY sh588800", body)
        self.assertIn("AI审计不可用", body)

    def test_disabled_ai_adds_no_audit_noise_to_bark(self):
        dashboard = self.dashboard()
        dashboard["audit"] = {
            "enabled": False,
            "ok": True,
            "text": "",
            "error": None,
        }
        body = send_report.build_bark_body("report", dashboard)
        self.assertIn("OP-01 BUY sh588800", body)
        self.assertNotIn("AI审计", body)

    def test_bark_body_flags_degraded(self):
        dashboard = self.dashboard()
        dashboard["decision"]["portfolio"] = {
            "health": "degraded",
            "data_gap_holdings": ["512690", "588800"],
        }
        body = send_report.build_bark_body("扫描报告正文", dashboard)
        self.assertTrue(body.startswith("🔴 数据降级 · 止损未评估"))
        self.assertIn("止损未评估", body)
        self.assertIn("512690", body)
        self.assertIn("588800", body)

        payload = send_report.build_payload(
            "扫描报告正文", "2026-07-10", dashboard_data=dashboard
        )
        self.assertEqual(
            payload["title"],
            f"🔴 数据降级 X-Plan {METHODOLOGY_VERSION} 波段扫描 2026-07-10",
        )

    def test_bark_body_flags_policy_not_applied(self):
        """政策步骤是 continue-on-error，Actions 全绿；Bark 是唯一能吼出来的地方。

        2026-07-27~29 政策链路停摆 2 天没人发现，就是因为这行不存在。
        """
        dashboard = self.dashboard()
        dashboard["decision"]["policy"] = {
            "ok": False,
            "as_of": None,
            "reason": "政策数据文件缺失",
            "applied": {},
        }
        body = send_report.build_bark_body("扫描报告正文", dashboard)
        self.assertIn("⚠️ 政策未计入：政策数据文件缺失", body)
        self.assertIn("纯手工 base 分", body)

    def test_bark_body_confirms_policy_applied(self):
        """有生效调整时给正向确认，「政策正常」才和「这行忘了加」可区分。"""
        dashboard = self.dashboard()
        dashboard["decision"]["policy"] = {
            "ok": True,
            "as_of": "2026-07-29",
            "reason": "",
            "applied": {"证券": 1, "半导体": -2},
        }
        body = send_report.build_bark_body("扫描报告正文", dashboard)
        self.assertIn("🏛️ 政策已计入 2026-07-29", body)
        self.assertIn("证券+1", body)
        self.assertIn("半导体-2", body)

    def test_bark_body_flags_keyword_fallback(self):
        """AI 归类退回关键词兜底必须吭声，否则又是一次静默降级。"""
        dashboard = self.dashboard()
        dashboard["decision"]["policy"] = {
            "ok": True, "as_of": "2026-07-29", "reason": "", "applied": {"证券": 1},
            "classifier": "keyword", "classifier_reason": "第二趟失败: HTTP 429",
        }
        body = send_report.build_bark_body("扫描报告正文", dashboard)
        self.assertIn("政策归类由关键词兜底", body)
        self.assertIn("HTTP 429", body)
        self.assertIn("🏛️ 政策已计入", body)

    def test_bark_body_quiet_when_ai_classifier_worked(self):
        dashboard = self.dashboard()
        dashboard["decision"]["policy"] = {
            "ok": True, "as_of": "2026-07-29", "reason": "", "applied": {"证券": 1},
            "classifier": "ai", "classifier_reason": "",
        }
        body = send_report.build_bark_body("扫描报告正文", dashboard)
        self.assertNotIn("关键词兜底", body)

    def test_bark_body_stays_quiet_without_policy_block(self):
        """崩溃降级路径写的最小 decision.json 没有 policy 键，不能因此炸掉推送。"""
        dashboard = self.dashboard()
        self.assertNotIn("policy", dashboard["decision"])
        body = send_report.build_bark_body("扫描报告正文", dashboard)
        self.assertNotIn("政策未计入", body)
        self.assertNotIn("政策已计入", body)

    def test_bark_body_stays_quiet_when_policy_ok_but_nothing_moved(self):
        dashboard = self.dashboard()
        dashboard["decision"]["policy"] = {
            "ok": True,
            "as_of": "2026-07-29",
            "reason": "",
            "applied": {},
        }
        body = send_report.build_bark_body("扫描报告正文", dashboard)
        self.assertNotIn("政策已计入", body)
        self.assertNotIn("政策未计入", body)

    def test_bark_title_has_three_distinct_states(self):
        today = "2026-07-10"
        ok_title = send_report.build_payload(
            "report", today, dashboard_data=self.dashboard()
        )["title"]

        degraded = self.dashboard()
        degraded["decision"]["portfolio"] = {
            "health": "degraded",
            "data_gap_holdings": ["512690"],
        }
        degraded_title = send_report.build_payload(
            "report", today, dashboard_data=degraded
        )["title"]

        crashed = self.dashboard()
        crashed["decision"]["portfolio"] = {"health": "crashed", "data_gap_holdings": []}
        crashed_title = send_report.build_payload(
            "report", today, dashboard_data=crashed
        )["title"]

        self.assertTrue(ok_title.startswith("📡"))
        self.assertTrue(degraded_title.startswith("🔴 数据降级"))
        self.assertTrue(crashed_title.startswith("🔴 扫描崩溃"))
        self.assertEqual(len({ok_title, degraded_title, crashed_title}), 3)
        # 不应出现多个 emoji 图标堆叠成串（如 "🔴 📡"）
        for title in (ok_title, degraded_title, crashed_title):
            self.assertNotIn("🔴 📡", title)


def json_bytes(payload):
    import json

    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
