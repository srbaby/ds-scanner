#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared helpers for X-Plan policy research tools."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "policy_research"
RAW_DIR = DATA_DIR / "raw"
EVENT_DIR = DATA_DIR / "events"
DELTA_DIR = DATA_DIR / "deltas"
REPORT_DIR = DATA_DIR / "reports"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
SOURCES_FILE = DATA_DIR / "sources.json"
THEMES_FILE = DATA_DIR / "theme_keywords.json"

for path in (RAW_DIR, EVENT_DIR, DELTA_DIR, REPORT_DIR, SNAPSHOT_DIR):
    path.mkdir(parents=True, exist_ok=True)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def month_key(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime("%Y-%m")


def stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def read_recent_jsonl(folder: Path, days: int = 7) -> List[Dict[str, Any]]:
    cutoff = datetime.now() - timedelta(days=days)
    rows: List[Dict[str, Any]] = []
    for path in sorted(folder.glob("*.jsonl")):
        try:
            file_month = datetime.strptime(path.stem, "%Y-%m").date().replace(day=1)
            cutoff_month = cutoff.date().replace(day=1)
            if file_month < cutoff_month:
                continue
        except ValueError:
            pass
        rows.extend(read_jsonl(path))
    return rows


def compact_text(value: str, limit: int = 500) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value[:limit]


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(str(keyword).lower() in lowered for keyword in keywords if keyword)


def rank_weight(rank: str) -> int:
    return {"S": 4, "A": 3, "B": 2, "C": 1}.get(str(rank).upper(), 0)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if match:
        year, month, day = [int(part) for part in match.groups()]
        return datetime(year, month, day)
    return None


def normalize_url(base_url: str, href: str) -> str:
    from urllib.parse import urljoin, urldefrag

    url, _ = urldefrag(urljoin(base_url, href or ""))
    return url


def allowed_url(url: str, domains: Iterable[str]) -> bool:
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower()
    return any(host == d.lower() or host.endswith("." + d.lower()) for d in domains)


def dedupe_rows(rows: Iterable[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for row in rows:
        value = row.get(key)
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(row)
    return out

