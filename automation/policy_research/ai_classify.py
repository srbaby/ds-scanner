#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""政策事件的板块归类与方向判定（AI）。规则出处：`X-Plan.md` 模块11。

为什么是两趟：模型不直接读取链接正文，所以正文必须由本系统代抓。

    粗筛   关键词判"是不是政策类"，且只保留 etf_pool 里有对应 ETF 的板块
    第一趟 送 id + 标题 + 板块候选 → AI 回"该读哪些"（每板块≥2条，全局≤45条）
           不送 URL：AI 读不了，送 300 条 URL 白费约 8K tokens
    抓正文 本系统抓这些页面，各取 ≤400 字
    第二趟 送正文 → AI 回 板块 / 方向 / 强度 / 是否与前一条重复

AI 只判这四样。评分、等级、操作、仓位一概看不到也不产出——红线 3。
任何一步失败都整体退回关键词分类器，并让调用方把原因显式写进报告与 Bark。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Dict, List, Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

if __package__ in {None, ""}:
    from automation.policy_research import common
else:
    from . import common

POLICY_AI_PROVIDER = os.environ.get("POLICY_AI_PROVIDER", "gemini").strip().lower()

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_TIMEOUT = int(os.environ.get("DEEPSEEK_TIMEOUT", "90"))
DEEPSEEK_RETRIES = int(os.environ.get("DEEPSEEK_RETRIES", "1"))
DEEPSEEK_RETRY_SLEEP_SECONDS = int(os.environ.get("DEEPSEEK_RETRY_SLEEP_SECONDS", "10"))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "90"))
GEMINI_RETRIES = int(os.environ.get("GEMINI_RETRIES", "1"))
GEMINI_RETRY_SLEEP_SECONDS = int(os.environ.get("GEMINI_RETRY_SLEEP_SECONDS", "10"))

# 每个板块至少让 AI 读 2 条，否则冷门板块（今天煤炭/港股科技各只有 3 条候选）
# 按热度排序永远轮不到，AI 覆盖不到它们就等于没接
MIN_PER_SECTOR = int(os.environ.get("POLICY_AI_MIN_PER_SECTOR", "2"))
READ_BUDGET = int(os.environ.get("POLICY_AI_READ_BUDGET", "45"))
EXCERPT_CHARS = 400
FETCH_TIMEOUT = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 X-Plan policy research bot; research-only",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
PROXIES = {"http": None, "https": None}

DIRECTIONS = {"positive", "negative", "neutral"}


def enabled() -> bool:
    if POLICY_AI_PROVIDER == "gemini":
        return bool(GEMINI_API_KEY)
    if POLICY_AI_PROVIDER == "deepseek":
        return bool(DEEPSEEK_API_KEY)
    return False


def active_model() -> str:
    if POLICY_AI_PROVIDER == "gemini":
        return GEMINI_MODEL
    if POLICY_AI_PROVIDER == "deepseek":
        return DEEPSEEK_MODEL
    return ""


def disabled_reason() -> str:
    if POLICY_AI_PROVIDER == "gemini":
        return "未配置 GEMINI_API_KEY"
    if POLICY_AI_PROVIDER == "deepseek":
        return "未配置 DEEPSEEK_API_KEY"
    return f"不支持的 POLICY_AI_PROVIDER: {POLICY_AI_PROVIDER}"


# --------------------------------------------------------------------------
# 粗筛
# --------------------------------------------------------------------------

def etf_sectors() -> List[str]:
    """只认 etf_pool 里真实存在的板块。

    ds_scanner 用 ETF 的 category 取 base 分，etf_base_config 里没有对应 ETF 的
    主题分永远取不到（AI算力/储能/医药/大消费/银行 5 个就是这样），送去让 AI 判
    纯属烧 token——2026-07-29 实测砍掉它们能把送审量从 435 条降到 310 条。
    """
    data = common.load_json(common.ROOT / "data" / "etf_pool.json", {})
    pool = (data or {}).get("etfs") or {}
    return sorted({row.get("category") for row in pool.values() if row.get("category")})


def prefilter(raw_rows: List[Dict], map_themes, config: Dict, sectors: List[str]) -> List[Dict]:
    """关键词粗筛：留下能映射到"有 ETF 的板块"的条目，按 raw_id 去重。"""
    allowed = set(sectors)
    seen = set()
    items = []
    for raw in raw_rows:
        raw_id = raw.get("raw_id")
        if not raw_id or raw_id in seen:
            continue
        title = common.compact_text(raw.get("title", ""), 220)
        if not title:
            continue
        cands = [t for t in map_themes(title, config) if t in allowed]
        if not cands:
            continue
        seen.add(raw_id)
        items.append({
            "id": raw_id,
            "title": title,
            "url": raw.get("url") or "",
            "candidate_sectors": cands,
            "source": raw.get("source") or "",
        })
    return items


