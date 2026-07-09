# /// script
# dependencies = [
#   "requests",
# ]
# ///

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动验证 Gemini 审计服务；只通知主 Bark 接收者。"""

import json
import os
from datetime import datetime

import requests

from gemini_review import GEMINI_MODEL, call_gemini

PROXIES = {"http": None, "https": None}
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BARK_ICON = "https://cdn.jsdelivr.net/gh/srbaby/ds-scanner@main/favicon.png"


def _load_json(name):
    with open(os.path.join(ROOT_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def _load_text(name):
    with open(os.path.join(ROOT_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def send_bark(title, body, level):
    key = os.environ.get("BARK_KEY", "").strip()
    if not key:
        print("⚠️ 未配置 BARK_KEY，跳过通知")
        return
    response = requests.post(
        f"https://api.day.app/{key}",
        headers={"Content-Type": "application/json; charset=utf-8"},
        data=json.dumps(
            {
                "title": title,
                "body": body,
                "level": level,
                "group": "X-Plan Gemini验证",
                "badge": 1,
                "icon": BARK_ICON,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        proxies=PROXIES,
        timeout=30,
    )
    print(f"Bark推送({key[:8]}…) -> {response.status_code}: {response.text}")
    response.raise_for_status()


def main():
    try:
        result = call_gemini(_load_text("report.txt"), _load_json("decision.json"))
    except Exception as exc:
        result = {
            "ok": False,
            "model": GEMINI_MODEL,
            "text": "",
            "error": f"Gemini验证异常: {exc}",
        }
    status = "OK" if result["ok"] else "FAIL"
    title = f"{'✅' if result['ok'] else '⚠️'} X-Plan Gemini {status} {datetime.now():%Y-%m-%d}"
    body = (
        f"模型：{result['model']}\n"
        f"状态：{status}\n"
        f"错误：{result.get('error') or '-'}\n"
        f"审计摘要：{(result.get('text') or '-')[:800]}"
    )
    print(title)
    print(body)
    send_bark(title, body, "active" if result["ok"] else "timeSensitive")


if __name__ == "__main__":
    main()
