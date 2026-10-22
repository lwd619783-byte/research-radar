"""Offline normalization/snapshot invariants independent of the case harness."""

import copy
import json
import math
from pathlib import Path
import random
import sys
import unittest


RADAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR / "scripts"))
from notion_normalize import normalize
from research_snapshot import ResearchAbort, canonical_json, load_last_good


FIXTURES = RADAR / "tests" / "fixtures" / "notion_v3"
CLOCK = "2026-10-21T18:15:00+08:00"


def fixture_fetch(contract):
    tables = {}
    for table in contract["tables"]:
        pages = []
        for path in sorted((FIXTURES / "notion").glob("query_" + table + "*.json")):
            pages.extend(json.loads(path.read_text(encoding="utf-8"))["results"])
        tables[table] = {"ok": True, "pages": pages,
                         "schema": json.loads((FIXTURES / "notion" / ("ds_" + table + ".json")).read_text(encoding="utf-8"))}
    return {"tables": tables, "requests": {"total": 13, "GET": 6, "POST": 7, "retries": 0}}


def find_page(fetch, table, key):
    name = {"companies": "代号", "financials": "记录", "daily": "标题", "weekly": "周次"}.get(table, "名称")
    for page in fetch["tables"][table]["pages"]:
        prop = page["properties"][name]
        if "".join(part["plain_text"] for part in prop[prop["type"]]) == key:
            return page
    raise AssertionError(key)


class NotionNormalizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((RADAR / "data" / "notion_schema.json").read_text(encoding="utf-8"))
        cls.original = fixture_fetch(cls.contract)
        cls.baseline = normalize(cls.original, cls.contract, CLOCK)

    def setUp(self):
        self.fetch = copy.deepcopy(self.original)

    def run_normalize(self, **kwargs):
        return normalize(self.fetch, self.contract, kwargs.pop("clock", CLOCK),
                         last_good=kwargs.pop("last_good", self.baseline["snapshot"]), **kwargs)

    def assert_projection(self, actual, expected):
        if isinstance(expected, dict):
            for key, value in expected.items():
                self.assertIn(key, actual)
                self.assert_projection(actual[key], value)
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected))
            for left, right in zip(actual, expected):
                self.assert_projection(left, right)
        elif isinstance(expected, float):
            self.assertTrue(math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12), (actual, expected))
        else:
            self.assertEqual(actual, expected)

    def test_complete_research_projection_matches_immutable_fixture(self):
        expected = json.loads((FIXTURES / "expected" / "research_projection.json").read_text(encoding="utf-8"))
        for table in ("industries", "chokepoints", "companies"):
            actual = copy.deepcopy(self.baseline[table])
            key = (lambda row: row["id"]) if table == "companies" else (lambda row: (row["ind"], row["name"])) if table == "chokepoints" else (lambda row: row["name"])
            actual.sort(key=key)
            if table == "companies":
                for row in actual:
                    row["financial"] = row["provenance"]["financial"]
            self.assert_projection(actual, expected[table])

    def test_snapshot_determinism_does_not_depend_on_page_order(self):
        for entry in self.fetch["tables"].values():
            random.Random(7).shuffle(entry["pages"])
        normalized = self.run_normalize()
        self.assertEqual(canonical_json(normalized["snapshot"]), canonical_json(self.baseline["snapshot"]))
        self.assertEqual(normalized["notion"]["snapshotSHA256"], self.baseline["notion"]["snapshotSHA256"])

    def test_single_row_replacement_remains_distinct_from_table_fallback(self):
        find_page(self.fetch, "industries", "AI核心半导体")["properties"]["景气度"]["number"] = 6
        normalized = self.run_normalize()
        industry = next(row for row in normalized["industries"] if row["name"] == "AI核心半导体")
        self.assertEqual(industry["s"][0], 5)
        self.assertEqual(industry["rowSource"], "last_good")
        self.assertIn("row_quarantined", industry["judgment"]["reasons"])
        self.assertEqual(normalized["notion"]["fallbackTables"], [])
        self.assertEqual(normalized["notion"]["counts"]["industries"]["substituted"], 1)

    def test_quality_threshold_is_strictly_above_twenty_percent(self):
        for name in ("消费", "房地产", "玻璃基板"):
            find_page(self.fetch, "industries", name)["properties"]["景气度"]["number"] = 0
        boundary = self.run_normalize()
        self.assertEqual(boundary["notion"]["fallbackTables"], [])
        find_page(self.fetch, "industries", "网络安全")["properties"]["景气度"]["number"] = 0
        fallback = self.run_normalize()
        self.assertEqual(fallback["notion"]["fallbackTables"][0]["code"], "table_quality_low")
        self.assertTrue(all(row["judgment"]["label"] == "ai" for row in fallback["industries"]))

    def test_disabled_industry_excludes_descendants_but_preserves_other_info(self):
        find_page(self.fetch, "industries", "电力与数据中心")["properties"]["停用"]["checkbox"] = True
        normalized = self.run_normalize()
        self.assertEqual(len(normalized["companies"]), 30)
        self.assertEqual(len(normalized["chokepoints"]), 12)
        self.assertEqual([note["key"] for note in normalized["notion"]["warnings"]],
                         ["CXMT", "DZSK", "HDGF", "SNDL", "SYST", "ZWGX"])
        self.assertTrue(all(note["code"] == "text_long" for note in normalized["notion"]["warnings"]))

    def test_all_table_fallback_revalidates_expiry_using_current_clock(self):
        self.fetch["stopped_all"] = True
        self.fetch["error"] = {"code": "notion_token_missing"}
        normalized = self.run_normalize(clock="2026-11-02T18:15:00+08:00")
        self.assertEqual(normalized["notion"]["source"], "last_good")
        self.assertEqual(len(normalized["notion"]["fallbackTables"]), 6)
        self.assertTrue(all(row["judgment"]["reasons"] == ["expired"] for row in normalized["industries"]))
        self.assertEqual(normalized["snapshot"]["tables"]["industries"]["fetchedAt"], CLOCK)

    def test_failed_fetch_without_snapshot_raises_safe_publication_blocker(self):
        self.fetch["tables"]["weekly"] = {"ok": False, "error": {"code": "notion_not_found"}}
        with self.assertRaises(ResearchAbort) as caught:
            self.run_normalize(last_good=None)
        self.assertEqual(caught.exception.code, "no_last_good")
        self.assertEqual(caught.exception.codes, ["notion_not_found", "no_last_good"])
        self.assertEqual(caught.exception.exit_code, 2)

    def test_removed_company_has_no_orphan_financial_in_snapshot(self):
        company = find_page(self.fetch, "companies", "MU")
        self.fetch["tables"]["companies"]["pages"].remove(company)
        normalized = self.run_normalize()
        self.assertEqual(len(normalized["companies"]), 41)
        self.assertEqual(len(normalized["snapshot"]["tables"]["financials"]["rows"]), 41)
        self.assertEqual(normalized["notion"]["quarantined"], [])

    def test_invalid_or_future_snapshot_version_is_not_accepted(self):
        snapshot = copy.deepcopy(self.baseline["snapshot"])
        snapshot["schemaVersion"] = 2
        self.assertIsNone(load_last_good(snapshot, self.contract))
        self.assertIsNone(load_last_good("{not valid json", self.contract))


if __name__ == "__main__":
    unittest.main()
