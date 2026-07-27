import unittest

import generate_dashboard


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
        self.assertEqual(data["data_schema_version"], "v3.2")


if __name__ == "__main__":
    unittest.main()
