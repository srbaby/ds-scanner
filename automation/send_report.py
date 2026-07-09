import os
import sys
import json
import requests
from datetime import datetime
from versioning import METHODOLOGY_VERSION, validate_document_versions

# Bark App历史列表图标（系统通知横幅图标iOS不可覆盖，是限制不是bug，见fund-monitor的踩坑记录）
BARK_ICON = "https://cdn.jsdelivr.net/gh/srbaby/ds-scanner@main/favicon.png"
DASHBOARD_URL = "https://stock.bailuzun.com"
DASHBOARD_FILE = "dashboard.json"
# APNs 单条 payload 约 4KB；为标题、图标、分组、URL 等元数据预留足够空间。
MAX_BARK_BODY_BYTES = 2800
TRANSACTION_ACTIONS = {"BUY", "ADD", "REDUCE", "SELL"}


def is_trade_day():
    try:
        import akshare as ak

        today = datetime.now().strftime('%Y%m%d')
        trade_cal = ak.tool_trade_date_hist_sina()
        trade_dates = trade_cal['trade_date'].astype(str).str.replace('-', '').tolist()
        return today in trade_dates
    except Exception as e:
        print(f"⚠️ 交易日历获取失败: {e}，默认继续发送")
        return True


def utf8_truncate(text, max_bytes=MAX_BARK_BODY_BYTES):
    raw = str(text or "").encode("utf-8")
    if len(raw) <= max_bytes:
        return str(text or "")
    suffix = "\n…完整内容请打开 X-Plan 看板"
    suffix_bytes = suffix.encode("utf-8")
    available = max(0, max_bytes - len(suffix_bytes))
    clipped = raw[:available]
    while clipped:
        try:
            return clipped.decode("utf-8") + suffix
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return suffix.lstrip()


def get_section(text, heading):
    lines = str(text or "").splitlines()
    start = next(
        (idx for idx, line in enumerate(lines) if line.strip().startswith(f"【{heading}】")),
        -1,
    )
    if start < 0:
        return []
    result = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("【") and "】" in stripped:
            break
        if stripped:
            result.append(stripped)
    return result


def parse_action_rows(ai_text):
    rows = []
    for line in get_section(ai_text, "操作清单"):
        if "|" not in line:
            continue
        cols = [part.strip() for part in line.strip().strip("|").split("|")]
        if not cols or "操作编号" in cols[0] or set(cols[0]) <= {"-", ":"}:
            continue
        if len(cols) < 10:
            continue
        action = cols[1].upper()
        rows.append(
            {
                "id": cols[0],
                "action": action,
                "code": cols[2],
                "name": cols[3],
                "current": cols[4],
                "target": cols[5],
                "rule": cols[7],
                "reason": cols[9],
            }
        )
    return rows


def build_bark_body(report_text, dashboard_data=None):
    dashboard_data = dashboard_data or {}
    ai = dashboard_data.get("ai") or {}
    generated_at = dashboard_data.get("generated_at") or ""
    version = dashboard_data.get("methodology_version") or METHODOLOGY_VERSION
    lines = [f"{version} · {generated_at or '本次扫描'}"]

    if ai.get("ok") and ai.get("text"):
        ai_text = ai["text"]
        window_lines = [
            line for line in get_section(ai_text, "执行窗口")
            if "|" not in line and not line.startswith("类型")
        ]
        if window_lines:
            lines.extend(["", "执行窗口", window_lines[0]])

        rows = parse_action_rows(ai_text)
        transaction_rows = [row for row in rows if row["action"] in TRANSACTION_ACTIONS]
        lines.extend(["", "操作清单"])
        if transaction_rows:
            for row in transaction_rows:
                code_name = " ".join(part for part in [row["code"], row["name"]] if part)
                lines.append(
                    f"{row['id']} {row['action']} {code_name} "
                    f"{row['current']}→{row['target']} {row['rule']}"
                )
                if row["reason"]:
                    lines.append(f"  {row['reason']}")
        else:
            lines.append("今日无 BUY / ADD / REDUCE / SELL 操作")

        warnings = []
        for line in ai_text.splitlines():
            stripped = line.strip().lstrip("-* ")
            if (
                stripped
                and any(marker in stripped for marker in ("⚠️", "❌", "异常", "失败", "降级"))
                and stripped not in warnings
            ):
                warnings.append(stripped)
            if len(warnings) >= 3:
                break
        if warnings:
            lines.extend(["", "异常与降级", *warnings])
    else:
        error = ai.get("error") or "未生成可用 AI 操作清单"
        lines.extend([
            "",
            "⚠️ AI 分析失败",
            str(error),
            "原始扫描与完整错误已保留在看板，请勿依据缺失清单执行交易。",
        ])

    lines.extend(["", f"完整报告：{DASHBOARD_URL}"])
    return utf8_truncate("\n".join(lines))


def load_dashboard(path=DASHBOARD_FILE):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠️ 无法读取 {path}: {exc}")
        return None


def build_payload(report_text, today=None, dashboard_data=None):
    today = today or datetime.now().strftime('%Y-%m-%d')
    return {
        "title": f"📡 X-Plan {METHODOLOGY_VERSION} 波段扫描 {today}",
        "body": build_bark_body(report_text, dashboard_data),
        "level": "active",
        "group": "X-Plan扫描",
        "badge": 1,
        "icon": BARK_ICON,
        "url": DASHBOARD_URL,
    }


def send_bark(report_text, dashboard_data=None, post=requests.post, keys=None):
    supplied_keys = keys is not None
    keys = list(keys) if supplied_keys else [os.environ['BARK_KEY']]
    # 老婆的推送Key（可选，配置后同步推送）
    if not supplied_keys:
        wife_key = os.environ.get('BARK_KEY_WIFE', '').strip()
        if wife_key:
            keys.append(wife_key)

    payload = build_payload(report_text, dashboard_data=dashboard_data)
    failures = []

    for key in keys:
        try:
            r = post(
                f"https://api.day.app/{key}",
                headers={"Content-Type": "application/json; charset=utf-8"},
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=30,
            )
            print(f"Bark推送({key[:8]}…) -> {r.status_code}: {r.text}")
            r.raise_for_status()
        except Exception as exc:
            failures.append(f"{key[:8]}…: {exc}")
            print(f"❌ Bark推送失败({key[:8]}…): {exc}")
    if failures:
        raise RuntimeError(f"Bark推送部分失败（{len(failures)}/{len(keys)}）: {'; '.join(failures)}")
    print(f"✅ Bark推送成功（共{len(keys)}个接收方）")
    return payload


if __name__ == '__main__':
    validate_document_versions()
    if not is_trade_day():
        print("📅 今日非交易日，跳过发送")
        sys.exit(0)

    with open('report.txt', 'r', encoding='utf-8') as f:
        report = f.read()

    send_bark(report, load_dashboard())
