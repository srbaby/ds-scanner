import os
import sys
import json
import requests
from datetime import datetime
import akshare as ak

# Bark App历史列表图标（系统通知横幅图标iOS不可覆盖，是限制不是bug，见fund-monitor的踩坑记录）
BARK_ICON = "https://cdn.jsdelivr.net/gh/srbaby/ds-scanner@main/favicon.png"


def is_trade_day():
    try:
        today = datetime.now().strftime('%Y%m%d')
        trade_cal = ak.tool_trade_date_hist_sina()
        trade_dates = trade_cal['trade_date'].astype(str).str.replace('-', '').tolist()
        return today in trade_dates
    except Exception as e:
        print(f"⚠️ 交易日历获取失败: {e}，默认继续发送")
        return True


def send_bark(report_text):
    bark_key = os.environ['BARK_KEY']
    today = datetime.now().strftime('%Y-%m-%d')

    # 全文塞body（不做截断/中转），便于直接在Bark App长按复制给DeepSeek/Gemini。
    # 注意：APNs单条推送payload上限约4KB，report.txt若超长可能被系统截断——
    # 这是已知风险，按JanY要求选择"全文优先"而非"摘要+链接中转"。
    payload = {
        "title": f"📡 DS波段扫描 {today}",
        "body": report_text,
        "level": "active",
        "group": "DS扫描",
        "badge": 1,
        "icon": BARK_ICON,
    }

    r = requests.post(
        f"https://api.day.app/{bark_key}",
        headers={"Content-Type": "application/json; charset=utf-8"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=30,
    )
    print(f"Bark推送 -> {r.status_code}: {r.text}")
    r.raise_for_status()
    print("✅ Bark推送成功")


if __name__ == '__main__':
    if not is_trade_day():
        print("📅 今日非交易日，跳过发送")
        sys.exit(0)

    with open('report.txt', 'r', encoding='utf-8') as f:
        report = f.read()

    send_bark(report)
