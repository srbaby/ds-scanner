#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

import versioning
import ai_review


class VersioningTests(unittest.TestCase):
    def test_version_manifest_is_v3(self):
        self.assertEqual(versioning.METHODOLOGY_VERSION, "v3.0")
        self.assertEqual(versioning.PROMPT_CONTRACT_VERSION, "v3.0")
        self.assertEqual(versioning.DATA_SCHEMA_VERSION, "v2.0")

    def test_key_documents_match_manifest(self):
        versioning.validate_document_versions()

    def test_v3_ai_output_contract(self):
        text = "\n".join(
            [
                "【操作清单】",
                "| 操作编号 | 类型 | 代码 | 名称 | 当前目标仓位% | 今日目标仓位% | 调整仓位 | 规则代码 | 信号等级 | 中文操作依据 | 关键指标 |",
                "| OP-01 | BUY | sh588800 | 科创100ETF | 0% | 10% | +10% | B_INITIAL_BUY | B | 普通信号首次建仓 | 评分76 |",
            ]
        )
        self.assertIsNone(ai_review.validate_ai_output(text))

    def test_old_ai_output_contract_is_rejected(self):
        text = "【操作清单】\n| 类型 | 代码 | 名称 | 数量 | 说明 |"
        self.assertIn("缺少列", ai_review.validate_ai_output(text))


if __name__ == "__main__":
    unittest.main()
