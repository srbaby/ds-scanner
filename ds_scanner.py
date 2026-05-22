# /// script
# dependencies = [
#   "requests",
#   "pandas",
#   "akshare",
#   "lxml",
#   "beautifulsoup4"
# ]
# ///

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X-DeepSeek 波段验证系统 - 尾盘扫描器 v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
核心升级 v3.0（动态止盈与状态记忆 完全体）:
  - ⭐ [新增] 动态止盈拦截：计算并传入 max_drawdown，严格执行最高点回撤 3% 强制清仓纪律。
  - ⭐ [新增] 状态记忆机制：识别 holdings.json 中的 is_reduced 标签，解决减半仓后重复提示减仓的死循环Bug。
  - ⭐ [优化] 半仓格局期真正实现“零压力底仓”，不再受 +8% 减仓线干扰，直达 +12% 终极止盈。

历史核心升级 v2.6-v2.7（价值波段同步）:
  - ⭐ 彻底废除闪电战止损（T+1/T+2/T+3节点）。
  - ⭐ 引入三道防线：逻辑止损（政策分<15）、价格止损（-8%）、时间止损（T+21）。

运行时间: 每日14:30（量比以14:55尾盘为准）
输出格式: 原始数据（不含评分），DeepSeek基于四维框架评分
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

# ============================================================
# 系统全局常量
# ============================================================
SYSTEM_VERSION = "3.0"
SYSTEM_NAME = "X-DeepSeek 波段验证系统"
METHODOLOGY_DESC = "价值波段 Value-Swing"

os.environ["TZ"] = "Asia/Shanghai"
if hasattr(time, "tzset"):
    time.tzset()

# 禁用代理
for k in [
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
]:
    if k in os.environ:
        del os.environ[k]

# ============================================================
# 配置区 - 硬编码兜底配置
# ============================================================

# ETF观察池（基础配置，包含代码映射）
ETF_WATCHLIST_BASE = {
    # --- S级：核心科技进攻 ---
    "sh588000": {"name": "科创50ETF", "category": "科技成长"},
    "sh512480": {"name": "半导体ETF", "category": "半导体"},
    "sh515880": {"name": "通信ETF", "category": "通信"},
    "sz159766": {"name": "旅游ETF", "category": "旅游"},
    "sh515120": {"name": "创新药ETF", "category": "创新药"},
    # --- A级：牛市旗手与新能源 ---
    "sz159851": {"name": "金融科技", "category": "金融科技"},
    "sh512880": {"name": "证券ETF", "category": "证券"},
    "sz159915": {"name": "创业板ETF", "category": "科技成长"},
    "sh515030": {"name": "新能车ETF", "category": "新能车"},
    "sz159755": {"name": "电池ETF", "category": "电池"},
    # --- B级：周期轮动 ---
    "sh515220": {"name": "煤炭ETF", "category": "煤炭"},
    "sh516150": {"name": "稀土ETF", "category": "稀土"},
    "sh512400": {"name": "有色ETF", "category": "有色"},
    "sh516020": {"name": "化工ETF", "category": "化工"},
    # --- 消费与港股 ---
    "sh512690": {"name": "酒ETF", "category": "酒"},
    "sh513180": {"name": "恒生科技", "category": "港股科技"},
    # --- 观察区 ---
    "sh515790": {"name": "光伏ETF", "category": "光伏"},
    "sh512660": {"name": "军工ETF", "category": "国防安全"},
}

# 板块基础分硬编码兜底（0-15分）
DEFAULT_BASE_SCORES = {
    # 国家战略级（12-15分）
    "半导体": 15,
    "AI算力": 15,
    "通信": 13,
    "创新药": 13,
    # 重点支持级（9-12分）
    "新能车": 11,
    "储能": 10,
    "科技成长": 10,
    "电池": 9,
    # 稳增长级（6-9分）
    "大消费": 8,
    "旅游": 7,
    "酒": 8,
    "医药": 7,
    # 中性周期级（4-6分）
    "稀土": 8,  # 战略资源，单独分类
    "有色": 6,
    "化工": 5,
    "煤炭": 4,
    "金融科技": 6,
    "港股科技": 5,
    # 政策工具级（2-4分）
    "证券": 3,
    "银行": 2,
    # 观察区
    "光伏": 6,
    "国防安全": 7,
}

# 硬编码持仓兜底
DEFAULT_HOLDINGS = {"cash_available": 157686.21, "holdings": []}

# 波段管理参数（v3.0价值波段规则）
# 三道防线：逻辑止损（政策分<15）→ 价格止损（-8%）→ 时间止损（21天）
WAVE_CONFIG = {
    "快速波段": {
        "max_days": 21,
    },
    "标准波段": {
        "max_days": 21,
    },
}

# 逻辑止损阈值（政策分跌破此值触发）
POLICY_LOGIC_STOP_THRESHOLD = 15

# 风控参数
HARD_STOP_LOSS = -8.0
DYNAMIC_STOP_TRIGGER = 2.0
DYNAMIC_STOP_MOVE = 1.0

# 请求配置
HEADERS = {"Referer": "http://finance.sina.com.cn"}
PROXIES = {"http": None, "https": None}

