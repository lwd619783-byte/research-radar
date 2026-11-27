"""Offline acceptance tests for the public short-term snapshot boundary."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

RADAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR / 'scripts'))
from output_scan import UI_WORDS, normalized, scan_output
from render_v3 import DISCLAIMER
from short_term_merge import contract, load_short_term, normalize_history, sanitize_short_term_text

FIXTURE = RADAR / 'tests/fixtures/short_term_v4/sample_short_term_history.json'


class ShortTermMergeTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(FIXTURE.read_text('utf-8'))

    def test_fixture_and_immutable_release_gate(self):
        short = load_short_term(FIXTURE, as_of=dt.date(2026, 11, 24), environ={})
        self.assertFalse(short['meta']['isStale'])
        self.assertEqual(len(short['days']), 10)
        self.assertEqual(len(short['catalysts']), 9)
        data = {'meta': {}, 'industries': [], 'chokepoints': [], 'companies': [], 'shortTerm': short}
        literal = json.dumps(data, ensure_ascii=False).replace('<', r'\u003c')
        html = f'<p id="disclaimer">{DISCLAIMER}</p><script>const DATA={literal};</script>'
        self.assertEqual(scan_output(html, data, site_dir=RADAR / 'site'), [])

    def test_contract_matches_gate_and_all_words_cleaned_at_any_depth(self):
        words = json.loads((RADAR / 'data/notion_schema.json').read_text('utf-8'))['banned_words']
        self.assertEqual(set(words), set(contract()['ego_sanitization']['banned_word_mask_map']))
        combined = list(words) + list(UI_WORDS)
        dirty = '！'.join('　'.join(word) for word in combined) + '，＠个人网名。'
        self.raw['days'][0]['ego']['posts'][0].update(quote=dirty, author='原始署名')
        self.raw['catalysts'][0]['expectationNote'] = dirty
        result = normalize_history(self.raw)
        for text in (result['days'][0]['ego']['posts'][0]['quote'], result['catalysts'][0]['expectationNote']):
            self.assertFalse(any(word in normalized(text) for word in combined))
            self.assertIn('匿名用户', text)
            self.assertNotIn('个人网名', text)
            self.assertEqual(sanitize_short_term_text(text), text)
        self.assertEqual(result['days'][0]['ego']['posts'][0]['author'], '匿名用户')

    def test_private_fields_and_scan_literals_do_not_escape(self):
        token = 'ntn_' + 'a' * 20
        row = self.raw['days'][0]
        row['headline'] = token + ' .mock-note'
        row['pulse']['request_headers'] = {'Authorization': 'local-only'}
        result = normalize_history(self.raw)['days'][0]
        self.assertNotIn(token, result['headline'])
        self.assertNotIn('.mock-note', result['headline'])
        self.assertNotIn('request_headers', result['pulse'])

    def test_bad_latest_day_keeps_previous_and_sets_stale(self):
        for path, bad in [(('date',), '2026-11-22'),
                          (('ego', 'platforms', 0, 'bull'), 'undefined'),
                          (('breadth', 'up'), ['invalid']),
                          (('matrix', 0, 'items'), {}),
                          (('industries', 'up', 0, 'spark'), [float('nan')]),
                          (('cycle', 'activeStep'), 9),
                          (('yesterdayReconcile', 'items', 0, 'status'), 'unknown'),
                          (('headline',), 'A' * 2049)]:
            with self.subTest(path=path):
                raw = copy.deepcopy(self.raw)
                target = raw['days'][0]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = bad
                result = normalize_history(raw)
                self.assertTrue(result['meta']['isStale'])
                self.assertEqual(result['days'][0]['date'], '2026-11-23')

    def test_oldest_dropped_and_duplicates_do_not_displace_dates(self):
        old = copy.deepcopy(self.raw['days'][-1])
        old['date'] = '2026-11-10'
        self.raw['days'] = [old, *reversed(self.raw['days']), self.raw['days'][0]]
        result = normalize_history(self.raw)
        self.assertEqual(len(result['days']), 10)
        dates = [row['date'] for row in result['days']]
        self.assertEqual(dates, sorted(set(dates), reverse=True))
        self.assertEqual(dates[-1], '2026-11-11')

    def test_as_of_no_future_days_and_no_calendar_from_future_snapshot(self):
        result = normalize_history(self.raw, as_of=dt.date(2026, 11, 20))
        self.assertEqual(result['days'][0]['date'], '2026-11-20')
        self.assertEqual(result['catalysts'], [])

    def test_fixed_clock_before_final_omits_future_snapshot_and_later_calendar(self):
        result = load_short_term(FIXTURE, as_of='2026-11-24T12:29:59Z', environ={})
        self.assertEqual(result['days'][0]['date'], '2026-11-23')
        self.assertEqual(result['catalysts'], [])
        self.assertIsNone(result['generatedAt'])
        self.assertEqual(result, normalize_history(result))
        result = load_short_term(FIXTURE, as_of='2026-11-24T12:30:00Z', environ={})
        self.assertEqual(result['days'][0]['date'], '2026-11-24')

    def test_archive_sensitive_guard_rejects_only_bad_rows(self):
        for fields in ({'apiKey': 'private'}, {'rawBody': 'some text'},
                       {'note': 'https://example.invalid/q?signature=opaque'},
                       {'note': 'Bearer ' + 'A' * 13}):
            with self.subTest(fields=tuple(fields)):
                self.raw['days'][0]['pulse'] = fields
                result = normalize_history(self.raw)
                self.assertTrue(result['meta']['isStale'])
                self.assertEqual(result['days'][0]['date'], '2026-11-23')

    def test_staleness_at_final_cutoff_and_over_weekend(self):
        self.raw['generatedAt'] = '2026-11-20T20:30:00+08:00'
        self.raw['days'] = self.raw['days'][2:]  # Friday
        for stamp, stale in [('2026-11-22T21:00:00+08:00', False),
                             ('2026-11-23T20:29:59+08:00', False),
                             ('2026-11-23T12:30:00+00:00', True)]:
            with self.subTest(clock=stamp):
                result = normalize_history(self.raw, as_of=dt.datetime.fromisoformat(stamp))
                self.assertEqual(result['meta']['isStale'], stale)

    def test_missing_corrupt_unusable_and_oversized_are_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            for payload in (None, b'{', b'\xff', b'{}', b'A' * (8 * 1024 * 1024 + 1)):
                if payload is not None:
                    path.write_bytes(payload)
                with self.assertLogs('short_term_merge', level='WARNING'):
                    self.assertIsNone(load_short_term(path, environ={}))

    def test_invalid_event_does_not_disable_an_entire_valid_day(self):
        self.raw['catalysts'][0]['stars'] = -2
        result = normalize_history(self.raw)
        self.assertTrue(result['meta']['isStale'])
        self.assertEqual(len(result['days']), 10)
        self.assertEqual(len(result['catalysts']), 8)

    def test_manual_override_is_sanitized_again_and_failure_preserves_snapshot(self):
        def overlay(history, **kwargs):
            raw = copy.deepcopy(history)
            raw['days'][0]['headline'] = '@私有账号，买入'
            return raw
        with patch('short_term_notion.apply_overrides', side_effect=overlay):
            result = load_short_term(FIXTURE, environ={})
            self.assertEqual(result['days'][0]['headline'], '匿名用户，介入')
        with patch('short_term_notion.apply_overrides', side_effect=TimeoutError):
            with self.assertLogs('short_term_merge', level='WARNING'):
                result = load_short_term(FIXTURE, environ={})
            self.assertEqual(result['days'][0]['headline'], self.raw['days'][0]['headline'])


if __name__ == '__main__':
    unittest.main()