# --------------------------------------------------------------------------
# AI 调用（Gemini 默认；DeepSeek 仅作可切换备用）
# --------------------------------------------------------------------------

def _chat_deepseek(system: str, user: str, max_tokens: int = 4096) -> Dict:
    if not DEEPSEEK_API_KEY:
        return {"ok": False, "text": "", "error": "未配置 DEEPSEEK_API_KEY"}
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "stream": False,
        # 分类任务要可复现：同样的输入不该今天判 + 明天判 −
        "temperature": 0,
        # thinking 默认是 enabled，推理会吃掉 max_tokens 且结果落在 reasoning_content，
        # content 反而空——2026-07-29 首次上线就栽在这（"第一趟失败: 返回内容为空"）。
        # 归类不需要思维链，关掉它更快更省也更稳定。
        "thinking": {"type": "disabled"},
        # 官方建议用 JSON 模式约束输出；prompt 里必须出现 "json" 字样并给出样例，
        # 两个 system prompt 都满足
        "response_format": {"type": "json_object"},
    }
    retryable = {429, 500, 502, 503, 504}
    attempts = max(1, DEEPSEEK_RETRIES + 1)
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            r = requests.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                         "Content-Type": "application/json"},
                json=payload, proxies=PROXIES, timeout=DEEPSEEK_TIMEOUT,
            )
        except Exception as exc:
            last_error = f"请求异常: {str(exc)[:200]}"
            if attempt < attempts:
                time.sleep(DEEPSEEK_RETRY_SLEEP_SECONDS)
                continue
            return {"ok": False, "text": "", "error": last_error}
        if r.status_code == 200:
            try:
                data = r.json()
                choices = data.get("choices") or []
                message = choices[0].get("message", {}) if choices else {}
                text = (message.get("content") or "").strip()
                finish = choices[0].get("finish_reason", "?") if choices else "?"
                reasoning_len = len(message.get("reasoning_content") or "")
                usage = data.get("usage") or {}
            except Exception as exc:
                return {"ok": False, "text": "", "error": f"响应解析失败: {str(exc)[:160]}"}
            if not text:
                # 空 content 的原因不止一种（推理吃光配额 / 截断 / 官方已知的偶发空返回），
                # 报错必须带上判据，否则下次还得再猜一轮
                last_error = (
                    f"返回内容为空（finish_reason={finish}，reasoning={reasoning_len}字，"
                    f"completion_tokens={usage.get('completion_tokens', '?')}，"
                    f"上限={max_tokens}）")
                # 官方文档明说 JSON 模式偶发返回空 content，值得再试一次
                if attempt < attempts:
                    time.sleep(DEEPSEEK_RETRY_SLEEP_SECONDS)
                    continue
                return {"ok": False, "text": "", "error": last_error}
            return {"ok": True, "text": text, "error": None}
        last_error = f"HTTP {r.status_code}: {r.text[:200]}"
        if r.status_code in retryable and attempt < attempts:
            time.sleep(DEEPSEEK_RETRY_SLEEP_SECONDS)
            continue
        return {"ok": False, "text": "", "error": last_error}
    return {"ok": False, "text": "", "error": last_error}


def _chat_gemini(system: str, user: str, max_tokens: int = 4096) -> Dict:
    if not GEMINI_API_KEY:
        return {"ok": False, "text": "", "error": "未配置 GEMINI_API_KEY"}
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(GEMINI_MODEL, safe='')}:generateContent"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": max_tokens,
        },
    }
    retryable = {429, 500, 502, 503, 504}
    attempts = max(1, GEMINI_RETRIES + 1)
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            r = requests.post(
                url,
                headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                json=payload,
                proxies=PROXIES,
                timeout=GEMINI_TIMEOUT,
            )
        except Exception as exc:
            last_error = f"请求异常: {str(exc)[:200]}"
            if attempt < attempts:
                time.sleep(GEMINI_RETRY_SLEEP_SECONDS)
                continue
            return {"ok": False, "text": "", "error": last_error}
        if r.status_code == 200:
            try:
                data = r.json()
                candidates = data.get("candidates") or []
                candidate = candidates[0] if candidates else {}
                parts = ((candidate.get("content") or {}).get("parts") or [])
                text = "\n".join(
                    str(part.get("text") or "").strip()
                    for part in parts
                    if isinstance(part, dict) and part.get("text")
                ).strip()
                finish = candidate.get("finishReason", "?")
            except Exception as exc:
                return {"ok": False, "text": "", "error": f"响应解析失败: {str(exc)[:160]}"}
            if not text:
                last_error = f"返回内容为空（finish_reason={finish}，上限={max_tokens}）"
                if attempt < attempts:
                    time.sleep(GEMINI_RETRY_SLEEP_SECONDS)
                    continue
                return {"ok": False, "text": "", "error": last_error}
            return {"ok": True, "text": text, "error": None}
        last_error = f"HTTP {r.status_code}: {r.text[:200]}"
        if r.status_code in retryable and attempt < attempts:
            time.sleep(GEMINI_RETRY_SLEEP_SECONDS)
            continue
        return {"ok": False, "text": "", "error": last_error}
    return {"ok": False, "text": "", "error": last_error}


