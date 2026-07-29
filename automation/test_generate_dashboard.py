import json
import os
import unittest

import generate_dashboard

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DashboardContractTests(unittest.TestCase):
    def test_raw_report_is_a_separate_gist_file(self):
        data = generate_dashboard.build_dashboard(
            "raw report",
            {"operations": []},
            "none",
            {"enabled": False, "model": "none", "ok": True, "text": "", "error": ""},
        )
        self.assertNotIn("report", data)
        self.assertEqual(data["report_file"], "report.txt")
        self.assertTrue(data["report_available"])
        # 从 VERSION.json 读，别写死版本号：写死的话每次升版本都要来改一次测试，
        # 而这个断言本意是"看板声明的 schema 版本要和统一清单一致"
        with open(os.path.join(ROOT, "VERSION.json"), "r", encoding="utf-8") as f:
            expected = json.load(f)["data_schema_version"]
        self.assertEqual(data["data_schema_version"], expected)


if __name__ == "__main__":
    unittest.main()
