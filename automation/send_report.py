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
DECISION_FILE = "decision.json"
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


def decision_action_rows(dashboard_data):
    rows = []
    for op in ((dashboard_data.get("decision") or {}).get("operations") or []):
        rows.append(
            {
                "id": op.get("id") or "",
                "action": str(op.get("action") or "").upper(),
                "code": op.get("symbol") or "",
                "name": op.get("name") or "",
                "current": f"{op.get('current_target_position_pct', 0)}%",
                "target": f"{op.get('target_position_pct', 0)}%",
                "rule": op.get("rule_code") or "",
                "reason": op.get("reason") or "",
                "guidance": op.get("execution_guidance") or {},
            }
        )
    return rows


def build_bark_body(report_text, dashboard_data=None):
    dashboard_data = dashboard_data or {}
    decision = dashboard_data.get("decision") or {}
    audit = dashboard_data.get("audit") or dashboard_data.get("ai") or {}
    ai = dashboard_data.get("ai") or {}
    generated_at = dashboard_data.get("generated_at") or ""
    version = dashboard_data.get("methodology_version") or METHODOLOGY_VERSION
    lines = [f"{version} · {generated_at or '本次扫描'}"]

    rows = decision_action_rows(dashboard_data)
    if rows:
        ai_text = ai.get("text") or ""
        window_lines = [
            line for line in get_section(ai_text, "执行窗口")
            if "|" not in line and not line.startswith("类型")
        ]
        if window_lines:
            lines.extend(["", "执行窗口", window_lines[0]])

        transaction_rows = [row for row in rows if row["action"] in TRANSACTION_ACTIONS]
        lines.extend(["", "操作清单"])
        if transaction_rows:
            for row in transaction_rows:
                code_name = " ".join(part for part in [row["code"], row["name"]] if part)
                lines.append(
                    f"{row['id']} {row['action']} {code_name} "
                    f"{row['current']}→{row['target']} {row['rule']}"
                )
                guidance = row.get("guidance") or {}
                if guidance:
                    lines.append(
                        f"  建议 {guidance.get('recommended_shares', 0):,}份"
                        f"（{guidance.get('recommended_lots', 0)}手）"
                        f" · 约¥{guidance.get('estimated_amount', 0):,.2f}"
                        f" · 参考价{guidance.get('reference_price', 0):.3f}"
                    )
                if row["reason"]:
                    lines.append(f"  {row['reason']}")
        else:
            lines.append("今日无 BUY / ADD / REDUCE / SELL 操作")

        warnings = []
        audit_text = audit.get("text") or ""
        for line in audit_text.splitlines():
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
        if audit.get("enabled") is False:
            pass
        elif audit.get("ok"):
            status = next(
                (value for value in ("CONFLICT", "WARN", "PASS") if value in audit_text),
                "PASS",
            )
            lines.extend(["", f"AI审计：{status}"])
        else:
            lines.extend(["", f"AI审计不可用：{audit.get('error') or '未知错误'}"])
    elif ai.get("ok") and ai.get("text"):
        # 旧版 dashboard.json 兼容。
        rows = parse_action_rows(ai["text"])
        transaction_rows = [row for row in rows if row["action"] in TRANSACTION_ACTIONS]
        lines.extend(["", "操作清单"])
        for row in transaction_rows:
            lines.append(
                f"{row['id']} {row['action']} {row['code']} {row['current']}→{row['target']} {row['rule']}"
            )
    else:
        error = "未生成扫描器权威操作清单"
        lines.extend([
            "",
            "⚠️ 决策生成失败",
            str(error),
            "请勿依据缺失清单执行交易。",
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


def load_decision(path=DECISION_FILE):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠️ 无法读取 {path}: {exc}")
        return None


def dashboard_with_decision_fallback(dashboard_data=None, decision_data=None):
    dashboard_data = dict(dashboard_data or {})
    if not dashboard_data.get("decision") and decision_data:
        dashboard_data["decision"] = decision_data
    if not dashboard_data.get("audit"):
        dashboard_data["audit"] = {
            "ok": False,
            "text": "",
            "error": "AI审计不可用；已使用扫描器权威决策兜底",
        }
    return dashboard_data


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

    dashboard = dashboard_with_decision_fallback(load_dashboard(), load_decision())
    send_bark(report, dashboard)
