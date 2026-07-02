# /// script
# dependencies = [
#   "requests",
# ]
# ///

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X-Plan Gemini API 可靠性验证
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
读取 Prompt.md + report.txt，调用 Gemini API 做影子验证，并通过 Bark 独立推送结果。

定位：
- 不替代当前正式 DeepSeek 分析；
- 不写入 dashboard.json；
- 不阻塞扫描报告和看板主流程；
- 为未来 Gemini 转正积累可用性证据。

环境变量：
  GEMINI_API_KEY      必填，Google AI Studio / Gemini API Key
  GEMINI_MODEL        可选，默认 gemini-3.5-flash
  BARK_KEY            可选，用于独立推送验证结果
  BARK_KEY_WIFE       可选，同步推送第二接收方
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PROXIES = {"http": None, "https": None}

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT_FILE = os.path.join(ROOT_DIR, "Prompt.md")
REPORT_FILE = os.path.join(ROOT_DIR, "report.txt")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash").strip()
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_TIMEOUT_SECONDS = int(os.environ.get("GEMINI_TIMEOUT_SECONDS", "90"))

BARK_ICON = "https://cdn.jsdelivr.net/gh/srbaby/ds-scanner@main/favicon.png"
ACTION_RE = re.compile(r"^\s*(SELL|BUY|HOLD|SKIP|ADD|WATCH)\s*\|", re.MULTILINE)
TABLE_HEADER = "类型 | 代码 | 名称 | 数量 | 说明"


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _extract_text_from_any(value: Any) -> List[str]:
    texts: List[str] = []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"text", "output_text", "outputText"} and isinstance(child, str):
                texts.append(child)
            else:
                texts.extend(_extract_text_from_any(child))
    elif isinstance(value, list):
        for child in value:
            texts.extend(_extract_text_from_any(child))
    return texts