def _chat(system: str, user: str, max_tokens: int = 4096) -> Dict:
    if POLICY_AI_PROVIDER == "gemini":
        return _chat_gemini(system, user, max_tokens)
    if POLICY_AI_PROVIDER == "deepseek":
        return _chat_deepseek(system, user, max_tokens)
    return {"ok": False, "text": "", "error": disabled_reason()}


def parse_json_object(text: str) -> Optional[Dict]:
    """容忍模型套 ```json 围栏或前后带闲话，取第一个完整 JSON 对象。"""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    while start != -1:
        depth = 0
        for idx in range(start, len(cleaned)):
            if cleaned[idx] == "{":
                depth += 1
            elif cleaned[idx] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(cleaned[start:idx + 1])
                        return parsed if isinstance(parsed, dict) else None
                    except json.JSONDecodeError:
                        break
        start = cleaned.find("{", start + 1)
    return None


PASS1_SYSTEM = (
    "你是政策事件初筛员。只判断哪些标题最可能构成对某个 ETF 板块的实质利好或利空。"
    "纯程序性内容（人事任免、部门决算、例行统计、会议纪要）不必读。"
    "你不得输出买卖建议、评分、等级、仓位或价格。"
    "只输出 JSON：{\"read\": [\"id1\", \"id2\"]}，不要解释，不要 markdown 围栏。"
)

PASS2_SYSTEM = (
    "你是政策事件分类员。对每条事件判断：影响哪个 ETF 板块、是利好还是利空、证据多强、"
    "是否与前面某条是同一件事。candidate_sectors 只是关键词粗筛的提示，不是答案，你可以改判，"
    "也可以判为与所有板块无关。判不出就填 null，不许为了凑数硬安一个板块。"
    "excerpt 为空表示正文抓取失败，此时只凭标题判，并把 strength 压到不超过 2。"
    "你不得输出买卖建议、评分、等级、仓位或价格。"
    "只输出 JSON：{\"results\":[{\"id\":\"\",\"sector\":\"\",\"direction\":\"positive|negative|neutral\","
    "\"strength\":1,\"duplicate_of\":null}]}，results 必须覆盖入参每一个 id，"
    "不要解释，不要 markdown 围栏。"
)


def pass1_pick(items: List[Dict], sectors: List[str]) -> Dict:
    """第一趟：AI 挑出该读正文的条目。"""
    payload = {
        "sectors": sectors,
        "min_per_sector": MIN_PER_SECTOR,
        "budget": READ_BUDGET,
        "items": [{"id": it["id"], "candidate_sectors": it["candidate_sectors"], "title": it["title"]}
                  for it in items],
    }
    # 45 个 id 的 JSON 数组本身很短，但留足余量防截断（官方明确提醒 max_tokens
    # 给小了 JSON 会中途断掉，断掉的 JSON 解析失败等于整趟白跑）
    got = _chat(PASS1_SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=4096)
    if not got["ok"]:
        return {"ok": False, "read": [], "error": got["error"]}
    parsed = parse_json_object(got["text"])
    read = (parsed or {}).get("read")
    if not isinstance(read, list):
        return {"ok": False, "read": [], "error": "第一趟返回不含 read 数组"}
    known = {it["id"] for it in items}
    return {"ok": True, "read": [r for r in read if r in known][:READ_BUDGET], "error": None}


