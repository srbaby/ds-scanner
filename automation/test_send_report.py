#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

import send_report


class SendReportTests(unittest.TestCase):
    def dashboard(self, text=None, ok=True, error=None):
        text = text or "\n".join(
            [
                "【执行窗口】",
                "14:53-15:00 执行，未成交走盘后固定价格。",
                "【操作清单】",
                "| 操作编号 | 类型 | 代码 | 名称 | 当前目标仓位% | 今日目标仓位% | 调整仓位 | 规则代码 | 信号等级 | 中文操作依据 | 关键指标 |",
                "|---|---|---|---|---|---|---|---|---|---|---|",
                "| OP-01 | BUY | sh588800 | 科创100ETF | 0% | 10% | +10% | B_INITIAL_BUY | B | 普通信号首次建仓 | 评分76 |",
            ]
        )
        return {
            "generated_at": "2026-07-09 14:52:00",
            "methodology_version": "v3.0",
            "ai": {"ok": ok, "text": text if ok else "", "error": error},
        }

    def test_main_bark_payload_is_v3_and_has_no_gemini_message(self):
        payload = send_report.build_payload(
            "扫描报告正文",
            "2026-07-09",
            self.dashboard(),
        )
        self.assertIn("v3.0", payload["title"])
        self.assertNotIn("Gemini", payload["title"])
        self.assertIn("OP-01 BUY sh588800", payload["body"])
        self.assertNotIn("扫描报告正文", payload["body"])
        self.assertEqual(payload["group"], "X-Plan扫描")
        self.assertEqual(payload["url"], "https://stock.bailuzun.com")

    def test_long_multibyte_summary_stays_under_byte_budget(self):
        text = self.dashboard()["ai"]["text"] + "\n⚠️ " + ("超长异常说明" * 2000)
        payload = send_report.build_payload("原始报告" * 5000, dashboard_data=self.dashboard(text))
        self.assertLessEqual(
            len(payload["body"].encode("utf-8")),
            send_report.MAX_BARK_BODY_BYTES,
        )
        self.assertLess(len(json_bytes(payload)), 4096)

    def test_ai_failure_sends_short_warning_not_full_report(self):
        report = "不可进入推送的超长原始报告" * 1000
        payload = send_report.build_payload(
            report,
            dashboard_data=self.dashboard(ok=False, error="DeepSeek HTTP 503"),
        )
        self.assertIn("AI 分析失败", payload["body"])
        self.assertIn("DeepSeek HTTP 503", payload["body"])
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


def json_bytes(payload):
    import json

    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