# ============================================================
# Gist 持久化配置（环境变量注入，本地不设置则自动降级本地文件）
# ============================================================
GIST_ID = os.environ.get("DS_SCANNER_GIST_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def _gist_headers() -> Dict:
    if GITHUB_TOKEN:
        return {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        }
    return {"Content-Type": "application/json"}


def _gist_get_file(filename: str) -> Optional[str]:
    """从 Gist 读取指定文件内容，失败返回 None"""
    if not GIST_ID:
        return None
    try:
        r = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_gist_headers(),
            proxies=PROXIES,
            timeout=10,
        )
        if r.status_code == 200:
            content = r.json().get("files", {}).get(filename, {}).get("content")
            if content:
                return content
        else:
            print(f"  ⚠️ Gist 读取失败: HTTP {r.status_code}")
    except Exception as e:
        print(f"  ⚠️ Gist 读取异常: {e}")
    return None


def _gist_put_file(filename: str, content: str) -> bool:
    """将内容写回 Gist 指定文件，成功返回 True"""
    if not GIST_ID or not GITHUB_TOKEN:
        return False
    try:
        import json as _json

        payload = _json.dumps({"files": {filename: {"content": content}}})
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_gist_headers(),
            data=payload,
            proxies=PROXIES,
            timeout=10,
        )
        if r.status_code == 200:
            return True
        else:
            print(f"  ⚠️ Gist 写入失败: HTTP {r.status_code}")
    except Exception as e:
        print(f"  ⚠️ Gist 写入异常: {e}")
    return False


# ============================================================
# 配置文件加载（三级兜底机制）
# ============================================================


def load_base_scores():
    """
    加载板块基础分配置
    优先级：JSON文件 > 硬编码默认值
    """
    config_file = "etf_base_config.json"

    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            print(f"✅ 使用 {config_file} 配置")
            return config.get("scores", DEFAULT_BASE_SCORES)
        except Exception as e:
            print(f"⚠️ 读取 {config_file} 失败: {e}")
            print("\n" + "!" * 60)
            print("🚨 严重警告：etf_base_config.json 读取失败！")
            print("   当前使用硬编码兜底值，与战间期基准严重偏差：")
            print("   ⛔ 持仓止损判断可能完全失效，请立即检查JSON文件！")
            print("!" * 60 + "\n")
            input("   确认已知晓风险，按回车键继续（或 Ctrl+C 退出）...")
            return DEFAULT_BASE_SCORES
    else:
        print("💡 使用默认板块评分（首次运行）")
        generate_base_config_template()
        return DEFAULT_BASE_SCORES