def _extract_response_text(data: Dict[str, Any]) -> str:
    for key in ("output_text", "outputText"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # Interactions API response shape can evolve; collect likely text fields defensively.
    candidates = _extract_text_from_any(data.get("steps", []))
    if not candidates:
        candidates = _extract_text_from_any(data)
    return "\n".join(t.strip() for t in candidates if t and t.strip()).strip()


def validate_ai_output(text: str) -> Dict[str, Any]:
    action_lines = ACTION_RE.findall(text or "")
    first_action = ""
    for line in (text or "").splitlines():
        if ACTION_RE.match(line):
            first_action = line.strip()
            break

    checks = {
        "non_empty": bool((text or "").strip()),
        "has_action_section": "【操作清单】" in (text or ""),
        "has_table_header": TABLE_HEADER in (text or ""),
        "has_action_line": bool(action_lines),
    }
    warnings = []
    legacy_name = "X-" + "DeepSeek"
    if legacy_name in (text or ""):
        warnings.append("回复仍出现旧系统名")

    return {
        "format_ok": all(checks.values()),
        "checks": checks,
        "action_count": len(action_lines),
        "first_action": first_action,
        "warnings": warnings,
    }


def call_gemini(prompt_text: str, report_text: str) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        return {
            "ok": False,
            "model": GEMINI_MODEL,
            "latency_ms": 0,
            "text": "",
            "error": "未配置 GEMINI_API_KEY",
        }

    payload = {
        "model": GEMINI_MODEL,
        "system_instruction": prompt_text,
        "input": report_text,
        "generation_config": {
            "temperature": 0.2,
        },
    }

    started = time.perf_counter()
    try:
        r = requests.post(
            GEMINI_API_URL,
            headers={
                "x-goog-api-key": GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
            proxies=PROXIES,
            timeout=GEMINI_TIMEOUT_SECONDS,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
    except Exception as e:
        return {
            "ok": False,
            "model": GEMINI_MODEL,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "text": "",
            "error": f"请求异常: {e}",
        }

    if r.status_code != 200:
        return {
            "ok": False,
            "model": GEMINI_MODEL,
            "latency_ms": latency_ms,
            "text": "",
            "error": f"HTTP {r.status_code}: {r.text[:500]}",
        }

    try:
        data = r.json()
    except Exception as e:
        return {
            "ok": False,
            "model": GEMINI_MODEL,
            "latency_ms": latency_ms,
            "text": "",
            "error": f"响应JSON解析失败: {e}",
        }

    text = _extract_response_text(data)
    if not text:
        return {
            "ok": False,
            "model": GEMINI_MODEL,
            "latency_ms": latency_ms,
            "text": "",
            "error": f"Gemini返回内容为空: {json.dumps(data, ensure_ascii=False)[:500]}",
        }

    return {
        "ok": True,
        "model": GEMINI_MODEL,
        "latency_ms": latency_ms,
        "text": text,
        "error": None,
    }


def build_summary(result: Dict[str, Any], validation: Dict[str, Any]) -> Dict[str, str]:
    today = datetime.now().strftime("%Y-%m-%d")
    status_ok = bool(result.get("ok")) and bool(validation.get("format_ok"))
    title = (
        f"✅ X-Plan Gemini API OK {today}"
        if status_ok
        else f"⚠️ X-Plan Gemini API FAIL {today}"
    )

    warning_text = ""
    if validation.get("warnings"):
        warning_text = "\n命名警告：" + "；".join(validation["warnings"])

    if status_ok:
        body = (
            f"模型：{result.get('model')}\n"
            f"耗时：{result.get('latency_ms')} ms\n"
            f"格式验证：通过\n"
            f"动作行数：{validation.get('action_count')}\n"
            f"回复长度：{len(result.get('text') or '')} 字\n"
            f"首条动作：{validation.get('first_action') or '-'}"
            f"{warning_text}"
        )
        level = "active"
    else:
        checks = validation.get("checks", {})
        failed_checks = [name for name, ok in checks.items() if not ok]
        body = (
            f"模型：{result.get('model')}\n"
            f"耗时：{result.get('latency_ms')} ms\n"
            f"API状态：{'成功' if result.get('ok') else '失败'}\n"
            f"格式验证：{'通过' if validation.get('format_ok') else '失败'}\n"
            f"失败检查：{', '.join(failed_checks) if failed_checks else '-'}\n"
            f"动作行数：{validation.get('action_count')}\n"
            f"错误摘要：{result.get('error') or '-'}\n"
            f"首条动作：{validation.get('first_action') or '-'}"
            f"{warning_text}"
        )
        level = "timeSensitive"

    return {"title": title, "body": body, "level": level}


def send_bark(title: str, body: str, level: str) -> None:
    key = os.environ.get("BARK_KEY", "").strip()
    if not key:
        print("⚠️ 未配置 BARK_KEY，跳过Gemini验证Bark推送")
        return

    keys = [key]
    wife_key = os.environ.get("BARK_KEY_WIFE", "").strip()
    if wife_key:
        keys.append(wife_key)

    payload = {
        "title": title,
        "body": body,
        "level": level,
        "group": "X-Plan Gemini验证",
        "badge": 1,
        "icon": BARK_ICON,
    }

    for bark_key in keys:
        try:
            r = requests.post(
                f"https://api.day.app/{bark_key}",
                headers={"Content-Type": "application/json; charset=utf-8"},
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                proxies=PROXIES,
                timeout=30,
            )
            print(f"Bark推送({bark_key[:8]}…) -> {r.status_code}: {r.text}")
            r.raise_for_status()
        except Exception as e:
            print(f"⚠️ Bark推送失败({bark_key[:8]}…): {e}")


def main() -> None:
    try:
        prompt_text = _read_text(PROMPT_FILE)
        report_text = _read_text(REPORT_FILE)
    except Exception as e:
        result = {
            "ok": False,
            "model": GEMINI_MODEL,
            "latency_ms": 0,
            "text": "",
            "error": f"读取Prompt/report失败: {e}",
        }
        validation = validate_ai_output("")
        summary = build_summary(result, validation)
        print(summary["title"])
        print(summary["body"])
        send_bark(summary["title"], summary["body"], summary["level"])
        return

    result = call_gemini(prompt_text, report_text)
    validation = validate_ai_output(result.get("text", ""))
    summary = build_summary(result, validation)

    print(summary["title"])
    print(summary["body"])
    send_bark(summary["title"], summary["body"], summary["level"])


if __name__ == "__main__":
    main()
