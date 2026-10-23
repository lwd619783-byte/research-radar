"""Publication gates inspect rendered content and DATA without executing code."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from output_scan import (ContentParser, OutputScanError, assert_output_safe,
                         embedded_data, scan_output)
from render_v3 import DISCLAIMER


def minimal_data():
    return {'meta': {'today': '2026-10-21'}, 'industries': [], 'chokepoints': [], 'companies': []}


def page(content='', data=None):
    data = minimal_data() if data is None else data
    encoded = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    return '<!doctype html><html><body>' + content + '<p id="disclaimer">' + DISCLAIMER + '</p><script>const DATA=' + encoded + ';</script></body></html>'


class OutputScanTests(unittest.TestCase):
    def codes(self, html, data=None, **kwargs):
        return {issue['code'] for issue in scan_output(html, minimal_data() if data is None else data, **kwargs)}

    def test_all_contract_words_are_checked_in_data_and_visible_text(self):
        contract = json.loads((Path(__file__).resolve().parents[1] / 'data/notion_schema.json').read_text('utf-8'))
        for word in contract['banned_words']:
            with self.subTest(word=word, surface='HTML'):
                self.assertIn('banned_words_in_output', self.codes(page('<p>' + word + '</p>')))
            with self.subTest(word=word, surface='DATA'):
                data = minimal_data()
                data['meta']['test'] = {'nested': [word]}
                self.assertIn('banned_words_in_output', self.codes(page(data=data), data))

    def test_split_nodes_nfkc_spaces_and_character_entities_cannot_bypass(self):
        for content in ('<p>买<span>入</span></p>', '<p>买　 入</p>', '<p>&#20080;&#20837;</p>',
                        '<p data-tip="加&#20179;">安全文本</p>'):
            with self.subTest(content=content):
                self.assertIn('banned_words_in_output', self.codes(page(content)))

    def test_all_text_attributes_are_scanned(self):
        for name in ('data-tip', 'title', 'aria-label', 'placeholder', 'alt'):
            with self.subTest(attribute=name):
                self.assertIn('banned_words_in_output', self.codes(page(f'<span {name}="建议买入">说明</span>')))

    def test_notion_ui_word_exemption_never_exempts_banned_words(self):
        permitted = '<div data-src="notion"><span title="录入核对记录">财务录入说明：已核对原文</span></div>'
        self.assertEqual(self.codes(page(permitted)), set())
        self.assertIn('legacy_ui_words_in_output', self.codes(page('<span>行情待核</span>')))
        self.assertIn('banned_words_in_output', self.codes(page('<div data-src="notion">已核实</div>')))

    def test_script_style_and_template_are_not_visible_content(self):
        content = '<script>const ignored="买入 核验";</script><style>.x:before{content:"买入"}</style><template>买入</template>'
        self.assertEqual(self.codes(page(content)), set())

    def test_site_source_checks_only_requested_site_directory(self):
        with tempfile.TemporaryDirectory(prefix='radar-scan-') as directory:
            root = Path(directory)
            site = root / 'site'
            site.mkdir()
            (site / 'app.js').write_text('const label="数据暂缺";', encoding='utf-8')
            docs = root / 'docs'
            docs.mkdir()
            (docs / 'spec.html').write_text('买入 原评分 .mock-note', encoding='utf-8')
            self.assertEqual(self.codes(page(), site_dir=site), set())
            (site / 'app.js').write_text('const label="行情待核";', encoding='utf-8')
            self.assertIn('legacy_ui_words_in_output', self.codes(page(), site_dir=site))

    def test_disclaimer_once_and_mock_note_absent(self):
        self.assertEqual(self.codes(page()), set())
        self.assertIn('disclaimer_count', self.codes(page().replace(DISCLAIMER, '')))
        self.assertIn('disclaimer_count', self.codes(page('<div>' + DISCLAIMER + '</div>')))
        self.assertIn('disclaimer_count', self.codes(page('<div id="disclaimer"></div>')))
        self.assertIn('mock_note_in_output', self.codes(page('<div class="mock-note">说明</div>')))

    def test_links_reject_script_urls_and_require_external_rel(self):
        for href in ('javascript:alert(1)', 'data:text/html,test', '//example.test', 'https://a:b@example.test', 'https://exa mple.test'):
            with self.subTest(href=href):
                self.assertIn('unsafe_link_in_output', self.codes(page(f'<a href="{href}">来源</a>')))
        self.assertIn('unsafe_link_in_output', self.codes(page('<a href="https://example.test" target="_blank">来源</a>')))
        safe = '<a href="#dataNotes">说明</a><a href="https://example.test" target="_blank" rel="noopener noreferrer">来源 ↗</a>'
        self.assertEqual(self.codes(page(safe)), set())

    def test_invalid_or_mismatched_data_cannot_pass(self):
        self.assertIn('invalid_embedded_data', self.codes(page().replace('const DATA=', 'const OTHER=')))
        self.assertIn('embedded_data_mismatch', self.codes(page(), {**minimal_data(), 'extra': 1}))
        self.assertIn('invalid_data_shape', self.codes(page(data={'meta': {}}), {'meta': {}}))
        with self.assertRaises(ValueError):
            embedded_data('<script>const DATA={"number":NaN};</script>')

    def test_secrets_and_raw_notion_people_metadata_never_leave_safe_diagnostics(self):
        # This is a fixture sentinel, not a real credential or process env value.
        sentinel = 'ntn_TEST_DO_NOT_LOG_123456'
        data = minimal_data()
        data['meta']['nested'] = {'created_by': {'id': 'person'}, 'request_id': 'opaque', 'unexpected': sentinel}
        issues = scan_output(page(data=data), data)
        self.assertTrue({'secret_in_output', 'private_metadata_in_output'} <= {item['code'] for item in issues})
        self.assertNotIn(sentinel, json.dumps(issues))
        with self.assertRaises(OutputScanError) as raised:
            assert_output_safe(page(data=data), data)
        self.assertNotIn(sentinel, str(raised.exception))
        self.assertEqual(raised.exception.exit_code, 2)


if __name__ == '__main__':
    unittest.main()
