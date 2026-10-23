"""Daily counters retain observed changes without confusing price or evidence edits."""
import copy
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import daily_changes as changes
import render_v3


def sample(at='2026-10-21T08:45:00+08:00'):
    return {'meta': {'generatedAt': at, 'today': '2026-10-21', 'coverage': []},
            'industries': [{'name': 'AI网络', 's': [5, 4, 5, 4], 'total': 18, 'judgment': {'label': 'ai'}}],
            'chokepoints': [],
            'companies': [{'id': 'A', 'name': '公司甲', 'sym': 'AAA', 'cur': 'USD', 'period': '2026Q2',
                           'price': 20, 'sc': [19, 20], 'r1d': .02, 'metricAsOf': '2026-10-20',
                           'next': '2026-10-30', 'earnings': {'status': 'unverified'},
                           'provenance': {'daily': {'phase': 'closed', 'src': 'yahoo', 'returnBasis': 'adjclose'},
                                          'financial': {'evidence': 'source', 'report_status': 'final'}}}]}


def publish_projection(data, history):
    summary = changes.summarize(data, history)
    return changes.project(data, {}, summary['today']), summary


class DailyV3Tests(unittest.TestCase):
    def test_first_publication_is_unknown_and_next_unchanged_publication_has_three_zeroes(self):
        first, summary = publish_projection(sample(), [])
        self.assertEqual(summary['mode'], 'unavailable')
        self.assertEqual(summary['today'], {'date': '2026-10-21', 'reports': [], 'confirmed': [], 'scores': []})
        later = sample('2026-10-21T12:15:00+08:00')
        result = changes.summarize(later, [first])
        self.assertEqual(result['mode'], 'previous_update')
        self.assertEqual(result['today'], summary['today'])

    def test_same_day_accumulates_deduplicated_transitions_including_reversions(self):
        old, _ = publish_projection(sample(), [])
        noon = sample('2026-10-21T12:15:00+08:00')
        noon['companies'][0]['period'] = '2026Q3'
        noon['companies'][0]['earnings']['status'] = 'confirmed'
        noon['industries'][0]['s'][1] = 5
        projected, summary = publish_projection(noon, [old])
        expected = {'date': '2026-10-21', 'reports': ['A'], 'confirmed': ['A'], 'scores': ['AI网络']}
        self.assertEqual(summary['today'], expected)
        reverted = sample('2026-10-21T18:15:00+08:00')
        end, summary2 = publish_projection(reverted, changes.history_with(projected, [old]))
        self.assertEqual(summary2['today'], expected)
        later = copy.deepcopy(noon); later['meta']['generatedAt'] = '2026-10-21T20:15:00+08:00'
        self.assertEqual(changes.summarize(later, [end])['today'], expected)
        # Projections own their cumulative values, not a mutable reference.
        summary2['today']['reports'].append('external')
        self.assertEqual(end['changesToday'], expected)

    def test_two_successful_publications_in_same_displayed_minute_keep_baseline(self):
        data = sample()
        previous = changes.project(data, {}, {'date': '2026-10-21', 'reports': ['A'], 'confirmed': [], 'scores': []})
        data['industries'][0]['s'][0] = 4
        result = changes.summarize(data, [previous])
        self.assertEqual(result['mode'], 'previous_update')
        self.assertEqual(result['today']['reports'], ['A'])
        self.assertEqual(result['today']['scores'], ['AI网络'])

    def test_crosses_beijing_midnight_even_when_utc_date_is_unchanged(self):
        before = sample('2026-10-21T15:59:00Z')  # 23:59 Beijing
        prior = changes.project(before, {}, {'date': '2026-10-21', 'reports': ['OLD'], 'confirmed': ['OLD'], 'scores': ['旧行业']})
        after = sample('2026-10-21T16:01:00Z')   # 00:01 Beijing the following day
        after['companies'][0]['period'] = '2026Q3'
        result = changes.summarize(after, [prior])
        self.assertEqual(result['mode'], 'previous_day')
        self.assertEqual(result['today'], {'date': '2026-10-22', 'reports': ['A'], 'confirmed': [], 'scores': []})

    def test_today_compares_latest_release_while_legacy_summary_keeps_prior_day_baseline(self):
        yesterday = changes.project(sample('2026-10-20T18:15:00+08:00'), {})
        morning = sample(); morning['companies'][0]['period'] = '2026Q3'
        prior, _ = publish_projection(morning, [yesterday])
        noon = copy.deepcopy(morning); noon['meta']['generatedAt'] = '2026-10-21T12:15:00+08:00'
        noon['industries'][0]['s'][0] = 4
        result = changes.summarize(noon, [yesterday, prior])
        self.assertEqual(result['baselineAt'], yesterday['generatedAt'])
        self.assertEqual(result['today']['reports'], ['A'])
        self.assertEqual(result['today']['scores'], ['AI网络'])
        self.assertEqual(result['scores'], [{'name': 'AI网络', 'before': [5, 4, 5, 4], 'after': [4, 4, 5, 4]}])

    def test_same_report_evidence_edit_remains_legacy_detail_but_is_not_today_report_change(self):
        old = changes.project(sample(), {})
        data = sample('2026-10-21T12:15:00+08:00')
        data['companies'][0]['provenance']['financial']['source_urls'] = ['https://issuer.example/report']
        data['companies'][0]['next'] = '2026-10-31'
        result = changes.summarize(data, [old])
        self.assertEqual(len(result['reports']), 1)
        self.assertEqual(len(result['calendar']), 1)
        self.assertEqual(result['today']['reports'], [])
        self.assertEqual(result['today']['confirmed'], [])

    def test_no_record_new_identity_and_legacy_missing_scores_do_not_invent_changes(self):
        old = changes.project(sample(), {}); old.pop('industries')
        data = sample('2026-10-21T12:15:00+08:00')
        data['companies'][0]['provenance']['financial'] = None
        new = copy.deepcopy(data['companies'][0]); new.update(id='B', period='2026Q4', earnings={'status': 'confirmed'})
        data['companies'].append(new)
        data['industries'].append({'name': '新行业', 's': [5, 5, 5, 5]})
        result = changes.summarize(data, [old])
        self.assertEqual(result['today'], {'date': '2026-10-21', 'reports': [], 'confirmed': [], 'scores': []})
        self.assertEqual(result['scores'], [])

    def test_history_compares_instants_not_iso_spelling_and_rejects_naive_time(self):
        earlier = changes.project(sample('2026-10-21T08:00:00+08:00'), {})
        later = changes.project(sample('2026-10-21T01:00:00Z'), {})
        self.assertEqual(changes.history_with(later, [earlier]), [later])
        with self.assertRaisesRegex(ValueError, 'without_timezone'):
            changes.summarize(sample('2026-10-21T08:00:00'), [])

    def test_current_judgments_use_v3_labels(self):
        self.assertFalse(changes.review_pending({'judgment': {'label': 'ai'}}, '2026-10-21'))
        self.assertTrue(changes.review_pending({'judgment': {'label': 'stale'}}, '2026-10-21'))


class PulseTodayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / 'radar/site/app.js').read_text('utf-8')
        cls.helper = source[source.index('function todayChangeText()'):source.index('function renderReleaseStatus()')]

    def assert_rendered(self, summary, expected):
        data = sample()
        operations = {'changes': summary}
        script = 'const D=' + json.dumps(data) + '; const OP=' + json.dumps(operations) + ';\n' + self.helper
        script += '\nprocess.stdout.write(todayChangeText());'
        run = subprocess.run(['node', '-e', script], capture_output=True, encoding='utf-8')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout, expected)
        html = render_v3.render_pulse(data, dt.date(2026, 10, 21), operations)
        self.assertIn(expected, re.sub('<[^>]+>', '', html))
        template = '<!--__SSR_PULSE__-->'
        self.assertIn(expected, re.sub('<[^>]+>', '', render_v3.render_into(template, data, operations)))

    def test_canonical_operations_changes_today_matches_static_and_dynamic_page(self):
        self.assert_rendered({'mode': 'previous_update', 'today': {'date': '2026-10-21',
                             'reports': ['A', 'B'], 'confirmed': ['A'], 'scores': []}},
                             '今日变化：财报 2 · 财报日确认 1 · 评分 0')

    def test_initial_release_does_not_render_zero_changes_as_known_history(self):
        self.assert_rendered({'mode': 'unavailable', 'today': {'date': '2026-10-21',
                             'reports': [], 'confirmed': [], 'scores': []}}, '今日变化：首次更新')


if __name__ == '__main__':
    unittest.main()
