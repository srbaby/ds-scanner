# /// script
# dependencies = [
#   "requests",
# ]
# ///

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X-Plan 在线量化观察任务

正式运行在 GitHub Actions：
  - 读取 Gist: holdings.json / dashboard.json / observer_request.json
  - 维护 Gist: trades.jsonl / portfolio_snapshots.jsonl / stats.json / observer_state.json
  - 不要求用户补填成交价、通道、原因

本地未配置 Gist 时只做语法/单元测试，不进入日常链路。
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

os.environ["TZ"] = "Asia/Shanghai"
if hasattr(time, "tzset"):
    time.tzset()

for proxy_key in [
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
]:
    os.environ.pop(proxy_key, None)

PROXIES = {"http": None, "https": None}
GIST_ID = os.environ.get("DS_SCANNER_GIST_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

LEGACY_VIRTUAL_PRINCIPAL = 200000.0
COMMISSION_RATE = float(os.environ.get("XPLAN_COMMISSION_RATE", "0.0003"))
COMMISSION_MIN = float(os.environ.get("XPLAN_COMMISSION_MIN", "5"))
ENHANCED_ALPHA_NET = float(os.environ.get("XPLAN_ENHANCED_ALPHA_NET", "0.03"))

FILE_HOLDINGS = "holdings.json"
FILE_DASHBOARD = "dashboard.json"
FILE_OBSERVER_REQUEST = "observer_request.json"
FILE_TRADES = "trades.jsonl"
FILE_SNAPSHOTS = "portfolio_snapshots.jsonl"
FILE_STATS = "stats.json"
FILE_STATE = "observer_state.json"

ETF_NAMES = {
    "sh588000": "科创50ETF",
    "sh512480": "半导体ETF",
    "sh515880": "通信ETF",
    "sz159766": "旅游ETF",
    "sh515120": "创新药ETF",
    "sz159851": "金融科技",
    "sh512880": "证券ETF",
    "sz159915": "创业板ETF",
    "sh515030": "新能车ETF",
    "sz159755": "电池ETF",
    "sh515220": "煤炭ETF",
    "sh516150": "稀土ETF",
    "sh512400": "有色ETF",
    "sh516020": "化工ETF",
    "sh512690": "酒ETF",
    "sh513180": "恒生科技",
    "sh515790": "光伏ETF",
    "sh512660": "军工ETF",
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_text() -> str:
    return date.today().isoformat()


def gist_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "x-plan-observer"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


def read_gist_files() -> Dict[str, str]:
    if not GIST_ID or not GITHUB_TOKEN:
        raise RuntimeError("缺少 DS_SCANNER_GIST_ID 或 GITHUB_TOKEN，观察任务只能在线写 Gist")
    r = requests.get(
        f"https://api.github.com/gists/{GIST_ID}",
        headers=gist_headers(),
        proxies=PROXIES,
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Gist 读取失败: HTTP {r.status_code} {r.text[:200]}")
    files = r.json().get("files", {})
    return {name: meta.get("content", "") for name, meta in files.items()}


def write_gist_files(files: Dict[str, str]) -> None:
    payload = {"files": {name: {"content": content} for name, content in files.items()}}
    r = requests.patch(
        f"https://api.github.com/gists/{GIST_ID}",
        headers=gist_headers(),
        data=json.dumps(payload, ensure_ascii=False),
        proxies=PROXIES,
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Gist 写入失败: HTTP {r.status_code} {r.text[:300]}")


def parse_json(raw: str, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def parse_jsonl(raw: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in StringLines(raw):
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except Exception:
            continue
    return rows


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)


def dump_jsonl(rows: Iterable[Dict[str, Any]]) -> str:
    return "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=False) for row in rows) + "\n"


def StringLines(raw: str) -> Iterable[str]:
    for line in str(raw or "").splitlines():
        line = line.strip()
        if line:
            yield line


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return default
        return out
    except Exception:
        return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def normalize_symbol(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    digits = re.sub(r"\D", "", text)
    if len(digits) != 6:
        return text
    if text.startswith(("sh", "sz", "bj")):
        return text[:2] + digits
    if re.match(r"^(60|65|68|50|51|52|56|58)", digits):
        return "sh" + digits
    if re.match(r"^(00|30|15|16|18)", digits):
        return "sz" + digits
    return "sh" + digits


def commission(amount: float) -> float:
    if amount <= 0:
        return 0.0
    return round(max(amount * COMMISSION_RATE, COMMISSION_MIN), 2)


def canonical_holdings(holdings_data: Dict[str, Any]) -> Dict[str, Any]:
    rows = []
    for raw in holdings_data.get("holdings") or []:
        if not isinstance(raw, dict):
            continue
        qty = to_int(raw.get("qty"))
        if qty <= 0:
            continue
        symbol = normalize_symbol(raw.get("symbol"))
        rows.append(
            {
                "symbol": symbol,
                "name": raw.get("name") or ETF_NAMES.get(symbol) or symbol,
                "qty": qty,
                "cost": round(to_float(raw.get("cost")), 6),
                "buy_date": str(raw.get("buy_date") or ""),
                "_lot_id": raw.get("_lot_id") or "",
                "is_reduced": bool(raw.get("is_reduced", False)),
            }
        )
    rows.sort(key=lambda x: (x["symbol"], x["buy_date"], x["cost"], x["qty"], x["_lot_id"]))
    return {
        "cash_available": round(to_float(holdings_data.get("cash_available")), 2),
        "holdings": rows,
    }


def holdings_hash(holdings_data: Dict[str, Any]) -> str:
    encoded = json.dumps(canonical_holdings(holdings_data), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def next_seq(prefix: str, existing: Iterable[str]) -> int:
    seq = 0
    for value in existing:
        if str(value).startswith(prefix):
            m = re.search(r"(\d+)$", str(value))
            if m:
                seq = max(seq, int(m.group(1)))
    return seq + 1


def make_lot_id(symbol: str, buy_date: str, existing: Iterable[str]) -> str:
    day = re.sub(r"\D", "", buy_date or today_text())[:8] or date.today().strftime("%Y%m%d")
    prefix = f"{symbol}#{day}#"
    return f"{prefix}{next_seq(prefix, existing):02d}"


def make_trade_id(existing: Iterable[Dict[str, Any]]) -> str:
    max_id = 0
    for trade in existing:
        m = re.match(r"t(\d+)$", str(trade.get("trade_id", "")))
        if m:
            max_id = max(max_id, int(m.group(1)))
    return f"t{max_id + 1:04d}"


def assign_current_lots(
    current: Dict[str, Any], previous_lots: List[Dict[str, Any]], known_lot_ids: Iterable[str]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    assigned: List[Dict[str, Any]] = []
    notes: List[str] = []
    used_prev: set[int] = set()
    all_ids = set(known_lot_ids)

    for raw in current["holdings"]:
        row = dict(raw)
        lot_id = str(row.get("_lot_id") or "")
        if not lot_id:
            candidates = []
            for idx, prev in enumerate(previous_lots):
                if idx in used_prev:
                    continue
                if prev.get("symbol") != row["symbol"]:
                    continue
                score = 0
                if prev.get("buy_date") == row["buy_date"]:
                    score += 3
                if abs(to_float(prev.get("cost")) - row["cost"]) < 0.000001:
                    score += 3
                if prev.get("name") == row["name"]:
                    score += 1
                score -= abs(to_int(prev.get("qty")) - row["qty"]) / 1000000
                if score >= 3:
                    candidates.append((score, idx, prev))
            if candidates:
                candidates.sort(key=lambda item: item[0], reverse=True)
                _, idx, prev = candidates[0]
                used_prev.add(idx)
                lot_id = str(prev.get("lot_id") or "")
            else:
                lot_id = make_lot_id(row["symbol"], row["buy_date"], all_ids)
                notes.append(f"new_lot_id:{lot_id}")
        row["lot_id"] = lot_id
        all_ids.add(lot_id)
        assigned.append(row)

    return assigned, notes


def fetch_sina_quotes(symbols: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    symbols = sorted({normalize_symbol(s) for s in symbols if s})
    if not symbols:
        return {}
    try:
        url = f"http://hq.sinajs.cn/list={','.join(symbols)}"
        r = requests.get(url, headers={"Referer": "http://finance.sina.com.cn"}, proxies=PROXIES, timeout=10)
        r.encoding = "gbk"
        quotes: Dict[str, Dict[str, Any]] = {}
        for line in r.text.splitlines():
            m = re.match(r'var hq_str_(\w+)="(.*)";', line)
            if not m:
                continue
            code, payload = m.group(1).lower(), m.group(2)
            parts = payload.split(",")
            if len(parts) < 4 or not parts[0]:
                continue
            last_close = to_float(parts[2])
            price = to_float(parts[3]) or last_close
            quotes[code] = {
                "name": parts[0],
                "price": price,
                "last_close": last_close,
                "source": "sina",
            }
        return quotes
    except Exception as exc:
        print(f"⚠️ 新浪行情失败: {exc}")
        return {}


def fetch_csindex_close(index_code: str, target_day: str) -> Optional[float]:
    start = target_day.replace("-", "")
    end = start
    try:
        url = (
            "https://www.csindex.com.cn/csindex-home/perf/index-perf"
            f"?indexCode={index_code}&startDate={start}&endDate={end}"
        )
        r = requests.get(url, proxies=PROXIES, timeout=12)
        if r.status_code != 200:
            return None
        payload = r.json()
        rows = payload.get("data") or payload.get("result") or []
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("rows") or []
        if not rows:
            return None
        row = rows[-1]
        for key in ["close", "closePrice", "indexClose", "指数收盘", "收盘"]:
            if key in row:
                value = to_float(row.get(key), 0)
                if value:
                    return value
    except Exception as exc:
        print(f"⚠️ 中证全收益指数失败 {index_code}: {exc}")
    return None


def infer_trade_reason(action: str, symbol: str, dashboard: Dict[str, Any]) -> str:
    text = "\n".join(
        [
            str(dashboard.get("report") or ""),
            str((dashboard.get("ai") or {}).get("text") or ""),
        ]
    )
    if symbol and symbol in text:
        for line in text.splitlines():
            if symbol in line:
                if re.search(r"止损|清仓|卖出|止盈|减仓|买入|加仓", line):
                    return line.strip()[:120]
    return "AI操作清单/持仓变更推导" if action in {"BUY", "ADD", "SELL"} else "自动观察"


def build_trade(
    trade_id: str,
    action: str,
    lot: Dict[str, Any],
    qty: int,
    trade_day: str,
    price: Optional[float],
    confidence: str,
    source: str,
    dashboard: Dict[str, Any],
    open_ref: Optional[str] = None,
    open_cost: Optional[float] = None,
) -> Dict[str, Any]:
    amount = round((price or 0) * qty, 2) if price else None
    row: Dict[str, Any] = {
        "trade_id": trade_id,
        "date": trade_day,
        "action": action,
        "symbol": lot["symbol"],
        "name": lot.get("name") or ETF_NAMES.get(lot["symbol"]) or lot["symbol"],
        "lot_id": lot["lot_id"],
        "qty": qty,
        "price": round(price, 6) if price else None,
        "amount": amount,
        "commission": commission(amount or 0),
        "channel": "auto",
        "open_ref": open_ref,
        "reason": infer_trade_reason(action, lot["symbol"], dashboard),
        "confidence": confidence,
        "source": source,
    }
    if price is None:
        row["needs_review"] = True
    if action == "SELL" and open_cost is not None and price is not None:
        gross = (price - open_cost) * qty
        row["pnl_amount"] = round(gross - row["commission"], 2)
        row["pnl_pct"] = round((price / open_cost - 1) * 100, 4) if open_cost > 0 else None
    return row


def diff_trades(
    current_lots: List[Dict[str, Any]],
    state: Dict[str, Any],
    trades: List[Dict[str, Any]],
    dashboard: Dict[str, Any],
    request: Dict[str, Any],
    quotes: Dict[str, Dict[str, Any]],
    trade_day: str,
    request_matches_current: bool,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not state.get("initialized"):
        return [], ["observer_initialized_without_backfill"]

    notes: List[str] = []
    previous_lots = state.get("last_holdings") or []
    prev_by_id = {lot.get("lot_id"): lot for lot in previous_lots}
    cur_by_id = {lot.get("lot_id"): lot for lot in current_lots}
    request_date = request.get("date")
    high_conf = request_matches_current and request_date == trade_day
    base_confidence = "high" if high_conf else "medium"
    source = "holdings_diff+observer_request" if high_conf else "holdings_diff+fallback"

    existing_keys = {
        f"{t.get('date')}|{t.get('action')}|{t.get('lot_id')}|{t.get('qty')}|{t.get('price')}"
        for t in trades
    }
    new_trades: List[Dict[str, Any]] = []

    def append_trade(row: Dict[str, Any]) -> None:
        key = f"{row.get('date')}|{row.get('action')}|{row.get('lot_id')}|{row.get('qty')}|{row.get('price')}"
        if key in existing_keys:
            return
        existing_keys.add(key)
        new_trades.append(row)

    for lot_id, cur in cur_by_id.items():
        prev = prev_by_id.get(lot_id)
        if not prev:
            price = cur["cost"] or quotes.get(cur["symbol"], {}).get("price")
            append_trade(
                build_trade(
                    make_trade_id(trades + new_trades),
                    "BUY",
                    cur,
                    cur["qty"],
                    trade_day,
                    price,
                    base_confidence,
                    source,
                    dashboard,
                )
            )
            continue

        qty_delta = cur["qty"] - to_int(prev.get("qty"))
        if qty_delta > 0:
            price = cur["cost"] or quotes.get(cur["symbol"], {}).get("price")
            append_trade(
                build_trade(
                    make_trade_id(trades + new_trades),
                    "ADD",
                    cur,
                    qty_delta,
                    trade_day,
                    price,
                    base_confidence,
                    source,
                    dashboard,
                )
            )
        elif qty_delta < 0:
            price = quotes.get(cur["symbol"], {}).get("price") or to_float(prev.get("cost")) or None
            append_trade(
                build_trade(
                    make_trade_id(trades + new_trades),
                    "SELL",
                    cur,
                    abs(qty_delta),
                    trade_day,
                    price,
                    base_confidence if price else "low",
                    "holdings_diff+market_close",
                    dashboard,
                    open_ref=lot_id,
                    open_cost=to_float(prev.get("cost")),
                )
            )
        elif (
            abs(cur["cost"] - to_float(prev.get("cost"))) > 0.000001
            or cur.get("buy_date") != prev.get("buy_date")
        ):
            notes.append(f"metadata_edit:{lot_id}")

    for lot_id, prev in prev_by_id.items():
        if lot_id in cur_by_id:
            continue
        symbol = prev.get("symbol")
        lot = dict(prev)
        lot["lot_id"] = lot_id
        price = quotes.get(symbol, {}).get("price") or to_float(prev.get("cost")) or None
        append_trade(
            build_trade(
                make_trade_id(trades + new_trades),
                "SELL",
                lot,
                to_int(prev.get("qty")),
                trade_day,
                price,
                base_confidence if price else "low",
                "holdings_diff+market_close",
                dashboard,
                open_ref=lot_id,
                open_cost=to_float(prev.get("cost")),
            )
        )

    return new_trades, notes


def calc_positions_mv(lots: List[Dict[str, Any]], quotes: Dict[str, Dict[str, Any]]) -> Tuple[float, List[str]]:
    value = 0.0
    notes: List[str] = []
    for lot in lots:
        symbol = lot["symbol"]
        price = quotes.get(symbol, {}).get("price")
        source = "market"
        if not price:
            price = lot["cost"]
            source = "cost_fallback"
            notes.append(f"price_fallback:{symbol}")
        value += price * lot["qty"]
        lot["market_price"] = round(price, 6)
        lot["market_source"] = source
    return round(value, 2), notes


def upsert_snapshot(snapshots: List[Dict[str, Any]], snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    kept = [row for row in snapshots if row.get("date") != snapshot.get("date")]
    kept.append(snapshot)
    kept.sort(key=lambda row: row.get("date", ""))
    return kept


def max_drawdown_pct(values: List[float]) -> float:
    peak = None
    worst = 0.0
    for value in values:
        if value <= 0:
            continue
        peak = value if peak is None else max(peak, value)
        if peak:
            worst = min(worst, value / peak - 1)
    return round(worst * 100, 4)


def cumulative_return(first: Optional[float], last: Optional[float]) -> Optional[float]:
    if not first or not last:
        return None
    return round((last / first - 1) * 100, 4)


def parse_day(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except Exception:
        return None


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def build_stats(
    snapshots: List[Dict[str, Any]],
    trades: List[Dict[str, Any]],
    state: Dict[str, Any],
    data_notes: List[str],
) -> Dict[str, Any]:
    snapshots = sorted(snapshots, key=lambda row: row.get("date", ""))
    latest = snapshots[-1] if snapshots else {}
    total_asset = to_float(latest.get("total_asset"))
    first_snapshot = snapshots[0] if snapshots else {}
    performance_base_asset = to_float(first_snapshot.get("total_asset")) or LEGACY_VIRTUAL_PRINCIPAL
    performance_base_date = first_snapshot.get("date")
    asset_values = [to_float(row.get("total_asset")) for row in snapshots]
    sells = [t for t in trades if t.get("action") == "SELL" and t.get("pnl_amount") is not None]
    wins = [t for t in sells if to_float(t.get("pnl_amount")) > 0]
    losses = [t for t in sells if to_float(t.get("pnl_amount")) < 0]
    avg_win = sum(to_float(t.get("pnl_amount")) for t in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(to_float(t.get("pnl_amount")) for t in losses) / len(losses)) if losses else 0
    holding_days = []
    by_lot = {t.get("lot_id"): t for t in trades if t.get("action") in {"BUY", "ADD"}}
    for sell in sells:
        buy = by_lot.get(sell.get("open_ref") or sell.get("lot_id"))
        if not buy:
            continue
        try:
            d0 = datetime.strptime(buy.get("date"), "%Y-%m-%d").date()
            d1 = datetime.strptime(sell.get("date"), "%Y-%m-%d").date()
            holding_days.append(max((d1 - d0).days, 0))
        except Exception:
            continue

    metric_notes: List[str] = []

    def benchmark_close(row: Dict[str, Any], key: str) -> Optional[float]:
        value = ((row.get("benchmarks") or {}).get(key) or {}).get("close")
        close = to_float(value, 0)
        return close or None

    def window_excess(window_rows: List[Dict[str, Any]], key: str) -> Tuple[Optional[float], Optional[float]]:
        usable = [
            row for row in window_rows
            if to_float(row.get("total_asset"), 0) > 0 and benchmark_close(row, key)
        ]
        if len(usable) < 2:
            return None, None
        start_row = usable[0]
        end_row = usable[-1]
        xplan_ret = cumulative_return(
            to_float(start_row.get("total_asset"), 0),
            to_float(end_row.get("total_asset"), 0),
        )
        bench_ret = cumulative_return(
            benchmark_close(start_row, key),
            benchmark_close(end_row, key),
        )
        if xplan_ret is None or bench_ret is None:
            return bench_ret, None
        return bench_ret, round(xplan_ret - bench_ret, 4)

    def rolling_window_rows() -> Optional[List[Dict[str, Any]]]:
        if not snapshots:
            return None
        end_day = parse_day(snapshots[-1].get("date"))
        if not end_day:
            return None
        cutoff = add_months(end_day, -3)
        start_idx = None
        for idx, row in enumerate(snapshots):
            row_day = parse_day(row.get("date"))
            if row_day and row_day <= cutoff:
                start_idx = idx
        if start_idx is None:
            return None
        return snapshots[start_idx:]

    def bench_stats(key: str, role: str, name: str, tr_code: str, price_code: str = "") -> Dict[str, Any]:
        bench_ret, excess = window_excess(snapshots, key)
        rolling_rows = rolling_window_rows()
        if rolling_rows is None:
            rolling_excess = excess
            metric_notes.append("rolling_3m_window_insufficient")
        else:
            _, rolling_excess = window_excess(rolling_rows, key)
        return {
            "name": name,
            "total_return_code": tr_code,
            "price_code": price_code,
            "cumulative_return_pct": bench_ret,
            "cumulative_excess_pct": excess,
            "rolling_3m_excess_pct": rolling_excess,
            "role": role,
        }

    low_conf = [t for t in trades if t.get("confidence") == "low" or t.get("needs_review")]
    honest_notes = [
        "pnl_nets_sell_commission_only",
        "holding_days_excludes_pre_observation_lots",
        "drawdown_observation_window_only",
        "return_base_observation_start",
    ]
    history_rebuilt = bool(state.get("history_rebuilt", False))
    total_return = round((total_asset / performance_base_asset - 1) * 100, 4) if total_asset and performance_base_asset else 0.0

    hs300 = bench_stats("hs300_tr", "canonical", "沪深300全收益", "H00300", "000300")
    csi500 = bench_stats("csi500_tr", "risk_match", "中证500全收益", "H00905", "000905")
    enhanced = bench_stats("enhanced_ref", "opportunity_cost", "宽基增强参考", "", "")
    enhanced.update(
        {
            "basis": "中证500全收益 + 假设增强 alpha - 假设费用",
            "is_assumption": True,
        }
    )
    fallback_notes = list(dict.fromkeys(data_notes + state.get("audit_notes", [])[-20:] + metric_notes + honest_notes))

    condition_a = hs300.get("rolling_3m_excess_pct")
    condition_b = total_return
    graduation_a = max(0, min(100, round((condition_a or 0) / 5 * 100, 1)))
    graduation_b = max(0, min(100, round(condition_b / 15 * 100, 1)))
    dd = max_drawdown_pct(asset_values)
    circuit_a = max(0, min(100, round(abs(dd) / 25 * 100, 1)))
    recent = sells[-20:]
    recent_win_rate = (len([t for t in recent if to_float(t.get("pnl_amount")) > 0]) / len(recent) * 100) if recent else None

    return {
        "generated_at": now_text(),
        "principal": performance_base_asset,
        "legacy_virtual_principal": LEGACY_VIRTUAL_PRINCIPAL,
        "return_base": {
            "date": performance_base_date,
            "asset": performance_base_asset,
            "basis": "right_wheel_observation_start",
        },
        "data_quality": {
            "trade_count": len(trades),
            "low_confidence_trade_count": len(low_conf),
            "history_rebuilt": history_rebuilt,
            "snapshot_count": len(snapshots),
            "last_observe_hash": state.get("last_processed_hash"),
            "notes": fallback_notes[:40],
        },
        "summary": {
            "total_return_pct": total_return,
            "max_drawdown_pct": dd,
            "win_rate_pct": round(len(wins) / len(sells) * 100, 2) if sells else None,
            "profit_loss_ratio": round(avg_win / avg_loss, 4) if avg_loss else None,
            "avg_holding_days": round(sum(holding_days) / len(holding_days), 2) if holding_days else None,
        },
        "benchmarks": {
            "hs300": hs300,
            "csi500": csi500,
            "enhanced_ref": enhanced,
        },
        "graduation": {
            "condition_a_progress_pct": graduation_a,
            "condition_b_progress_pct": graduation_b,
            "status": "observing",
            "message": "未达毕业观察线",
        },
        "circuit_breaker": {
            "condition_a_progress_pct": circuit_a,
            "condition_b_progress_pct": 0,
            "condition_c_progress_pct": 0 if recent_win_rate is None else max(0, min(100, round((40 - recent_win_rate) / 40 * 100, 1))),
            "status": "normal",
            "message": "未触发熔断",
        },
        "series": build_chart_series(snapshots),
    }


def build_chart_series(snapshots: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    snapshots = sorted(snapshots, key=lambda row: row.get("date", ""))
    if not snapshots:
        return {"xplan": [], "hs300": [], "csi500": [], "enhanced_ref": []}

    def line(getter) -> List[Dict[str, Any]]:
        base = None
        out = []
        for row in snapshots:
            value = to_float(getter(row), 0)
            if not value:
                continue
            if base is None:
                base = value
            out.append({"date": row.get("date"), "value": round(value / base * 100, 4)})
        return out

    return {
        "xplan": line(lambda row: row.get("total_asset")),
        "hs300": line(lambda row: ((row.get("benchmarks") or {}).get("hs300_tr") or {}).get("close")),
        "csi500": line(lambda row: ((row.get("benchmarks") or {}).get("csi500_tr") or {}).get("close")),
        "enhanced_ref": line(lambda row: ((row.get("benchmarks") or {}).get("enhanced_ref") or {}).get("close")),
    }


def enhanced_close(csi500_close: Optional[float], snapshots: List[Dict[str, Any]], target_day: str) -> Optional[float]:
    if not csi500_close:
        return None
    if not snapshots:
        return csi500_close
    first_date = snapshots[0].get("date") or target_day
    try:
        d0 = datetime.strptime(first_date, "%Y-%m-%d").date()
        d1 = datetime.strptime(target_day, "%Y-%m-%d").date()
        days = max((d1 - d0).days, 0)
    except Exception:
        days = 0
    return round(csi500_close * ((1 + ENHANCED_ALPHA_NET) ** (days / 365)), 6)


def observe_once(files: Dict[str, str], target_day: str) -> Dict[str, str]:
    holdings = parse_json(files.get(FILE_HOLDINGS, ""), {"cash_available": 0, "holdings": []})
    dashboard = parse_json(files.get(FILE_DASHBOARD, ""), {})
    request = parse_json(files.get(FILE_OBSERVER_REQUEST, ""), {})
    state = parse_json(files.get(FILE_STATE, ""), {})
    trades = parse_jsonl(files.get(FILE_TRADES, ""))
    snapshots = parse_jsonl(files.get(FILE_SNAPSHOTS, ""))

    canonical = canonical_holdings(holdings)
    current_hash = holdings_hash(holdings)
    previous_lots = state.get("last_holdings") or []
    known_lot_ids = [lot.get("lot_id") for lot in previous_lots] + [t.get("lot_id") for t in trades]
    current_lots, lot_notes = assign_current_lots(canonical, previous_lots, known_lot_ids)
    request_matches_current = (
        request.get("holdings_hash") == current_hash
        or request.get("holdings_canonical") == canonical
    )

    symbols = [lot["symbol"] for lot in current_lots] + [lot.get("symbol") for lot in previous_lots]
    quotes = fetch_sina_quotes(symbols)
    new_trades, diff_notes = diff_trades(
        current_lots,
        state,
        trades,
        dashboard,
        request,
        quotes,
        target_day,
        request_matches_current,
    )
    all_trades = trades + new_trades

    positions_mv, mv_notes = calc_positions_mv(current_lots, quotes)
    hs300_close = fetch_csindex_close("H00300", target_day)
    csi500_close = fetch_csindex_close("H00905", target_day)
    data_notes = lot_notes + diff_notes + mv_notes

    if not hs300_close and snapshots:
        hs300_close = to_float(((snapshots[-1].get("benchmarks") or {}).get("hs300_tr") or {}).get("close"), 0) or None
        if hs300_close:
            data_notes.append("hs300_tr_carry_forward")
    if not csi500_close and snapshots:
        csi500_close = to_float(((snapshots[-1].get("benchmarks") or {}).get("csi500_tr") or {}).get("close"), 0) or None
        if csi500_close:
            data_notes.append("csi500_tr_carry_forward")

    snapshot = {
        "date": target_day,
        "cash": canonical["cash_available"],
        "positions_mv": positions_mv,
        "total_asset": round(canonical["cash_available"] + positions_mv, 2),
        "benchmarks": {
            "hs300_tr": {
                "code": "H00300",
                "name": "沪深300全收益",
                "close": hs300_close,
                "source": "csindex" if hs300_close else "missing",
            },
            "csi500_tr": {
                "code": "H00905",
                "name": "中证500全收益",
                "close": csi500_close,
                "source": "csindex" if csi500_close else "missing",
            },
            "enhanced_ref": {
                "name": "宽基增强参考",
                "close": enhanced_close(csi500_close, snapshots, target_day),
                "source": "synthetic",
                "is_assumption": True,
            },
        },
        "confidence": "high" if request_matches_current else "medium",
        "source": "observer_action" if request_matches_current else "nightly_fallback",
    }

    snapshots = upsert_snapshot(snapshots, snapshot)
    state.setdefault("audit_notes", [])
    state["audit_notes"] = (state.get("audit_notes") or [])[-80:] + data_notes
    state.update(
        {
            "initialized": True,
            "updated_at": now_text(),
            "last_processed_hash": current_hash,
            "last_holdings": current_lots,
            "last_cash_available": canonical["cash_available"],
            "last_snapshot_date": target_day,
            "last_new_trade_count": len(new_trades),
        }
    )

    stats = build_stats(snapshots, all_trades, state, data_notes)

    return {
        FILE_TRADES: dump_jsonl(all_trades),
        FILE_SNAPSHOTS: dump_jsonl(snapshots),
        FILE_STATE: dump_json(state),
        FILE_STATS: dump_json(stats),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_text(), help="观察日期 YYYY-MM-DD")
    args = parser.parse_args()

    print(f"📈 X-Plan observe start: {args.date}")
    try:
        files = read_gist_files()
        updates = observe_once(files, args.date)
        write_gist_files(updates)
        print(
            "✅ observe 完成: "
            f"{FILE_TRADES}, {FILE_SNAPSHOTS}, {FILE_STATS}, {FILE_STATE}"
        )
        return 0
    except Exception as exc:
        print(f"❌ observe 失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
