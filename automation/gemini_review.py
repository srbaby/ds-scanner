# /// script
# dependencies = [
#   "requests",
# ]
# ///

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X-Plan Gemini 审计模块；扫描器始终是唯一决策源。"""

import json
import os
import time
from typing import Dict, Optional
from urllib.parse import quote

import requests

from ai_review import load_prompt, validate_ai_output
from versioning import METHODOLOGY_VERSION, validate_document_versions

PROXIES = {"http": None, "https": None}

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash").strip()
GEMINI_MAX_TOKENS = int(os.environ.get("GEMINI_MAX_TOKENS", "8192"))
GEMINI_RETRIES = int(os.environ.get("GEMINI_RETRIES", "1"))
GEMINI_RETRY_SLEEP_SECONDS = int(
    os.environ.get("GEMINI_RETRY_SLEEP_SECONDS", "20")
)
GEMINI_TIMEOUT_SECONDS = int(os.environ.get("GEMINI_TIMEOUT_SECONDS", "90"))


def _extract_text(data: Dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    return "\n".join(
        str(part.get("text") or "").strip()
        for part in parts
        if isinstance(part, dict) and part.get("text")
    ).strip()


def call_gemini(report_text: str, decision: Optional[Dict] = None) -> Dict:
    validate_document_versions()
    if not GEMINI_API_KEY:
        return {
            "ok": False,
            "model": GEMINI_MODEL,
            "text": "",
            "error": "未配置 GEMINI_API_KEY，跳过AI审计",
        }

    prompt = load_prompt()
    if not prompt:
        return {
            "ok": False,
            "model": GEMINI_MODEL,
            "text": "",
            "error": "未找到 Prompt.md",
        }

    system_instruction = (
        "你是 X-Plan 的独立审计员。扫描器是唯一决策源。"
        "你只能复核数学、规则一致性和数据异常，不得重新评分、改等级、改仓位或另造操作清单。\n\n"
        f"{prompt}"
    )
    user_content = report_text
    if decision:
        user_content += "\n\n【扫描器结构化权威决策】\n" + json.dumps(
            decision, ensure_ascii=False
        )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(GEMINI_MODEL, safe='')}:generateContent"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [
            {"role": "user", "parts": [{"text": user_content}]},
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": GEMINI_MAX_TOKENS,
        },
    }

    retryable_status = {429, 500, 502, 503, 504}
    max_attempts = max(1, GEMINI_RETRIES + 1)
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                url,
                headers={
                    "x-goog-api-key": GEMINI_API_KEY,
                    "Content-Type": "application/json",
                },
                json=payload,
                proxies=PROXIES,
                timeout=GEMINI_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            last_error = f"请求异常: {exc}"
            if attempt < max_attempts:
                time.sleep(GEMINI_RETRY_SLEEP_SECONDS)
                continue
            return {
                "ok": False,
                "model": GEMINI_MODEL,
                "text": "",
                "error": last_error,
            }

        if response.status_code != 200:
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
            if response.status_code in retryable_status and attempt < max_attempts:
                time.sleep(GEMINI_RETRY_SLEEP_SECONDS)
                continue
            return {
                "ok": False,
                "model": GEMINI_MODEL,
                "text": "",
                "error": last_error,
            }

        try:
            data = response.json()
            text = _extract_text(data)
            if not text:
                finish_reason = (
                    (data.get("candidates") or [{}])[0].get("finishReason")
                    or "UNKNOWN"
                )
                return {
                    "ok": False,
                    "model": GEMINI_MODEL,
                    "text": "",
                    "error": f"Gemini返回内容为空，finishReason={finish_reason}",
                }
            format_error = validate_ai_output(text)
            if format_error:
                return {
                    "ok": False,
                    "model": GEMINI_MODEL,
                    "text": text,
                    "error": f"{METHODOLOGY_VERSION} 输出契约校验失败: {format_error}",
                }
            return {
                "ok": True,
                "model": GEMINI_MODEL,
                "text": text,
                "error": None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "model": GEMINI_MODEL,
                "text": "",
                "error": f"解析响应失败: {exc}",
            }

    return {
        "ok": False,
        "model": GEMINI_MODEL,
        "text": "",
        "error": last_error,
    }
