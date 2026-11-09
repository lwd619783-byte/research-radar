"""PR5 operator diagnostics use actual normalized reasons without weakening gates."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import live_notion_dry_run as live
import production_collect as collector
import research_view as view


class LiveNotionReasonTests(unittest.TestCase):
    def data(self, rows=(), *, today='2026-10-26', warnings=(), quarantined=()):
        return {'meta': {'weekly': view.weekly_view(rows, [], [], [], today),
                         'notion': {'fallbackTables': [], 'warnings': list(warnings),
                                    'quarantined': list(quarantined)}}}

    def row(self, **props):
        return {'id': 'weekly-row', 'props': {'周次': '2026-W44', '主线行业': ['AI互连'],
            '研判理由': '以已发布报告为依据', '来源': 'https://issuer.test/dated-report',
            '研判日期': '2026-10-23', '有效至': '2026-11-02', **props}}

    def test_absent_current_week_has_specific_instruction_without_first_refresh(self):
        result = live.classify(self.data())
        self.assertFalse(result['ready'])
        self.assertEqual(result['code'], 'weekly_refresh_required')
        self.assertIn('没有可用的本周主线', result['action'])
        self.assertIn('2026-W44', result['action'])
        self.assertNotIn('第一次完整刷新', result['action'])
        self.assertNotIn('第五节', result['action'])

    def test_previous_week_and_expiration_report_both_actual_causes(self):
        result = live.classify(self.data([self.row(**{'周次': '2026-W43', '有效至': '2026-10-25'})]))
        self.assertFalse(result['ready'])
        self.assertIn('不是本周周次', result['action'])
        self.assertIn('已过有效期', result['action'])
        self.assertIn('实质复评', result['action'])
        self.assertIn('不要只延长日期', result['action'])

    def test_current_week_expiration_does_not_claim_wrong_week(self):
        result = live.classify(self.data([self.row(**{'有效至': '2026-10-25'})]))
        self.assertIn('已过有效期', result['action'])
        self.assertNotIn('不是本周周次', result['action'])

    def test_missing_source_dates_and_reason_remain_distinct(self):
        for props, expected in (({'来源': ''}, '缺有效来源链接'),
                                ({'有效至': ''}, '缺研判日期或有效至'),
                                ({'研判理由': ''}, '缺研判理由'),
                                ({'有效至': '2026-11-20'}, '有效期超过 14 天'),
                                ({'研判日期': '2026-10-27'}, '研判日期晚于演练日期')):
            with self.subTest(props=props):
                result = live.classify(self.data([self.row(**props)]))
                self.assertFalse(result['ready'])
                # A future-dated row may be excluded from the display entirely;
                # the display's reasons, rather than guesses from raw rows, rule.
                if props.get('研判日期') != '2026-10-27':
                    self.assertIn(expected, result['action'])
                else:
                    self.assertIn('没有可用的本周主线', result['action'])

    def test_rejected_current_row_uses_current_diagnostics_not_historical_noise(self):
        data = self.data(warnings=[{'table': 'weekly', 'key': '2026-W44', 'code': 'banned_words'},
                                  {'table': 'weekly', 'key': '2026-W43', 'code': 'prediction_words'},
                                  {'table': 'industries', 'key': '2026-W44', 'code': 'url_invalid'}],
                         quarantined=[{'table': 'weekly', 'key': '2026-W44', 'code': 'missing_required'}])
        result = live.classify(data)
        self.assertIn('内容含禁用词', result['action'])
        self.assertIn('缺必填项', result['action'])
        self.assertNotIn('预测性用词', result['action'])
        self.assertNotIn('不是有效 https', result['action'])

    def test_fallback_reports_table_and_distinguishes_quality_from_transport(self):
        data = self.data([self.row()])
        data['meta']['notion']['fallbackTables'] = [
            {'table': 'daily', 'code': 'notion_timeout'},
            {'table': 'weekly', 'code': 'table_quality_low'}]
        result = live.classify(data)
        self.assertFalse(result['ready'])
        self.assertEqual(result['code'], 'live_notion_fallback')
        self.assertIn('每日要点：读取超时', result['action'])
        self.assertIn('每周主线：异常行超过门槛', result['action'])
        self.assertIn('修复原行', result['action'])

    def test_auth_priority_and_ai_ready_behavior_are_unchanged(self):
        data = self.data([self.row()], warnings=[{'table': 'weekly', 'key': '2026-W43', 'code': 'banned_words'}])
        original = copy.deepcopy(data)
        self.assertEqual(live.classify(data), {'ready': True, 'code': 'live_notion_ready', 'action': '无'})
        self.assertEqual(data, original)
        for code, step in [('notion_token_missing', '第 1–4、6 步'),
                           ('notion_unauthorized', '第 6 步'),
                           ('notion_not_found', '第 4 步'),
                           ('notion_forbidden', '第 2 步')]:
            data['meta']['notion']['fallbackTables'] = [{'table': 'weekly', 'code': code}]
            result = live.classify(data)
            self.assertEqual(result['code'], code)
            self.assertIn(step, result['action'])
            self.assertFalse(result['ready'])

    def test_unknown_diagnostic_values_never_enter_operator_text(self):
        sentinel = 'ntn_OFFLINE_FAKE_SECRET_DO_NOT_ECHO'
        data = self.data()
        data['meta']['weekly'].update(week=sentinel, judgment={'reasons': [sentinel]})
        self.assertNotIn(sentinel, json.dumps(live.classify(data)))
        data['meta']['notion']['fallbackTables'] = [{'table': sentinel, 'code': sentinel, 'detail': sentinel}]
        self.assertNotIn(sentinel, json.dumps(live.classify(data)))
        self.assertFalse(live.classify(data)['ready'])

    def test_missing_bundle_exports_specific_safe_failure_without_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / 'work'
            work.mkdir()
            diagnostics = {'code': 'no_last_good', 'notionErrors': [
                {'table': 'weekly', 'code': 'notion_timeout'}]}
            (work / 'diagnostic.json').write_text(json.dumps(diagnostics), encoding='utf-8')
            env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': collector.REPOSITORY,
                   'GITHUB_REF': 'refs/heads/' + collector.LIVE_BRANCH,
                   'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ATTEMPT': '1',
                   'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123'}
            result = live.verify(source=root / 'absent', destination=root / 'release',
                                 artifact=root / 'artifact', work=work, env=env)
            self.assertEqual(result['code'], 'live_collection_failed')
            self.assertIn('每周主线：读取超时', result['action'])
            self.assertFalse(result['ready'])
            self.assertFalse(result['verified'])
            self.assertIs(result['publicationAuthorized'], False)
            self.assertEqual(result['purpose'], 'live-notion-dry-run')
            self.assertFalse((root / 'release').exists())
            saved = json.loads((root / 'artifact/result.json').read_text('utf-8'))
            self.assertIs(saved['publicationAuthorized'], False)
            self.assertEqual(saved['action'], result['action'])
            self.assertIn(result['action'], (root / 'artifact/step-summary.md').read_text('utf-8'))


if __name__ == '__main__':
    unittest.main()