def generate_base_config_template():
    """生成板块基础分配置模板"""
    template = {
        "_meta": {
            "version": SYSTEM_VERSION,  # 替换了硬编码的 "3.0"
            "created": datetime.now().strftime("%Y-%m-%d"),
            "description": "板块政策基础分配置（0-15分），定期手动维护",
            "next_review": (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d"),
        },
        "_update_log": [f"{datetime.now().strftime('%Y-%m-%d')}: v3.0 初始配置"],
        "scores": DEFAULT_BASE_SCORES,
        "_comment": "修改分数后，运行 --refresh-policy 即可生效",
    }

    try:
        with open("etf_base_config.json", "w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        print("📄 已生成 etf_base_config.json 模板，后续可自行修改")
    except Exception as e:
        print(f"⚠️ 生成模板失败: {e}")


def load_holdings():
    """
    加载持仓配置
    优先级：Gist > 本地文件 > 硬编码默认值
    """
    config_file = "holdings.json"

    # 优先从 Gist 读
    if GIST_ID:
        raw = _gist_get_file("holdings.json")
        if raw:
            try:
                config = json.loads(raw)
                print("✅ holdings 已从 Gist 读取")
                # 同步写本地缓存
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                return config
            except Exception as e:
                print(f"  ⚠️ Gist holdings 解析失败: {e}，降级本地文件")

    # 降级：本地文件
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            print(f"✅ 使用本地 {config_file} 配置")
            return config
        except Exception as e:
            print(f"⚠️ 读取 {config_file} 失败: {e}")

    print("💡 使用硬编码持仓配置")
    generate_holdings_template()
    return DEFAULT_HOLDINGS


def generate_holdings_template():
    """生成持仓配置模板"""
    template = {
        "cash_available": 157686.21,
        "holdings": [
            {
                "symbol": "sh512690",
                "qty": 15000,
                "cost": 0.551,
                "buy_date": "2026-02-02",
                "wave_type": "",
                "is_reduced": False,
                "_comment": "wave_type留空=自动推断。is_reduced用于标记是否已完成半仓止盈",
            }
        ],
    }

    try:
        with open("holdings.json", "w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        print("📄 已生成 holdings.json 模板，请填入实际持仓")
    except Exception as e:
        print(f"⚠️ 生成模板失败: {e}")


def should_refresh_policy():
    """判断是否需要刷新policy分数"""
    if not os.path.exists("etf_pool.json"):
        return True, "首次运行，全量扫描"

    try:
        with open("etf_pool.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            last_scan = data.get("_meta", {}).get("last_scan", "1970-01-01")
            days_ago = (datetime.now() - datetime.strptime(last_scan, "%Y-%m-%d")).days
    except:
        return True, "配置文件损坏，重新扫描"

    if days_ago >= 1:
        return True, f"距上次扫描{days_ago}天，每日刷新"

    return False, f"今日已扫描，跳过"


# ============================================================
# 数据获取函数
# ============================================================


def fetch_sina_realtime(codes: List[str]) -> Dict:
    """获取新浪实时行情（批量）"""
    if not codes:
        return {}

    url = f"http://hq.sinajs.cn/list={','.join(codes)}"
    try:
        resp = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=10)
        resp.encoding = "gbk"
        results = {}

        for line in resp.text.strip().split("\n"):
            if '="' not in line:
                continue
            code = line.split("var hq_str_")[1].split("=")[0]
            content = line.split('="')[1].strip('";\n')
            parts = content.split(",")

            if len(parts) < 10:
                continue

            results[code] = {
                "name": parts[0],
                "open": float(parts[1]) if parts[1] else 0,
                "last_close": float(parts[2]) if parts[2] else 0,
                "price": float(parts[3]) if parts[3] else 0,
                "high": float(parts[4]) if parts[4] else 0,
                "low": float(parts[5]) if parts[5] else 0,
                "volume": float(parts[8]) if parts[8] else 0,
                "amount": float(parts[9]) if parts[9] else 0,
            }

            if results[code]["last_close"] > 0:
                results[code]["change_pct"] = (
                    results[code]["price"] / results[code]["last_close"] - 1
                ) * 100
            else:
                results[code]["change_pct"] = 0

        return results
    except Exception as e:
        print(f"  ⚠️ 新浪数据获取失败: {e}")
        return {}


def fetch_sina_history(code: str, days: int = 30) -> Optional[pd.DataFrame]:
    """获取历史K线数据"""
    try:
        import akshare as ak

        df = ak.fund_etf_hist_sina(symbol=code)

        if df.empty:
            return None

        df = df.tail(days).copy()
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["open"] = df["open"].astype(float)

        df["ma5"] = df["close"].rolling(5).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        df["vol_ma5"] = df["volume"].rolling(5).mean()

        return df
    except Exception as e:
        return None


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> float:
    """计算RSI指标"""
    if len(df) < period + 1:
        return 50.0

    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)

    ma_up = up.ewm(com=period - 1, adjust=False).mean()
    ma_down = down.ewm(com=period - 1, adjust=False).mean()

    rsi = 100 - (100 / (1 + ma_up / ma_down))

    return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0


def fetch_index_sina() -> Dict:
    """获取沪深300指数"""
    url = "http://hq.sinajs.cn/list=s_sh000300"
    try:
        resp = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=5)
        resp.encoding = "gbk"
        content = resp.text.split('="')[1].strip('";\n')
        parts = content.split(",")

        return {"price": float(parts[1]), "change_pct": float(parts[3]), "ok": True}
    except:
        return {"ok": False}


# ============================================================
# policy评分计算（三维评分）
# ============================================================


def calc_tech_position_score(
    price: float, ma20: float, rsi: float, vol_ratio: float
) -> int:
    score = 0
    if ma20 > 0:
        price_ma20_ratio = price / ma20
        if price_ma20_ratio > 1.05:
            score += 3
        elif price_ma20_ratio > 1.0:
            score += 2
        elif price_ma20_ratio > 0.95:
            score += 1

    if 50 <= rsi <= 70:
        score += 3
    elif 40 <= rsi < 50:
        score += 2
    elif rsi > 70:
        score += 1

    if vol_ratio > 1.2:
        score += 2
    elif vol_ratio > 0.8:
        score += 1

    return score


def calc_relative_strength_score(etf_change: float, index_change: float) -> int:
    score = 0
    relative_change = etf_change - index_change
    if relative_change > 1.0:
        score += 7
    elif relative_change > 0.5:
        score += 5
    elif relative_change > 0:
        score += 3
    elif relative_change > -0.5:
        score += 1
    return score


def refresh_etf_pool(base_scores: Dict, index_change: float):
    print("⏳ 正在刷新ETF池policy分数...")
    etf_pool = {}
    codes = list(ETF_WATCHLIST_BASE.keys())
    realtime = fetch_sina_realtime(codes)

    for code, info in ETF_WATCHLIST_BASE.items():
        if code not in realtime:
            continue

        rt = realtime[code]
        history = fetch_sina_history(code, 30)

        if history is None or len(history) < 20:
            base_score = base_scores.get(info["category"], 5)
            etf_pool[code] = {
                "name": info["name"],
                "policy": base_score,
                "category": info["category"],
                "_breakdown": {"base": base_score, "tech": 0, "strength": 0},
            }
            continue

        last = history.iloc[-1]
        rsi = calculate_rsi(history, 14)
        ma20 = last["ma20"] if pd.notna(last["ma20"]) else rt["price"]
        vol_ma5 = (
            last["vol_ma5"] if pd.notna(last["vol_ma5"]) and last["vol_ma5"] > 0 else 1
        )
        vol_ratio = (
            rt["volume"] * calc_volume_time_factor() / vol_ma5 if vol_ma5 > 0 else 1.0
        )

        base_score = base_scores.get(info["category"], 5)
        tech_score = calc_tech_position_score(rt["price"], ma20, rsi, vol_ratio)
        strength_score = calc_relative_strength_score(rt["change_pct"], index_change)

        policy = base_score + tech_score + strength_score

        etf_pool[code] = {
            "name": info["name"],
            "policy": policy,
            "category": info["category"],
            "_breakdown": {
                "base": base_score,
                "tech": tech_score,
                "strength": strength_score,
            },
        }
        print(".", end="", flush=True)

    output = {
        "_meta": {
            "last_scan": datetime.now().strftime("%Y-%m-%d"),
            "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "index_change": index_change,
            "version": SYSTEM_VERSION,  # 替换了硬编码的 "3.0"
        },
        "etfs": etf_pool,
    }

    _save_etf_pool(output)

    print(" 完成!")
    print(f"✅ 已更新{len(etf_pool)}个ETF的policy分数")
    return etf_pool


def _save_etf_pool(data: dict):
    """保存 etf_pool：本地文件 + Gist（如已配置）"""
    # 写本地文件
    with open("etf_pool.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 同步写 Gist
    if GIST_ID and GITHUB_TOKEN:
        content = json.dumps(data, ensure_ascii=False, indent=2)
        ok = _gist_put_file("etf_pool.json", content)
        if ok:
            print("✅ etf_pool 已同步到 Gist")


def load_etf_pool():
    """读取 etf_pool：Gist > 本地文件 > 空"""
    # 优先从 Gist 读
    if GIST_ID:
        raw = _gist_get_file("etf_pool.json")
        if raw:
            try:
                data = json.loads(raw)
                print("✅ etf_pool 已从 Gist 读取")
                # 同步写本地缓存
                with open("etf_pool.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return data.get("etfs", {})
            except Exception as e:
                print(f"  ⚠️ Gist 内容解析失败: {e}，降级本地文件")

    # 降级：本地文件
    if os.path.exists("etf_pool.json"):
        try:
            with open("etf_pool.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            print("✅ etf_pool 已从本地文件读取")
            return data.get("etfs", {})
        except Exception as e:
            print(f"  ⚠️ 本地 etf_pool.json 读取失败: {e}")

    return {}


# ============================================================
# 自动推断函数
# ============================================================


def auto_wave_type(user_input: str, buy_reason: str, holding_days: int) -> str:
    if user_input and user_input in ["快速波段", "标准波段"]:
        return user_input
    if holding_days <= 3:
        return "快速波段"
    fast_signals = ["突破", "放量", "强势", "RSI<30"]
    if any(s in buy_reason for s in fast_signals):
        return "快速波段"
    return "标准波段"


def auto_infer_holding_info(
    h: Dict, history: Optional[pd.DataFrame], holding_days: int
) -> Dict:
    symbol = h["symbol"]
    if symbol in ETF_WATCHLIST_BASE:
        name = ETF_WATCHLIST_BASE[symbol]["name"]
    else:
        name = symbol.replace("sh", "").replace("sz", "")

    buy_reason = "手动买入"
    buy_score = 75

    if history is not None and len(history) >= holding_days:
        try:
            buy_date = datetime.strptime(h["buy_date"], "%Y-%m-%d")
            history_with_date = history.copy()
            if "date" in history_with_date.columns:
                history_with_date["date"] = pd.to_datetime(history_with_date["date"])
                buy_day_data = history_with_date[
                    history_with_date["date"] <= buy_date
                ].tail(3)
            else:
                buy_day_data = history.tail(holding_days + 3).head(3)

            if len(buy_day_data) > 0:
                last_day = buy_day_data.iloc[-1]
                vol_ma5 = (
                    last_day["vol_ma5"]
                    if pd.notna(last_day["vol_ma5"]) and last_day["vol_ma5"] > 0
                    else 1
                )
                vol_ratio = last_day["volume"] / vol_ma5 if vol_ma5 > 0 else 1.0
                rsi = calculate_rsi(
                    buy_day_data.tail(14) if len(history) >= 14 else buy_day_data, 14
                )
                ma20 = (
                    last_day["ma20"]
                    if pd.notna(last_day["ma20"])
                    else last_day["close"]
                )
                price_vs_ma20 = (
                    ((last_day["close"] - ma20) / ma20 * 100) if ma20 > 0 else 0
                )

                reasons = []
                if vol_ratio < 0.7:
                    reasons.append(f"缩量({vol_ratio:.2f})")
                    buy_score += 5
                if rsi < 50:
                    reasons.append(f"RSI{rsi:.0f}")
                    buy_score += 3
                if price_vs_ma20 < 0:
                    reasons.append("回踩MA20")
                    buy_score += 3
                elif price_vs_ma20 > 2:
                    reasons.append("突破MA20")
                    buy_score += 5
                if vol_ratio > 1.5:
                    reasons.append(f"放量({vol_ratio:.2f})")
                    buy_score += 5

                if reasons:
                    buy_reason = "+".join(reasons)
                else:
                    buy_reason = "技术买点"
        except Exception:
            pass

    wave_type = auto_wave_type(h.get("wave_type", ""), buy_reason, holding_days)
    return {
        "name": name,
        "wave_type": wave_type,
        "buy_score": min(buy_score, 90),
        "buy_reason": buy_reason,
    }


# ============================================================
# 持仓波段管理核心函数
# ============================================================


def identify_wave_status(holding_days: int, wave_type: str) -> Tuple[str, str, str]:
    config = WAVE_CONFIG.get(wave_type, WAVE_CONFIG["快速波段"])
    max_days = config["max_days"]

    days_left = max_days - holding_days
    if holding_days == 0:
        return ("买入日", "🟢", "今日买入，关注政策分变化和-8%止损线")
    elif holding_days < 5:
        return (
            "洗盘观察期",
            "🟢",
            f"第{holding_days}天，给主力3-5天洗盘空间，坚定持有",
        )
    elif holding_days < max_days:
        return (
            "价值持有期",
            "🟢",
            f"第{holding_days}天，距T+21时间止损还有{days_left}天",
        )
    else:
        return ("超时", "🔴", f"第{holding_days}天，已触发T+21时间止损，强制换股")


def calculate_dynamic_stop(cost: float, current: float, peak: float) -> float:
    if current <= cost:
        return cost * (1 + HARD_STOP_LOSS / 100)
    gain_pct = ((peak - cost) / cost * 100) if cost > 0 else 0
    if gain_pct > DYNAMIC_STOP_TRIGGER:
        moves = int(gain_pct / DYNAMIC_STOP_TRIGGER)
        dynamic_stop = cost * (
            1 + HARD_STOP_LOSS / 100 + moves * DYNAMIC_STOP_MOVE / 100
        )
        return max(dynamic_stop, cost)
    else:
        return cost * (1 + HARD_STOP_LOSS / 100)


def generate_wave_action(
    h: Dict,
    price: float,
    profit_pct: float,
    holding_days: int,
    phase: str,
    stop_loss: float,
    policy_score: int = None,
    max_drawdown: float = 0.0,
) -> str:
    """生成持仓操作建议（v3.0价值波段规则，加入动态止盈）"""
    wave_type = h["wave_type"]
    config = WAVE_CONFIG.get(wave_type, WAVE_CONFIG["快速波段"])
    max_days = config["max_days"]
    cost = h["cost"]

    # 防线1：价格止损
    if profit_pct <= HARD_STOP_LOSS:
        return f"🔴 立即止损（触发-8%硬止损，不等尾盘，市价清仓）"

    # 防线2：逻辑止损
    if policy_score is not None and policy_score < POLICY_LOGIC_STOP_THRESHOLD:
        return (
            f"🔴 逻辑止损（板块政策分{policy_score}<15，政策逻辑证伪，尾盘14:55清仓）"
        )

    # 防线3：时间止损
    if holding_days >= max_days:
        return f"⏰ 尾盘平仓（第{holding_days}天，T+21时间止损触发，强制换股）"

    # 正常持有期参数
    hard_stop_price = cost * (1 + HARD_STOP_LOSS / 100)
    space_to_stop = ((price - hard_stop_price) / price * 100) if price > 0 else 0
    days_left = max_days - holding_days

    is_reduced = h.get("is_reduced", False)

    # v3.0 核心：止盈提示与拦截
    if is_reduced:
        if max_drawdown <= -3.0:
            return f"🔴 动态止盈触发（已从最高点回撤 {max_drawdown:.2f}%，跌破-3%防线，尾盘全部清仓！）"
        elif profit_pct >= 12.0:
            return f"🎯 终极止盈触发（浮盈 {profit_pct:.2f}% ≥ 12%，强制全部清仓，落袋为安！）"
        else:
            return (
                f"✅ 格局剩余仓位（浮盈 {profit_pct:.2f}%，距高点回撤 {max_drawdown:.2f}%）"
                f" | 纪律：回撤达-3% 或 浮盈达+12% 全清"
            )
    elif profit_pct >= 8.0:
        return (
            f"🎯 首次减仓（浮盈{profit_pct:.2f}%≥8%，强制触发：卖出50%锁定利润）"
            f' | 减仓后请在holdings.json中添加 "is_reduced": true'
        )
    elif profit_pct >= 5.0:
        return (
            f"✅ 观察止盈（浮盈{profit_pct:.2f}%，接近首次减仓线+8%）"
            f" | 距-8%止损线还有{space_to_stop:.1f}% | 持仓第{holding_days}天/距T+21还有{days_left}天"
        )

    # 洗盘期特殊提示
    if holding_days < 5 and profit_pct < 0:
        return (
            f"🟢 洗盘持有（浮亏{profit_pct:.2f}%，ETF价值托底，给主力{5 - holding_days}天洗盘空间）"
            f" | 距-8%硬止损线还有{space_to_stop:.1f}% | 政策分{'正常' if policy_score is None or policy_score >= 15 else f'⚠️{policy_score}接近警戒'}"
        )

    # 常规持有
    policy_status = (
        "正常"
        if policy_score is None or policy_score >= 20
        else (
            f"⚠️{policy_score}接近警戒线(15)"
            if policy_score >= 15
            else f"🔴{policy_score}触发止损"
        )
    )
    return f"✅ 价值持有（{profit_pct:+.2f}%） | 距-8%止损线还有{space_to_stop:.1f}% | 持仓第{holding_days}天/距T+21还有{days_left}天 | 政策分{policy_status}"


# ============================================================
# 扫描逻辑
# ============================================================


def scan_market():
    print("\n⏳ 正在扫描市场...")
    scan_time = datetime.now()
    index = fetch_index_sina()
    codes = list(ETF_WATCHLIST_BASE.keys())
    realtime = fetch_sina_realtime(codes)

    rising = len([v for v in realtime.values() if v.get("change_pct", 0) > 0])
    total = len(realtime)
    advance_ratio = (rising / total * 100) if total > 0 else 0

    if advance_ratio > 60:
        temperature = "🔥普涨"
    elif advance_ratio > 40:
        temperature = "😐震荡"
    else:
        temperature = "❄️普跌"

    return {
        "scan_time": scan_time.strftime("%Y-%m-%d %H:%M"),
        "index": index,
        "rising": rising,
        "total": total,
        "advance_ratio": advance_ratio,
        "temperature": temperature,
        "realtime": realtime,
    }


def scan_holdings_with_wave_management(
    holdings_config: Dict, realtime: Dict, etf_pool: Dict = None
):
    print("⏳ 正在扫描持仓波段状态...")
    holdings_list = holdings_config.get("holdings", [])
    holdings_data = []
    wave_cards = []
    total_value = 0

    for h in holdings_list:
        if h.get("symbol", "").startswith("_"):
            continue
        if h.get("qty", 0) == 0:
            continue

        code = h["symbol"]
        price = (
            realtime[code]["price"]
            if code in realtime
            else fetch_sina_realtime([code]).get(code, {}).get("price", 0)
        )
        if price == 0:
            continue

        profit_pct = ((price - h["cost"]) / h["cost"] * 100) if h["cost"] > 0 else 0
        market_value = price * h["qty"]
        total_value += market_value

        buy_date = datetime.strptime(h["buy_date"], "%Y-%m-%d")
        holding_days = (datetime.now() - buy_date).days

        history = fetch_sina_history(code, 30)
        inferred = auto_infer_holding_info(h, history, holding_days)
        h.update(inferred)

        phase, emoji, phase_desc = identify_wave_status(holding_days, h["wave_type"])

        max_drawdown = 0.0
        stop_loss = h["cost"] * (1 + HARD_STOP_LOSS / 100)

        if history is not None and len(history) > 0:
            recent_days = min(holding_days + 5, len(history))
            holding_period = history.tail(recent_days)
            if len(holding_period) > 0:
                peak = holding_period["high"].max()
                max_drawdown = ((price - peak) / peak * 100) if peak > 0 else 0.0
                stop_loss = calculate_dynamic_stop(h["cost"], price, peak)

        policy_score = etf_pool.get(code, {}).get("policy") if etf_pool else None

        # v3.0 核心传参：max_drawdown
        action = generate_wave_action(
            h,
            price,
            profit_pct,
            holding_days,
            phase,
            stop_loss,
            policy_score,
            max_drawdown,
        )

        hard_stop_price = h["cost"] * (1 + HARD_STOP_LOSS / 100)
        space_to_hard_stop = (
            ((price - hard_stop_price) / price * 100) if price > 0 else 0
        )
        days_left = (
            WAVE_CONFIG.get(h["wave_type"], WAVE_CONFIG["快速波段"])["max_days"]
            - holding_days
        )

        holdings_data.append(
            {
                "symbol": code.replace("sh", "").replace("sz", ""),
                "name": h["name"],
                "qty": h["qty"],
                "cost": h["cost"],
                "price": price,
                "profit_pct": profit_pct,
                "value": market_value,
                "days": holding_days,
                "wave_type": h["wave_type"],
                "phase": phase,
                "emoji": emoji,
                "stop": stop_loss,
                "hard_stop_price": hard_stop_price,
                "space_to_hard_stop": space_to_hard_stop,
                "days_left": days_left,
                "policy_score": policy_score,
                "max_dd": max_drawdown,
                "action": action,
            }
        )

        wave_cards.append(
            {
                "name": h["name"],
                "wave_type": h["wave_type"],
                "emoji": emoji,
                "phase_desc": phase_desc,
                "profit_pct": profit_pct,
                "buy_score": h["buy_score"],
                "buy_reason": h["buy_reason"],
                "action": action,
                "stop_loss": stop_loss,
                "hard_stop_price": hard_stop_price,
                "space_to_hard_stop": space_to_hard_stop,
                "holding_days": holding_days,
                "days_left": days_left,
                "max_days": WAVE_CONFIG.get(h["wave_type"], WAVE_CONFIG["快速波段"])[
                    "max_days"
                ],
                "policy_score": policy_score,
            }
        )
        print(".", end="", flush=True)

    print(" 完成!")
    return holdings_data, wave_cards, total_value


def calc_volume_time_factor() -> float:
    now = datetime.now()
    h, m = now.hour, now.minute
    total_minutes = 240
    if h < 9 or (h == 9 and m < 30):
        elapsed = total_minutes
    elif h < 11 or (h == 11 and m <= 30):
        elapsed = (h - 9) * 60 + m - 30
    elif h < 13:
        elapsed = 120
    elif h < 15:
        elapsed = 120 + (h - 13) * 60 + m
    else:
        elapsed = total_minutes

    return min(total_minutes / max(elapsed, 1), 8.0)


def scan_etf_pool(etf_pool: Dict, holding_symbols: set, realtime: Dict):
    print("⏳ 正在扫描ETF观察池...")
    etf_list = []

    for code, pool_info in etf_pool.items():
        if code not in realtime:
            continue
        rt = realtime[code]
        history = fetch_sina_history(code, 30)
        if history is None or len(history) < 20:
            continue

        last = history.iloc[-1]
        rsi = calculate_rsi(history, 14)
        ma20 = last["ma20"] if pd.notna(last["ma20"]) else rt["price"]
        vol_ma5 = (
            last["vol_ma5"] if pd.notna(last["vol_ma5"]) and last["vol_ma5"] > 0 else 1
        )
        vol_ratio = (
            rt["volume"] * calc_volume_time_factor() / vol_ma5 if vol_ma5 > 0 else 1.0
        )

        if rt["change_pct"] > 1.0 and vol_ratio > 1.2:
            fund_flow = "💰流入"
        elif rt["change_pct"] < -1.0 and vol_ratio > 1.2:
            fund_flow = "💸流出"
        else:
            fund_flow = "➖平衡"

        position = "✅持仓" if code in holding_symbols else "⭕无"

        etf_list.append(
            {
                "symbol": code.replace("sh", "").replace("sz", ""),
                "name": pool_info["name"],
                "category": pool_info["category"],
                "policy": pool_info["policy"],
                "price": rt["price"],
                "change_pct": rt["change_pct"],
                "vol_ratio": vol_ratio,
                "rsi": rsi,
                "ma20": ma20,
                "fund_flow": fund_flow,
                "position": position,
            }
        )
        print(".", end="", flush=True)

    print(" 完成!")
    return etf_list


# ============================================================
# 生成报告
# ============================================================


def generate_report_v2(
    market, etf_list, holdings_data, wave_cards, total_value, cash_available
):
    """生成 v3.0 格式报告"""
    report = []
    day_num = (datetime.now() - datetime(2026, 2, 4)).days + 1

    report.append(f"# 📡 DS波段扫描 Day {day_num}\n")

    now = datetime.now()
    h, m = now.hour, now.minute

    if h < 9 or (h == 9 and m < 30):
        time_tag, time_warn = (
            "⚠️ 开盘前数据",
            "当前为开盘前，量比无意义。请勿基于此报告做任何买卖决策。",
        )
    elif h < 11 or (h == 11 and m <= 30):
        elapsed = (h - 9) * 60 + m - 30
        time_tag, time_warn = (
            f"🔶 上午盘中数据（{h:02d}:{m:02d}）",
            f"量比已折算（系数×{round(240 / max(elapsed, 1), 2)}）。本报告为参考，不可用于尾盘决策。",
        )
    elif h < 13:
        time_tag, time_warn = (
            f"🔶 午休数据（{h:02d}:{m:02d}）",
            "午休期间量比已折算。本报告为参考，不可用于尾盘决策。",
        )
    elif h == 14 and m < 50:
        elapsed = 120 + (h - 13) * 60 + m
        time_tag, time_warn = (
            f"🔷 下午盘中数据（{h:02d}:{m:02d}）",
            f"量比已折算（系数×{round(240 / max(elapsed, 1), 2)}）。请在14:55重新运行。",
        )
    elif h == 14 and m >= 50:
        time_tag, time_warn = (
            f"✅ 尾盘数据（{h:02d}:{m:02d}）",
            "量比为全天真实值。**本报告可直接用于金牌判断和14:55-15:00执行决策。**",
        )
    else:
        time_tag, time_warn = (
            f"📋 收盘后数据（{h:02d}:{m:02d}）",
            "收盘后数据，可用于复盘分析，不可用于当日交易。",
        )

    report.append(f"## ⏱️ 数据时效：{time_tag}")
    report.append(f"> {time_warn}\n")

    report.append("## 🎯 持仓波段管理卡\n")
    if wave_cards:
        for card in wave_cards:
            profit_emoji = (
                "🟢"
                if card["profit_pct"] > 0
                else "🔴"
                if card["profit_pct"] < -3
                else "🟡"
            )
            ps = card.get("policy_score")
            if ps is None:
                policy_display = "未获取"
            elif ps < POLICY_LOGIC_STOP_THRESHOLD:
                policy_display = f"🔴 {ps}分（已触发逻辑止损）"
            elif ps < 20:
                policy_display = f"🟡 {ps}分（接近警戒线15）"
            else:
                policy_display = f"🟢 {ps}分（安全）"

            report.append(f"### 📍 {card['name']} ({card['wave_type']})\n")
            report.append(f"**波段状态:** {card['emoji']} {card['phase_desc']}")
            report.append(f"**当前盈亏:** {profit_emoji} {card['profit_pct']:+.2f}%")
            report.append(
                f"**买入信息:** ⭐{card['buy_score']}分 | 📝 {card['buy_reason']}"
            )
            report.append(
                f"**风控参数:** 🛑 硬止损价 {card['hard_stop_price']:.3f}（距-8%线还有{card['space_to_hard_stop']:.1f}%）| ⏳ 第{card['holding_days']}天/距T+21还有{card['days_left']}天"
            )
            report.append(f"**政策分:** {policy_display}")
            report.append(f"**今日行动:** {card['action']}")
            report.append(f"**动态止盈价:** 📈 {card['stop_loss']:.3f}\n")
    else:
        report.append("- 💤 当前无持仓\n")

    report.append("---\n## 📦 持仓状态\n")
    if holdings_data:
        for h in holdings_data:
            profit_emoji = "📈" if h["profit_pct"] > 0 else "📉"
            report.append(
                f"**{h['symbol']} {h['name']}:** {profit_emoji} 现价{h['price']:.3f} | 盈亏{h['profit_pct']:+.2f}% | ⏳ 持仓{h['days']}天 | 🏷️ {h['wave_type']} | {h['emoji']} {h['phase']}\n"
            )
    else:
        report.append("- 💤 空仓\n")

    report.append("\n## 📊 扫描数据（原始数据）\n")
    report.append(
        "| 代码 | 名称 | 现价 | 涨跌% | 量比 | RSI | MA20 | 资金流向 | 政策分 | 持仓 |"
    )
    report.append(
        "|------|------|------|-------|------|-----|------|----------|--------|------|"
    )
    for etf in etf_list:
        change_emoji = "🔴" if etf["change_pct"] < 0 else "🟢"
        report.append(
            f"| {etf['symbol']} | {etf['name']} | {etf['price']:.3f} | {change_emoji}{etf['change_pct']:+.2f}% | {etf['vol_ratio']:.2f} | {etf['rsi']:.0f} | {etf['ma20']:.3f} | {etf['fund_flow']} | {etf['policy']} | {etf['position']} |"
        )

    report.append("\n## 🌡️ 市场环境\n")
    report.append(f"**🕐 扫描时间:** {market['scan_time']}")
    report.append(
        f"**🌡️ 市场温度:** {market['temperature']} (上涨{market['rising']}/{market['total']})"
    )
    if market["index"].get("ok"):
        index_emoji = "📈" if market["index"]["change_pct"] > 0 else "📉"
        report.append(
            f"**🏛️ 沪深300:** {index_emoji} {market['index']['price']:.2f} ({market['index']['change_pct']:+.2f}%)\n"
        )

    report.append("## 💰 资金状态\n")
    total_asset = total_value + cash_available
    equity_ratio = (total_value / total_asset * 100) if total_asset > 0 else 0
    position_emoji = "🟢" if equity_ratio < 30 else "🟡" if equity_ratio < 50 else "🔴"

    report.append(f"**💵 可用资金:** {cash_available:,.2f}元")
    report.append(f"**📊 持仓市值:** {total_value:,.2f}元")
    report.append(f"**💼 总资产:** {total_asset:,.2f}元")
    report.append(f"**{position_emoji} 权益仓位:** {equity_ratio:.1f}%\n")

    report.append("---\n## 📝 DeepSeek任务\n")
    report.append("请基于四维评分体系（政策30+技术25+情绪20+风险收益25）分析并输出：\n")
    report.append("1. **持仓处理指令**（基于波段管理卡；若政策分<15请确认逻辑止损）")
    report.append("2. **新机会评分与仓位建议**（基于扫描数据，≥75分才列出）")
    report.append("3. **如买入卖出，告知我具体的份额**")
    report.append("4. **执行时间建议**（14:55-15:00）\n")
    report.append(
        f"*📡 数据来源: 新浪财经 + AKShare* \n*🕐 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}* \n*📖 方法论版本: v{SYSTEM_VERSION}（{METHODOLOGY_DESC}）*"
    )

    return "\n".join(report)


# ============================================================
# 主函数
# ============================================================


def main(force_refresh=False):
    print("\n" + "=" * 80)
    print(f"🚀 {SYSTEM_NAME} v{SYSTEM_VERSION}")
    print("⭐ 价值波段 | 逻辑止损(政策分<15) | 时间止损T+21 | 动态止盈机制")
    print("=" * 80)

    try:
        base_scores = load_base_scores()
        holdings_config = load_holdings()
        cash_available = holdings_config.get("cash_available", 0)
        holding_symbols = {
            h["symbol"]
            for h in holdings_config.get("holdings", [])
            if h.get("qty", 0) > 0
        }

        need_refresh, reason = should_refresh_policy()
        if force_refresh:
            need_refresh, reason = True, "用户强制刷新"

        market = scan_market()
        index_change = (
            market["index"].get("change_pct", 0) if market["index"].get("ok") else 0
        )

        if need_refresh:
            print(f"🔄 {reason}")
            etf_pool = refresh_etf_pool(base_scores, index_change)
        else:
            print(f"✅ {reason}")
            etf_pool = load_etf_pool()
            if not etf_pool:
                print("⚠️ etf_pool.json为空，执行全量扫描")
                etf_pool = refresh_etf_pool(base_scores, index_change)

        holdings_data, wave_cards, total_value = scan_holdings_with_wave_management(
            holdings_config, market["realtime"], etf_pool
        )
        etf_list = scan_etf_pool(etf_pool, holding_symbols, market["realtime"])

        report = generate_report_v2(
            market, etf_list, holdings_data, wave_cards, total_value, cash_available
        )

        if os.environ.get("GITHUB_ACTIONS"):
            with open("report.txt", "w", encoding="utf-8") as f:
                f.write(report)
            print("✅ report.txt 已写入")

        print("\n" + "=" * 80)
        print(report)
        print("=" * 80)
        print("\n✅ 扫描完成！")
        print("\n💡 下一步：复制上面的报告，发送给DeepSeek或Gemini进行四维评分分析")

    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
    except Exception as e:
        print(f"\n❌ 扫描失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    import sys

    force_refresh = "--refresh-policy" in sys.argv or "-r" in sys.argv
    main(force_refresh=force_refresh)
