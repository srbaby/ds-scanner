# /// script
# dependencies = [
#   "requests",
# ]
# ///

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X-Plan 看板数据生成器（Gemini独立审计）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
流程：
  1. 读取 report.txt（ds_scanner.py 刚生成的尾盘扫描报告）
  2. 每日流程默认不调用 AI；Gemini/DeepSeek 实现保留给独立研究
  3. 把 {report原文, 扫描器决策, 审计状态, 元信息} 写入 dashboard.json
     （与 etf_pool.json / holdings.json 同一个私有 Gist，复用现有 Token/权限）

index.html 前端读取 dashboard.json：AI分析全文（干货）默认展开，report原文默认折叠
（AI分析失败时自动展开report原文作兜底）。

失败处理：
  - AI调用失败不阻塞流程，dashboard.json中audit.ok=false；
    扫描器权威决策、看板和Bark推送不受影响。
  - Gist未配置（本地调试）时，写入本地同名文件 dashboard.json 供检查。

环境变量：
  DS_SCANNER_GIST_ID  必填（线上），与 ds_scanner.py 共用
  GITHUB_TOKEN        必填（线上），与 ds_scanner.py 共用（GH_PAT，需 gist 写权限）
  AI_PROVIDER         可选，默认 none；gemini/deepseek 仅供独立调试
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import os
import time
from datetime import datetime

import requests

from ai_review import DEEPSEEK_MODEL, call_deepseek
from gemini_review import GEMINI_MODEL, call_gemini
from versioning import (
    DATA_SCHEMA_VERSION,
    METHODOLOGY_VERSION,
    PROMPT_CONTRACT_VERSION,
    validate_document_versions,
)

os.environ["TZ"] = "Asia/Shanghai"
if hasattr(time, "tzset"):
    time.tzset()

PROXIES = {"http": None, "https": None}

GIST_ID = os.environ.get("DS_SCANNER_GIST_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

DASHBOARD_FILE = "dashboard.json"
REPORT_FILE = "report.txt"
DECISION_FILE = "decision.json"
AI_PROVIDER = os.environ.get("AI_PROVIDER", "none").strip().lower()


def load_policy_research() -> dict:
    path = os.path.join("data", "policy_research", "snapshots", "policy_watchlist.json")
    if not os.path.exists(path):
        path = os.path.join("data", "policy_research", "snapshots", "last_decision_compare.json")
    if not os.path.exists(path):
        return {"enabled": True, "ok": False, "error": "policy_watchlist.json 尚未生成"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "watchlist" in data:
            data = data["watchlist"]
        data["enabled"] = True
        data["ok"] = True
        return data
    except Exception as exc:
        return {"enabled": True, "ok": False, "error": f"政策旁路观察读取失败: {exc}"}


def call_ai_audit(report_text: str, decision: dict) -> tuple:
    provider = AI_PROVIDER if AI_PROVIDER in {"none", "gemini", "deepseek"} else "none"
    if provider == "none":
        return provider, {
            "enabled": False,
            "ok": True,
            "model": "",
            "text": "",
            "error": None,
        }
    try:
        if provider == "deepseek":
            return provider, call_deepseek(report_text, decision)
        return provider, call_gemini(report_text, decision)
    except Exception as exc:
        model = DEEPSEEK_MODEL if provider == "deepseek" else GEMINI_MODEL
        return provider, {
            "ok": False,
            "model": model,
            "text": "",
            "error": f"AI审计模块异常: {exc}",
        }


def _gist_headers():
    if GITHUB_TOKEN:
        return {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        }
    return {"Content-Type": "application/json"}


def write_dashboard(data: dict, report_text: str) -> bool:
    """发布轻量决策看板与独立原始报告，避免 report 重复嵌入 dashboard。"""
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"✅ {DASHBOARD_FILE} 已生成本地运行时副本")

    if not GIST_ID or not GITHUB_TOKEN:
        print("⚠️ 未配置 DS_SCANNER_GIST_ID/GITHUB_TOKEN，仅保留本地 dashboard.json")
        return False

    try:
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_gist_headers(),
            data=json.dumps({"files": {
                DASHBOARD_FILE: {"content": content},
                REPORT_FILE: {"content": report_text},
            }}),
            proxies=PROXIES,
            timeout=15,
        )
        if r.status_code == 200:
            print(f"✅ {DASHBOARD_FILE} 已写入 Gist")
            return True
        print(f"⚠️ Gist 写入失败: HTTP {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"⚠️ Gist 写入异常: {e}")

    # 本地副本已在请求前生成，供后续 Bark 摘要步骤稳定读取。
    return False


def build_dashboard(report_text: str, decision: dict, provider: str, result: dict) -> dict:
    """Create the front-end contract without duplicating the raw report."""
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "methodology_version": METHODOLOGY_VERSION,
        "prompt_contract_version": PROMPT_CONTRACT_VERSION,
        "data_schema_version": DATA_SCHEMA_VERSION,
        "report_file": REPORT_FILE,
        "report_available": bool(report_text),
        "decision": decision,
        "audit": {
            "provider": provider,
            "enabled": result.get("enabled", True),
            "model": result["model"],
            "ok": result["ok"],
            "text": result["text"],
            "error": result["error"],
        },
        # 兼容旧版前端；新链路只从 decision 读取交易操作。
        "ai": {
            "provider": provider,
            "enabled": result.get("enabled", True),
            "model": result["model"],
            "ok": result["ok"],
            "text": result["text"],
            "error": result["error"],
        },
        "policy_research": load_policy_research(),
    }


def main():
    validate_document_versions()
    with open("report.txt", "r", encoding="utf-8") as f:
        report_text = f.read()
    with open(DECISION_FILE, "r", encoding="utf-8") as f:
        decision = json.load(f)

    provider, result = call_ai_audit(report_text, decision)
    if not result.get("enabled", True):
        print("ℹ️ 每日AI审计已停用，直接发布扫描器权威决策")
    elif result["ok"]:
        print(f"✅ {provider} 审计完成")
    else:
        print(f"⚠️ {provider} 审计失败（扫描器决策仍有效）: {result['error']}")

    data = build_dashboard(report_text, decision, provider, result)
    write_dashboard(data, report_text)


if __name__ == "__main__":
    main()
