# /// script
# dependencies = [
#   "requests",
# ]
# ///

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X-Plan AI自动复核模块（Gemini Flash标准档）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
读取本目录 X-Plan.md（方法论 canonical）+ report.txt，
调用 Gemini API 输出基于"三道金牌 + 四维评分 + 双防线止损"的分析。

定位：
- 本模块只负责"调用AI、拿到文本"，不做展示，不做Gist读写。
- 方法论文本不在本文件重复抄写，运行时直接读取 X-Plan.md，
  避免和canonical文档产生第二份拷贝（CLAUDE.md卫生要求）。
- 模型可通过环境变量 GEMINI_MODEL 切换（默认 gemini-3.5-flash，免费层可用）。
- 默认采用 Gemini Flash 标准调用：不设置 temperature/top_p/top_k，不开启
  thinkingConfig，降低14:49高峰期触发繁忙/限流的概率。
- 对 429/5xx 繁忙类错误做短等待重试，失败仍不阻塞 report 推送。

环境变量：
  GEMINI_API_KEY        必填，Google AI Studio 申请的免费API Key
  GEMINI_MODEL          可选，默认 gemini-3.5-flash
  GEMINI_THINKING_LEVEL 可选，默认空；仅明确设置时传 thinkingConfig
  GEMINI_MAX_OUTPUT_TOKENS 可选，默认 8192
  GEMINI_RETRIES        可选，默认 1；仅对繁忙类错误短等待重试
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import time
from typing import Dict, Optional

import requests

PROXIES = {"http": None, "https": None}

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_THINKING_LEVEL = os.environ.get("GEMINI_THINKING_LEVEL", "")
GEMINI_MAX_OUTPUT_TOKENS = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "8192"))
GEMINI_RETRIES = int(os.environ.get("GEMINI_RETRIES", "1"))
GEMINI_RETRY_SLEEP_SECONDS = int(os.environ.get("GEMINI_RETRY_SLEEP_SECONDS", "20"))

# 与 ds_scanner.py 同级目录的上一层（X-Plan/ 根目录）
METHODOLOGY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "X-Plan.md",
)

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def load_methodology() -> Optional[str]:
    """读取 X-Plan.md 全文，失败返回 None"""
    try:
        with open(METHODOLOGY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"  ⚠️ 方法论文件读取失败: {e}")
        return None


def call_gemini(report_text: str) -> Dict:
    """
    调用 Gemini API 做四维评分分析。

    返回:
        {
          "ok": bool,
          "model": str,
          "text": str,          # ok=True 时为AI回复全文
          "error": str | None,  # ok=False 时为错误说明
        }
    """
    if not GEMINI_API_KEY:
        return {
            "ok": False,
            "model": GEMINI_MODEL,
            "text": "",
            "error": "未配置 GEMINI_API_KEY，跳过AI分析",
        }

    methodology = load_methodology()
    if not methodology:
        return {
            "ok": False,
            "model": GEMINI_MODEL,
            "text": "",
            "error": f"未找到方法论文件 {METHODOLOGY_FILE}",
        }

    system_instruction = (
        "你是 X-Plan（X-DeepSeek波段验证系统）的AI复核员。\n"
        "下面是本系统的完整方法论文档（v2.6），这是规则的唯一来源，"
        "请严格按文档中的三道金牌、四维评分体系、双防线止损（逻辑止损/价格止损/时间止损）、"
        "持仓-新信号冲突处理矩阵、仓位约束执行分析，不要引入文档之外的规则或个人经验判断。\n"
        "如果报告处于非尾盘时段（报告顶部会标注数据时效），请明确提示当前数据是否可用于"
        "尾盘决策，不要把盘中折算量比当作尾盘真实值使用。\n\n"
        f"{methodology}"
    )

    # Gemini Flash标准档：只限制输出长度，不主动开启高思考等级。
    generation_config: Dict = {"maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS}
    if GEMINI_THINKING_LEVEL:
        generation_config["thinkingConfig"] = {
            "thinkingLevel": GEMINI_THINKING_LEVEL.upper()
        }

    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": report_text}]}],
        "generationConfig": generation_config,
    }

    url = GEMINI_API_URL.format(model=GEMINI_MODEL)

    last_error = ""
    max_attempts = max(1, GEMINI_RETRIES + 1)
    retryable_status = {429, 500, 502, 503, 504}
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.post(
                url,
                params={"key": GEMINI_API_KEY},
                json=payload,
                proxies=PROXIES,
                timeout=120,
            )
        except Exception as e:
            last_error = f"请求异常: {e}"
            if attempt < max_attempts:
                time.sleep(GEMINI_RETRY_SLEEP_SECONDS)
                continue
            return {"ok": False, "model": GEMINI_MODEL, "text": "", "error": last_error}

        if r.status_code == 200:
            break

        last_error = f"HTTP {r.status_code}: {r.text[:300]}"
        if r.status_code in retryable_status and attempt < max_attempts:
            time.sleep(GEMINI_RETRY_SLEEP_SECONDS)
            continue
        return {"ok": False, "model": GEMINI_MODEL, "text": "", "error": last_error}

    if "r" not in locals():
        return {"ok": False, "model": GEMINI_MODEL, "text": "", "error": last_error}

    try:
        data = r.json()
        candidates = data.get("candidates", [])
        if not candidates:
            feedback = data.get("promptFeedback", {})
            return {
                "ok": False,
                "model": GEMINI_MODEL,
                "text": "",
                "error": f"无候选返回（可能被安全策略拦截）: {feedback}",
            }
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        finish_reason = candidates[0].get("finishReason", "UNKNOWN")
        if not text:
            return {
                "ok": False,
                "model": GEMINI_MODEL,
                "text": "",
                "error": f"返回内容为空，finishReason={finish_reason}",
            }
        if finish_reason == "MAX_TOKENS":
            text += "\n\n⚠️ 系统提示：本次回复因达到MAX_TOKENS被截断，内容可能不完整。"
        return {"ok": True, "model": GEMINI_MODEL, "text": text, "error": None}
    except Exception as e:
        return {"ok": False, "model": GEMINI_MODEL, "text": "", "error": f"解析响应失败: {e}"}


if __name__ == "__main__":
    # 本地调试：python automation/ai_review.py
    # 需在 X-Plan/ 根目录下运行，且设置 GEMINI_API_KEY
    with open("report.txt", "r", encoding="utf-8") as f:
        report = f.read()

    mode_note = (
        f", thinking={GEMINI_THINKING_LEVEL}"
        if GEMINI_THINKING_LEVEL
        else ", standard"
    )
    print(f"🤖 调用 Gemini ({GEMINI_MODEL}{mode_note}) ...")
    result = call_gemini(report)
    if result["ok"]:
        print("✅ 分析成功\n")
        print(result["text"])
    else:
        print(f"❌ 分析失败: {result['error']}")
