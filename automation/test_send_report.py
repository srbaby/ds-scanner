#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

import send_report


class SendReportTests(unittest.TestCase):
    def test_main_bark_payload_is_v3_and_has_no_gemini_message(self):
        payload = send_report.build_payload("扫描报告正文", "2026-07-09")
        self.assertIn("v3.0", payload["title"])
        self.assertNotIn("Gemini", payload["title"])
        self.assertEqual(payload["body"], "扫描报告正文")
        self.assertEqual(payload["group"], "X-Plan扫描")


if __name__ == "__main__":
    unittest.main()