def ensure_sector_floor(items: List[Dict], picked: List[str]) -> List[str]:
    """兜住"每板块至少 2 条"：AI 漏了就按原顺序补，绝不跨板块顶替。

    冷门板块的候选本来就少，靠 AI 自觉容易被热门板块挤掉。这里只补不减。
    """
    chosen = list(dict.fromkeys(picked))
    chosen_set = set(chosen)
    by_sector: Dict[str, List[str]] = {}
    for it in items:
        for sector in it["candidate_sectors"]:
            by_sector.setdefault(sector, []).append(it["id"])
    for sector, ids in sorted(by_sector.items()):
        have = sum(1 for i in ids if i in chosen_set)
        for raw_id in ids:
            if have >= MIN_PER_SECTOR:
                break
            if raw_id not in chosen_set:
                chosen.append(raw_id)
                chosen_set.add(raw_id)
                have += 1
    return chosen


def fetch_excerpt(url: str, limit: int = EXCERPT_CHARS) -> str:
    """抓正文关键片段。抓不到返回空串——调用方据此让 AI 只凭标题判。"""
    if not url:
        return ""
    try:
        r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=FETCH_TIMEOUT)
        if r.status_code != 200:
            return ""
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        return common.compact_text(soup.get_text(" "), limit)
    except Exception:
        return ""


def pass2_classify(items: List[Dict], sectors: List[str]) -> Dict:
    payload = {
        "sectors": sectors,
        "items": [{"id": it["id"], "candidate_sectors": it["candidate_sectors"],
                   "title": it["title"], "excerpt": it.get("excerpt", "")} for it in items],
    }
    got = _chat(PASS2_SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=8192)
    if not got["ok"]:
        return {"ok": False, "results": {}, "error": got["error"]}
    parsed = parse_json_object(got["text"])
    rows = (parsed or {}).get("results")
    if not isinstance(rows, list):
        return {"ok": False, "results": {}, "error": "第二趟返回不含 results 数组"}
    allowed = set(sectors)
    known = {it["id"] for it in items}
    verdicts: Dict[str, Dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_id = row.get("id")
        if raw_id not in known:
            continue
        sector = row.get("sector")
        direction = row.get("direction")
        if sector not in allowed or direction not in DIRECTIONS or direction == "neutral":
            continue  # 判不出/无关/中性都不计分
        try:
            strength = int(row.get("strength") or 0)
        except (TypeError, ValueError):
            continue
        if strength <= 0:
            continue
        verdicts[raw_id] = {
            "sector": sector,
            "direction": direction,
            # 夹紧在 1-5：模型偶尔会给出界的数，别让它溢出到下游打分
            "strength": max(1, min(5, strength)),
            "duplicate_of": row.get("duplicate_of") or None,
        }
    return {"ok": True, "results": verdicts, "error": None}


def classify(raw_rows: List[Dict], map_themes, config: Dict) -> Dict:
    """完整两趟流程。

    返回 {"ok", "reason", "verdicts", "stats"}。ok=False 时 verdicts 为空，
    调用方必须退回关键词分类器并把 reason 显式写进报告——绝不静默降级。
    """
    stats = {"prefiltered": 0, "picked": 0, "fetched": 0, "classified": 0}
    if not enabled():
        return {"ok": False, "reason": disabled_reason(), "verdicts": {}, "stats": stats}

    sectors = etf_sectors()
    items = prefilter(raw_rows, map_themes, config, sectors)
    stats["prefiltered"] = len(items)
    if not items:
        return {"ok": False, "reason": "粗筛后没有可送审条目", "verdicts": {}, "stats": stats}

    picked = pass1_pick(items, sectors)
    if not picked["ok"]:
        return {"ok": False, "reason": f"第一趟失败: {picked['error']}", "verdicts": {}, "stats": stats}
    chosen_ids = ensure_sector_floor(items, picked["read"])
    by_id = {it["id"]: it for it in items}
    chosen = [dict(by_id[i]) for i in chosen_ids if i in by_id]
    stats["picked"] = len(chosen)
    if not chosen:
        return {"ok": False, "reason": "第一趟没选出任何条目", "verdicts": {}, "stats": stats}

    for item in chosen:
        item["excerpt"] = fetch_excerpt(item.get("url", ""))
    stats["fetched"] = sum(1 for it in chosen if it.get("excerpt"))

    judged = pass2_classify(chosen, sectors)
    if not judged["ok"]:
        return {"ok": False, "reason": f"第二趟失败: {judged['error']}", "verdicts": {}, "stats": stats}
    stats["classified"] = len(judged["results"])
    if not judged["results"]:
        return {"ok": False, "reason": "第二趟没有任何可用判定", "verdicts": {}, "stats": stats}
    return {"ok": True, "reason": "", "verdicts": judged["results"], "stats": stats,
            "model": active_model()}
