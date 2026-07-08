# /// script
# dependencies = [
#   "requests",
# ]
# ///

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X-Plan AI自动复核模块（DeepSeek Flash）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
读取本目录 Prompt.md（每日 AI Core Prompt）+ report.txt，
调用 DeepSeek API 输出基于"三道金牌 + 四维评分 + 双防线止损"的分析。

定位：
- 本模块只负责"调用AI、拿到文本"，不做展示，不做Gist读写。
- 复核规则不在本文件重复抄写，运行时直接读取 Prompt.md。
- 模型可通过环境变量 DEEPSEEK_MODEL 切换（默认 deepseek-v4-flash）。
- 默认采用 DeepSeek Flash 非思考模式，适合规则审视式日常复核。
- 对 429/5xx 繁忙类错误做短等待重试，失败仍不阻塞 report 推送。

环境变量：
  DEEPSEEK_API_KEY        必填，DeepSeek Platform 申请的 API Key
  DEEPSEEK_MODEL          可选，默认 deepseek-v4-flash
  DEEPSEEK_MAX_TOKENS     可选，默认 8192
  DEEPSEEK_RETRIES        可选，默认 1；仅对繁忙类错误短等待重试
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import time
from typing import Dict, Optional

import requests
from versioning import METHODOLOGY_VERSION, validate_document_versions

PROXIES = {"http": None, "https": None}

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_MAX_TOKENS = int(os.environ.get("DEEPSEEK_MAX_TOKENS", "8192"))
DEEPSEEK_RETRIES = int(os.environ.get("DEEPSEEK_RETRIES", "1"))
DEEPSEEK_RETRY_SLEEP_SECONDS = int(os.environ.get("DEEPSEEK_RETRY_SLEEP_SECONDS", "20"))

# 与 ds_scanner.py 同级目录的上一层（X-Plan/ 根目录）
PROMPT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Prompt.md",
)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
REQUIRED_OPERATION_COLUMNS = [
    "操作编号",
    "类型",
    "代码",
    "名称",
    "当前目标仓位%",
    "今日目标仓位%",
    "调整仓位",
    "规则代码",
    "信号等级",
    "中文操作依据",
    "关键指标",
]


def validate_ai_output(text: str) -> Optional[str]:
    if "【操作清单】" not in text:
        return "缺少【操作清单】"
    header = next(
        (line for line in text.splitlines() if "|" in line and "操作编号" in line and "规则代码" in line),
        "",
    )
    missing = [column for column in REQUIRED_OPERATION_COLUMNS if column not in header]
    if missing:
        return f"操作清单缺少列: {', '.join(missing)}"
    transaction_rows = []
    for line in text.splitlines():
        if "|" not in line or not any(f"| {action} |" in line for action in ["BUY", "ADD", "REDUCE", "SELL"]):
            continue
        cols = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(cols) < len(REQUIRED_OPERATION_COLUMNS):
            return f"操作行字段不足: {line[:120]}"
        transaction_rows.append(cols)
    for cols in transaction_rows:
        if not cols[0].upper().startswith("OP-"):
            return f"操作编号无效: {cols[0]}"
        if not cols[7] or not cols[9]:
            return f"规则代码或中文操作依据为空: {cols[0]}"
    return None


def load_prompt() -> Optional[str]:
    """读取 Prompt.md 全文，失败返回 None"""
    try:
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"  ⚠️ Prompt文件读取失败: {e}")
        return None


def call_deepseek(report_text: str) -> Dict:
    """
    调用 DeepSeek API 做四维评分分析。

    返回:
        {
          "ok": bool,
          "model": str,
          "text": str,          # ok=True 时为AI回复全文
          "error": str | None,  # ok=False 时为错误说明
        }
    """
    validate_document_versions()
    if not DEEPSEEK_API_KEY:
        return {
            "ok": False,
            "model": DEEPSEEK_MODEL,
            "text": "",
            "error": "未配置 DEEPSEEK_API_KEY，跳过AI分析",
        }

    prompt = load_prompt()
    if not prompt:
        return {
            "ok": False,
            "model": DEEPSEEK_MODEL,
            "text": "",
            "error": f"未找到Prompt文件 {PROMPT_FILE}",
        }

    system_instruction = (
        "你是 X-Plan 的每日AI复核员。\n"
        "下面是本系统的每日AI Core Prompt，这是本次自动复核的唯一执行规则，"
        "请严格按Prompt输出分析，不要引入文档之外的规则或个人经验判断。\n"
        "如果报告处于非尾盘时段（报告顶部会标注数据时效），请明确提示当前数据是否可用于"
        "尾盘决策，不要把盘中折算量比当作尾盘真实值使用。\n\n"
        f"{prompt}"
    )

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": report_text},
        ],
        "max_tokens": DEEPSEEK_MAX_TOKENS,
        "stream": False,
    }

    last_error = ""
    max_attempts = max(1, DEEPSEEK_RETRIES + 1)
    retryable_status = {429, 500, 502, 503, 504}
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                proxies=PROXIES,
                timeout=90,
            )
        except Exception as e:
            last_error = f"请求异常: {e}"
            if attempt < max_attempts:
                time.sleep(DEEPSEEK_RETRY_SLEEP_SECONDS)
                continue
            return {"ok": False, "model": DEEPSEEK_MODEL, "text": "", "error": last_error}

        if r.status_code == 200:
            break

        last_error = f"HTTP {r.status_code}: {r.text[:300]}"
        if r.status_code in retryable_status and attempt < max_attempts:
            time.sleep(DEEPSEEK_RETRY_SLEEP_SECONDS)
            continue
        return {"ok": False, "model": DEEPSEEK_MODEL, "text": "", "error": last_error}

    if "r" not in locals():
        return {"ok": False, "model": DEEPSEEK_MODEL, "text": "", "error": last_error}

    try:
        data = r.json()
        choices = data.get("choices", [])
        if not choices:
            return {
                "ok": False,
                "model": DEEPSEEK_MODEL,
                "text": "",
                "error": f"无候选返回: {data}",
            }
        text = choices[0].get("message", {}).get("content", "").strip()
        finish_reason = choices[0].get("finish_reason", "UNKNOWN")
        if not text:
            return {
                "ok": False,
                "model": DEEPSEEK_MODEL,
                "text": "",
                "error": f"返回内容为空，finishReason={finish_reason}",
            }
        if finish_reason == "length":
            text += "\n\n⚠️ 系统提示：本次回复因达到max_tokens被截断，内容可能不完整。"
        format_error = validate_ai_output(text)
        if format_error:
            return {
                "ok": False,
                "model": DEEPSEEK_MODEL,
                "text": text,
                "error": f"{METHODOLOGY_VERSION} 输出契约校验失败: {format_error}",
            }
        return {"ok": True, "model": DEEPSEEK_MODEL, "text": text, "error": None}
    except Exception as e:
        return {"ok": False, "model": DEEPSEEK_MODEL, "text": "", "error": f"解析响应失败: {e}"}


if __name__ == "__main__":
    # 本地调试：python automation/ai_review.py
    # 需在 X-Plan/ 根目录下运行，且设置 DEEPSEEK_API_KEY
    with open("report.txt", "r", encoding="utf-8") as f:
        report = f.read()

    print(f"🤖 调用 DeepSeek ({DEEPSEEK_MODEL}) ...")
    result = call_deepseek(report)
    if result["ok"]:
        print("✅ 分析成功\n")
        print(result["text"])
    else:
        print(f"❌ 分析失败: {result['error']}")
