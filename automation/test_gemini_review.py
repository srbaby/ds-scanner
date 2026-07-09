#!/usr/bin/env python3

import unittest
from unittest.mock import patch

import gemini_review
import generate_dashboard


class Response:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


class GeminiReviewTests(unittest.TestCase):
    def test_daily_dashboard_disables_all_ai_calls(self):
        with patch.object(generate_dashboard, "AI_PROVIDER", "none"), patch.object(
            generate_dashboard, "call_gemini"
        ) as gemini_call, patch.object(
            generate_dashboard, "call_deepseek"
        ) as deepseek_call:
            provider, result = generate_dashboard.call_ai_audit("report", {})
        self.assertEqual(provider, "none")
        self.assertFalse(result["enabled"])
        self.assertTrue(result["ok"])
        gemini_call.assert_not_called()
        deepseek_call.assert_not_called()

    def test_generate_content_payload_and_audit_contract(self):
        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return Response(
                data={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": "【审计结论】\nPASS\n【发现】\n- 无\n【解释】\n一致"
                                    }
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ]
                }
            )

        with patch.object(gemini_review, "GEMINI_API_KEY", "test-key"), patch.object(
            gemini_review.requests, "post", side_effect=fake_post
        ):
            result = gemini_review.call_gemini("report", {"operations": []})

        self.assertTrue(result["ok"])
        self.assertIn("gemini-3.5-flash:generateContent", captured["url"])
        self.assertEqual(
            captured["kwargs"]["headers"]["x-goog-api-key"],
            "test-key",
        )
        self.assertIn(
            "扫描器结构化权威决策",
            captured["kwargs"]["json"]["contents"][0]["parts"][0]["text"],
        )

    def test_api_failure_returns_non_throwing_result(self):
        with patch.object(gemini_review, "GEMINI_API_KEY", "test-key"), patch.object(
            gemini_review, "GEMINI_RETRIES", 0
        ), patch.object(
            gemini_review.requests,
            "post",
            return_value=Response(status_code=503, text="busy"),
        ):
            result = gemini_review.call_gemini("report", {})
        self.assertFalse(result["ok"])
        self.assertIn("HTTP 503", result["error"])

    def test_missing_key_is_safe_failure(self):
        with patch.object(gemini_review, "GEMINI_API_KEY", ""):
            result = gemini_review.call_gemini("report", {})
        self.assertFalse(result["ok"])
        self.assertIn("GEMINI_API_KEY", result["error"])

    def test_dashboard_catches_ai_module_crash(self):
        with patch.object(generate_dashboard, "AI_PROVIDER", "gemini"), patch.object(
            generate_dashboard, "call_gemini", side_effect=RuntimeError("offline")
        ):
            provider, result = generate_dashboard.call_ai_audit("report", {})
        self.assertEqual(provider, "gemini")
        self.assertFalse(result["ok"])
        self.assertIn("AI审计模块异常", result["error"])


if __name__ == "__main__":
    unittest.main()
