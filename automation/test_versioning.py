#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

import versioning
import ai_review


class VersioningTests(unittest.TestCase):
    def test_version_manifest_is_v3(self):
        self.assertEqual(versioning.METHODOLOGY_VERSION, "v3.1")
        self.assertEqual(versioning.PROMPT_CONTRACT_VERSION, "v3.1")
        self.assertEqual(versioning.DATA_SCHEMA_VERSION, "v3.2")

    def test_key_documents_match_manifest(self):
        versioning.validate_document_versions()

    def test_v3_ai_output_contract(self):
        text = "\n".join(
            [
                "【审计结论】",
                "PASS",
                "【发现】",
                "- 无",
                "【解释】",
                "扫描器决策一致。",
            ]
        )
        self.assertIsNone(ai_review.validate_ai_output(text))

    def test_old_ai_output_contract_is_rejected(self):
        text = "【操作清单】\n| 类型 | 代码 | 名称 | 数量 | 说明 |"
        self.assertIn("审计结论", ai_review.validate_ai_output(text))


if __name__ == "__main__":
    unittest.main()
