# /// script
# dependencies = [
#   "requests",
# ]
# ///

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X-Plan 看板数据生成器（DeepSeek自动分析）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
流程：
  1. 读取 report.txt（ds_scanner.py 刚生成的尾盘扫描报告）
  2. 调用 ai_review.call_deepseek() 做四维评分分析
  3. 把 {report原文, DeepSeek分析, 元信息} 写入 Gist 的 dashboard.json
     （与 etf_pool.json / holdings.json 同一个私有 Gist，复用现有 Token/权限）

index.html 前端读取 dashboard.json：AI分析全文（干货）默认展开，report原文默认折叠
（AI分析失败时自动展开report原文作兜底）。

失败处理：
  - DeepSeek调用失败（额度/网络/被拦截）不阻塞流程，dashboard.json中ai.ok=false，
    前端展示错误信息，report原文照常可见，Bark推送不受影响。
  - Gist未配置（本地调试）时，写入本地同名文件 dashboard.json 供检查。

环境变量：
  DS_SCANNER_GIST_ID  必填（线上），与 ds_scanner.py 共用
  GITHUB_TOKEN        必填（线上），与 ds_scanner.py 共用（GH_PAT，需 gist 写权限）
  DEEPSEEK_API_KEY    必填，见 ai_review.py
  DEEPSEEK_MODEL      可选，见 ai_review.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import os
from datetime import datetime

import requests

from ai_review import call_deepseek, DEEPSEEK_MODEL
from versioning import (
    DATA_SCHEMA_VERSION,
    METHODOLOGY_VERSION,
    PROMPT_CONTRACT_VERSION,
    validate_document_versions,
)

PROXIES = {"http": None, "https": None}

GIST_ID = os.environ.get("DS_SCANNER_GIST_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

DASHBOARD_FILE = "dashboard.json"


def _gist_headers():
    if GITHUB_TOKEN:
        return {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        }
    return {"Content-Type": "application/json"}


def write_dashboard(data: dict) -> bool:
    """始终写本地运行时副本，再写入 Gist；返回是否写入 Gist 成功。"""
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ {DASHBOARD_FILE} 已生成本地运行时副本")

    if not GIST_ID or not GITHUB_TOKEN:
        print("⚠️ 未配置 DS_SCANNER_GIST_ID/GITHUB_TOKEN，仅保留本地 dashboard.json")
        return False

    try:
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_gist_headers(),
            data=json.dumps({"files": {DASHBOARD_FILE: {"content": content}}}),
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


def main():
    validate_document_versions()
    with open("report.txt", "r", encoding="utf-8") as f:
        report_text = f.read()

    print(f"🤖 调用 DeepSeek ({DEEPSEEK_MODEL}) 分析中...")
    result = call_deepseek(report_text)
    if result["ok"]:
        print("✅ DeepSeek 分析完成")
    else:
        print(f"⚠️ DeepSeek 分析失败（不影响report推送）: {result['error']}")

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "methodology_version": METHODOLOGY_VERSION,
        "prompt_contract_version": PROMPT_CONTRACT_VERSION,
        "data_schema_version": DATA_SCHEMA_VERSION,
        "report": report_text,
        "ai": {
            "provider": "deepseek",
            "model": result["model"],
            "ok": result["ok"],
            "text": result["text"],
            "error": result["error"],
        },
    }
    write_dashboard(data)


if __name__ == "__main__":
    main()
