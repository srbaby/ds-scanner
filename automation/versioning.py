#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X-Plan 统一版本清单读取与一致性校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION.json"


def load_versions() -> Dict[str, str]:
    data = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    required = {
        "methodology_version",
        "prompt_contract_version",
        "data_schema_version",
    }
    missing = sorted(required - set(data))
    if missing:
        raise RuntimeError(f"VERSION.json 缺少字段: {', '.join(missing)}")
    return {key: str(value) for key, value in data.items()}


VERSIONS = load_versions()
METHODOLOGY_VERSION = VERSIONS["methodology_version"]
PROMPT_CONTRACT_VERSION = VERSIONS["prompt_contract_version"]
DATA_SCHEMA_VERSION = VERSIONS["data_schema_version"]


def validate_document_versions() -> None:
    expected = METHODOLOGY_VERSION
    checks = {
        ROOT / "X-Plan.md": f"# X-Plan {expected}",
        ROOT / "Prompt.md": f"方法论版本：{expected}",
    }
    errors = []
    for path, marker in checks.items():
        text = path.read_text(encoding="utf-8")
        if marker not in text:
            errors.append(f"{path.name} 未声明 {marker}")
    if errors:
        raise RuntimeError("版本不一致: " + "；".join(errors))
