"""Supplementary native Notion sources in judgment rows and the production handoff."""

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RADAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR / "scripts"))
import notion_normalize
import production_collect
from acceptance_bundle import BundleError
from research_view import judgment, urls
from test_notion_normalize import CLOCK, find_page, fixture_fetch


PAGE_ID = "a16d2334-8e75-4df9-b0ac-3366778899fe"
DATABASE_ID = "39f180ca-9746-4681-9245-9285d2e1c82b"
PAGE_URL = "https://app.notion.com/p/a16d23348e754df9b0ac3366778899fe"
DATABASE_URL = "https://app.notion.com/p/39f180ca9746468192459285d2e1c82b"
PUBLIC_A = "https://issuer.example.test/quarter?lang=en&year=2026"
PUBLIC_B = "https://exchange.example.test/disclosures/2026-10-30"


def text_part(value):
    return {"type": "text", "plain_text": value, "text": {"content": value, "link": None}}


def mention(kind="page", target=PAGE_ID, label="Untitled", **optional):
    return {"type": "mention", "plain_text": label,
            "mention": {"type": kind, kind: {"id": target}}, **optional}


def source_property(parts, kind="rich_text"):
    return {"type": kind, kind: parts}


class NotionSourceMentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((RADAR / "data" / "notion_schema.json").read_text(encoding="utf-8"))
        cls.fixture = fixture_fetch(cls.contract)

    def flatten(self, parts, *, table="industries", field="来源", kind="rich_text", spec=None):
        page = {"properties": {field: source_property(parts, kind)}}
        contract = self.contract["tables"][table] if spec is None else spec
        return notion_normalize.simplify_page(page, contract)["props"][field]

    def test_page_and_database_accept_compact_or_standard_ids_without_href(self):
        for kind, target, expected in (("page", PAGE_ID, PAGE_URL), ("database", DATABASE_ID, DATABASE_URL)):
            for ident in (target.upper(), target.replace("-", "").upper()):
                with self.subTest(kind=kind, ident=ident):
                    self.assertEqual(self.flatten([text_part(PUBLIC_A + "\n"), mention(kind, ident)]),
                                     PUBLIC_A + "\n" + expected)

    def test_null_href_is_valid_in_all_three_judgment_tables(self):
        for table in ("industries", "chokepoints", "weekly"):
            with self.subTest(table=table):
                self.assertEqual(self.flatten([mention(href=None), text_part("\n" + PUBLIC_A)], table=table),
                                 PAGE_URL + "\n" + PUBLIC_A)

    def test_matching_https_notion_href_uses_canonical_mention_id(self):
        for href in (PAGE_URL, "https://www.notion.so/Research-" + PAGE_ID.replace("-", ""),
                     "https://team.notion.site/Research-" + PAGE_ID.upper() + "?source=copy_link",
                     "https://app.notion.com:443/p/" + PAGE_ID):
            with self.subTest(href=href):
                self.assertEqual(self.flatten([text_part(PUBLIC_A + "\n"), mention(href=href)]),
                                 PUBLIC_A + "\n" + PAGE_URL)

    def test_retains_visible_source_text_and_order_while_view_keeps_public_sources_first(self):
        parts = [text_part("证据清单\n" + PUBLIC_B + "\n"), mention(),
                 text_part("\n" + PUBLIC_A + "\n"), mention("database", DATABASE_ID),
                 text_part("\n"), mention()]
        result = self.flatten(parts)
        self.assertEqual(result, "\n".join(["证据清单", PUBLIC_B, PAGE_URL, PUBLIC_A, DATABASE_URL, PAGE_URL]))
        self.assertEqual(urls(result), [PUBLIC_B, PUBLIC_A, PAGE_URL, DATABASE_URL])

    def test_accepts_two_public_urls_separated_by_space(self):
        original = PUBLIC_B + " " + PUBLIC_A
        self.assertEqual(self.flatten([text_part(original + "\n"), mention()]),
                         original + "\n" + PAGE_URL)

    def test_an_already_visible_public_url_in_a_mention_label_is_never_removed(self):
        for prefix in ("", PUBLIC_B + "\n"):
            with self.subTest(prefix=prefix):
                source = self.flatten([text_part(prefix), mention(label=PUBLIC_A)])
                public_urls = [url for url in urls(source) if url in (PUBLIC_A, PUBLIC_B)]
                self.assertEqual(public_urls, ([PUBLIC_B] if prefix else []) + [PUBLIC_A])
        for label in (PUBLIC_A, "知识库标题", "untitled", "Untitled附录"):
            with self.subTest(label=label):
                self.assertEqual(self.flatten([text_part(PUBLIC_B + "\n"), mention(label=label)]),
                                 PUBLIC_B + "\n" + label)

    def test_mention_requires_an_existing_visible_public_https_source(self):
        for original in ("", "文字", PAGE_URL, "https://app.notion.com./p/" + PAGE_ID,
                         "https://team.notion.site./" + PAGE_ID, "http://issuer.example.test/report",
                         "https://", "https://[bad", "https://user@issuer.example.test/report",
                         "https://@issuer.example.test/report", "https://issuer.example.test:bad/report"):
            with self.subTest(original=original):
                value = self.flatten([text_part(original + "\n"), mention()])
                self.assertEqual(value, (original + "\nUntitled").strip())

    def test_public_url_in_hidden_rich_text_link_or_other_property_does_not_unlock_mention(self):
        linked_text = text_part("发行人公告")
        linked_text.update(href=PUBLIC_A, text={"content": "发行人公告", "link": {"url": PUBLIC_A}})
        page = {"properties": {"来源": source_property([linked_text, text_part("\n"), mention()]),
                               "研判理由": source_property([text_part(PUBLIC_B)])}}
        props = notion_normalize.simplify_page(page, self.contract["tables"]["industries"])["props"]
        self.assertEqual(props["来源"], "发行人公告\nUntitled")
        mention_title_only = [mention(label=PUBLIC_A), text_part("\n"), mention("database", DATABASE_ID)]
        self.assertEqual(self.flatten(mention_title_only), PUBLIC_A + "\nUntitled")
        split_by_mention = [text_part("https:/"), mention(label="发行人"), text_part("/issuer.example.test/report\n"),
                            mention("database", DATABASE_ID)]
        self.assertEqual(self.flatten(split_by_mention), "https:/发行人/issuer.example.test/report\nUntitled")

    def test_invalid_id_preserves_label_even_with_valid_href(self):
        malformed = (None, 17, {}, "", PAGE_ID + " ", "{" + PAGE_ID + "}", PAGE_ID[1:],
                     PAGE_ID.replace("a", "ａ", 1), PAGE_ID.replace("-", "", 1), "0" * 32)
        for ident in malformed:
            with self.subTest(ident=ident):
                self.assertEqual(self.flatten([text_part(PUBLIC_A + "\n"), mention(target=ident, href=PAGE_URL)]),
                                 PUBLIC_A + "\nUntitled")

    def test_unsafe_mismatched_or_incomplete_href_preserves_original_label(self):
        bad_links = ("", 17, "/p/" + PAGE_ID, "http://app.notion.com/p/" + PAGE_ID,
                     "javascript:alert(1)", "https://issuer.example.test/p/" + PAGE_ID,
                     "https://app.notion.com.example.test/p/" + PAGE_ID,
                     "https://user:pw@app.notion.com/p/" + PAGE_ID,
                     "https://@app.notion.com/p/" + PAGE_ID,
                     "https://app.notion.com:444/p/" + PAGE_ID, "https://app.notion.com:bad/p/" + PAGE_ID,
                     DATABASE_URL, PAGE_URL + "/other", "https://app.notion.com/p/other?id=" + PAGE_ID,
                     "https://app.notion.com/p/#" + PAGE_ID, "https://[bad")
        for href in bad_links:
            with self.subTest(href=href):
                self.assertEqual(self.flatten([text_part(PUBLIC_A + "\n"), mention(href=href)]),
                                 PUBLIC_A + "\nUntitled")

    def test_unsupported_and_malformed_native_mentions_do_not_expose_metadata(self):
        for native in ({"type": "user", "user": {"id": PAGE_ID}},
                       {"type": "date", "date": {"start": "2026-11-02"}},
                       {"type": "template_mention", "template_mention": {"id": PAGE_ID}},
                       {"type": "link_preview", "link_preview": {"url": PAGE_URL}},
                       {"type": "page", "database": {"id": PAGE_ID}},
                       {"type": "database", "database": [PAGE_ID]}, {"type": "page"}, None):
            with self.subTest(native=native):
                part = {"type": "mention", "plain_text": "Untitled", "mention": native, "href": PAGE_URL}
                self.assertEqual(self.flatten([text_part(PUBLIC_A + "\n"), part]), PUBLIC_A + "\nUntitled")

    def test_ordinary_text_links_keep_labels_and_do_not_gain_native_targets(self):
        part = {"type": "text", "plain_text": "知识库标题", "href": PAGE_URL,
                "text": {"content": "知识库标题", "link": {"url": PAGE_URL}},
                "mention": {"type": "page", "page": {"id": PAGE_ID}}}
        self.assertEqual(self.flatten([text_part(PUBLIC_A + "\n"), part]), PUBLIC_A + "\n知识库标题")

    def test_other_table_fields_titles_and_unrelated_contract_mapping_do_not_recover_mentions(self):
        parts = [text_part(PUBLIC_A + "\n"), mention()]
        expected = PUBLIC_A + "\nUntitled"
        for table, field, kind in (("industries", "研判理由", "rich_text"), ("weekly", "周次", "title"),
                                   ("companies", "看点", "rich_text"), ("financials", "其他来源", "rich_text"),
                                   ("daily", "一句话", "rich_text")):
            with self.subTest(table=table, field=field):
                self.assertEqual(self.flatten(parts, table=table, field=field, kind=kind), expected)
        for judgment_table, mapping in ((False, "judgment.sources"), (True, "financial.source_urls")):
            spec = {"judgment": judgment_table,
                    "properties": {"来源": {"type": "rich_text", "level": "field", "data": mapping}}}
            with self.subTest(judgment_table=judgment_table, mapping=mapping):
                self.assertEqual(self.flatten(parts, spec=spec), expected)

    def test_invalid_neighbor_mention_does_not_suppress_valid_one(self):
        parts = [text_part(PUBLIC_A + "\n"), mention(target="not-an-id"),
                 text_part("\n"), mention("database", DATABASE_ID)]
        self.assertEqual(self.flatten(parts), PUBLIC_A + "\nUntitled\n" + DATABASE_URL)

    def test_placeholder_attached_to_text_or_another_mention_stays_literal(self):
        for left, right in (("前文", ""), ("", "后文"), ("(", ")"), ("", "/part")):
            with self.subTest(left=left, right=right):
                prefix = PUBLIC_A + "\n" + left
                self.assertEqual(self.flatten([text_part(prefix), mention(), text_part(right)]),
                                 prefix + "Untitled" + right)
        parts = [text_part(PUBLIC_A + "\n"), mention(), mention("database", DATABASE_ID)]
        self.assertEqual(self.flatten(parts), PUBLIC_A + "\nUntitledUntitled")

    def test_real_sanitizer_still_rejects_sensitive_display_text_in_mention(self):
        sentinel = "OFFLINE-SENTINEL-FOR-THIS-TEST"
        for label, token, error, code in (
                (sentinel, sentinel, production_collect.CollectError, "sensitive_notion_input"),
                ("Bearer " + "X" * 24, "", BundleError, "sensitive_value")):
            with self.subTest(code=code):
                raw = copy.deepcopy(self.fixture)
                raw["request_stats"] = raw.pop("requests")
                page = find_page(raw, "industries", "AI核心半导体")
                page["properties"]["来源"]["rich_text"] = [text_part(PUBLIC_A + "\n"), mention(label=label)]
                with self.assertRaises(error) as caught:
                    production_collect.sanitize_fetch(raw, self.contract, fetched_at=CLOCK, token=token)
                self.assertEqual(str(caught.exception), code)

    def test_mention_only_glass_and_historical_week_retain_missing_source(self):
        raw = copy.deepcopy(self.fixture)
        for table, key in (("industries", "玻璃基板"), ("weekly", "2026-W42")):
            find_page(raw, table, key)["properties"]["来源"]["rich_text"] = [mention()]
        result = notion_normalize.normalize(raw, self.contract, CLOCK)
        glass = next(row for row in result["industries"] if row["name"] == "玻璃基板")
        week = next(row for row in result["weekly_rows"] if row["props"]["周次"] == "2026-W42")
        self.assertEqual(week["props"]["来源"], "Untitled")
        for decision in (glass["judgment"], judgment(week["props"], CLOCK, source_week="2026-W42")):
            self.assertEqual(decision["sources"], [])
            self.assertIn("missing_source", decision["reasons"])
            self.assertEqual(decision["label"], "stale")

    def test_direct_and_sanitized_paths_match_without_mutating_raw_pages_or_fetching_targets(self):
        raw = copy.deepcopy(self.fixture)
        raw["request_stats"] = raw.pop("requests")
        page = find_page(raw, "industries", "AI核心半导体")
        page["properties"]["来源"]["rich_text"] = [mention(), text_part("\n" + PUBLIC_A)]
        before = copy.deepcopy(raw)
        with patch("socket.getaddrinfo", side_effect=AssertionError("normalization must stay offline")), \
             patch("socket.socket.connect", side_effect=AssertionError("normalization must stay offline")):
            handoff = production_collect.sanitize_fetch(raw, self.contract, fetched_at=CLOCK)
            direct = notion_normalize.normalize(raw, self.contract, CLOCK)
            replay = notion_normalize.normalize(handoff, self.contract, CLOCK)
        self.assertEqual(raw, before)
        self.assertEqual(handoff["requests"], before["request_stats"])
        self.assertEqual(direct, replay)
        row = next(r for r in handoff["tables"]["industries"]["rows"] if r["id"] == page["id"])
        self.assertEqual(row["props"]["来源"], PAGE_URL + "\n" + PUBLIC_A)
        industry = next(r for r in direct["industries"] if r["name"] == "AI核心半导体")
        self.assertEqual(industry["judgment"]["sources"], [PUBLIC_A, PAGE_URL])
        self.assertEqual(direct["notion"]["fallbackTables"], [])

    def test_invalid_local_or_private_hosts_cannot_unlock_a_supplementary_source(self):
        for host in (".", "localhost", "radar.localhost.", "127.0.0.1", "[::1]",
                     "192.168.1.8", "[fd00::1]", "issuer..example.test", "-issuer.example.test"):
            with self.subTest(host=host):
                original = "https://" + host + "/report"
                self.assertEqual(self.flatten([text_part(original + "\n"), mention()]),
                                 original + "\nUntitled")

    def test_control_characters_and_backslashes_in_notion_href_keep_the_placeholder(self):
        for character in ("\x00", "\x01", "\x1f", "\x7f", "\t", "\n", "\r", "\\"):
            href = "https://app.notion.com/path" + character + "suffix/" + PAGE_ID
            with self.subTest(character=repr(character)):
                self.assertEqual(self.flatten([text_part(PUBLIC_A + "\n"), mention(href=href)]),
                                 PUBLIC_A + "\nUntitled")


if __name__ == "__main__":
    unittest.main()
