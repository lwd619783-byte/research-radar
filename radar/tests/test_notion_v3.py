"""Execute the supplied v3 acceptance matrix through the real offline pipeline."""
from __future__ import annotations

from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import copy
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build
from notion_fixtures import (FIXTURES, MISSING, FakeTransport, FixtureSet,
                             canonical_bytes, path_value, project, read_json)

CASES = read_json(FIXTURES / 'cases.json')


def snapshot_bytes(snapshot):
    import research_snapshot
    return research_snapshot.canonical_json(snapshot).encode('utf-8')


def run_fixture(mutations=(), last_good=None):
    """Build real DATA, HTML, and snapshot in a new isolated fixture directory."""
    import research_snapshot
    with tempfile.TemporaryDirectory(prefix='radar-notion-') as temporary:
        directory = Path(temporary)
        fixtures = FixtureSet(directory)
        fixtures.mutate(mutations)
        transport = FakeTransport(fixtures)
        quote_data = read_json(FIXTURES / 'quotes/data-2026-10-21.json')
        for index in quote_data['indices']:
            symbol = index.get('sym') or index.get('symbol')
            if symbol in CASES['index_changes']:
                index['chg'] = CASES['index_changes'][symbol]
        logs = io.StringIO()
        data, snapshot, fetch, exit_code = {}, None, {}, 0
        with redirect_stdout(logs), redirect_stderr(logs), \
             patch('socket.socket', side_effect=AssertionError('Network is forbidden in fixture tests')):
            try:
                data, snapshot, fetch = build.build_notion_data(
                    transport=transport, token=fixtures.env.get('NOTION_TOKEN'),
                    fixed_clock=fixtures.clock, last_good=copy.deepcopy(last_good),
                    quotes_data=quote_data, sleep=transport.sleep, pace=transport.pace,
                    trading_days=copy.deepcopy(CASES['trading_days']))
                build.write_notion_output(data, snapshot, directory / 'release')
            except research_snapshot.ResearchAbort as error:
                exit_code = 2
                print(str(error))
                for value in (getattr(error, 'code', None), getattr(error, 'codes', None),
                              getattr(error, 'diagnostics', None)):
                    if value is not None:
                        print(json.dumps(value, ensure_ascii=False))
        output = directory / 'release'
        files = sorted(path.name for path in output.iterdir()) if output.exists() else []
        snapshot_text = (output / 'research-snapshot.json').read_text('utf-8') if snapshot is not None else ''
        html = (output / 'index.html').read_bytes() if (output / 'index.html').exists() else b''
        return {**data, 'DATA': data, 'snapshot_object': snapshot, 'fetch': fetch,
                'snapshot': snapshot_text,
                'data': (output / 'DATA.json').read_text('utf-8') if (output / 'DATA.json').exists() else '',
                'html': html, 'exit': exit_code, 'logs': logs.getvalue(),
                'transport': {'requests': transport.requests, 'sleeps': transport.sleeps, 'calls': transport.calls},
                'files': {'written': files}}


def diagnostic_codes(result):
    if result['exit']:
        registered = {code for codes in CASES['codes'].values() for code in codes}
        return {code for code in registered if re.search(r'\b' + re.escape(code) + r'\b', result['logs'])}
    diagnostics = result['meta']['notion']
    return {item['code'] for group in ('warnings', 'quarantined', 'fallbackTables')
            for item in diagnostics[group]}


def outcome(result):
    """Infer observable behavior without using an expected result or case ID."""
    if result['exit']:
        return 'abort'
    notion = result['meta']['notion']
    if len(notion['fallbackTables']) == 6:
        return 'all_last_good'
    if notion['fallbackTables']:
        return 'table_last_good'
    if notion['quarantined']:
        return 'quarantine_row'
    if any(item['code'] != 'text_long' for item in notion['warnings']):
        return 'warning'
    if any(row['judgment']['label'] == 'stale' for table in ('industries', 'chokepoints') for row in result[table]):
        return 'warning'
    if any(counts.get('excluded', 0) for counts in notion['counts'].values()):
        return 'exclude'
    return 'ok'


def adapt_toml(data, notion_fixtures):
    """Only the eight intentional differences documented in fixture README."""
    data = copy.deepcopy(data)
    source_rows = {notion_fixtures.plain(row['properties']['名称']): row
                   for row in notion_fixtures.rows('industries')}
    for row in data['industries']:
        raw = source_rows[row['name']]['properties']['知识库']
        row['kb'] = raw['url']
        row.pop('review', None)
    for row in data['chokepoints']:
        row.pop('review', None)
    weekly = data['meta']['weekly']
    weekly['sourceWeek'] = weekly['week']
    weekly['week'] = '2026-W43'
    weekly.pop('review', None)
    weekly.pop('thermoAction', None)
    for row in data['companies']:
        row.pop('flashStatus', None)
        row['earnings'].pop('published_at', None)
        row['earnings'].pop('verified_at', None)
        financial = row['provenance']['financial']
        if financial is not None:
            financial['entered_at'] = financial.pop('verified_at')
            status = financial.pop('status')
            financial['evidence'] = {'verified': 'source', 'verified_partial': 'partial'}.get(status, 'missing')
    return data


class NotionV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = run_fixture()
        if cls.baseline['exit']:
            raise AssertionError('Unmodified fixtures must build: ' + cls.baseline['logs'])
        cls.started = time.perf_counter()
        cls.results = Counter()
        cls.case_failures = 0

    @classmethod
    def tearDownClass(cls):
        print('NOTION_V3_CASE_SUMMARY ' + json.dumps({
            'cases': sum(cls.results.values()), 'outcomes': dict(sorted(cls.results.items())),
            'failed_cases': cls.case_failures,
            'seconds': round(time.perf_counter() - cls.started, 3)}, ensure_ascii=False))

    def assert_tree(self, actual, expected, path='root'):
        if isinstance(expected, dict):
            self.assertIsInstance(actual, dict, path)
            self.assertEqual(set(actual), set(expected), path)
            for key in expected:
                self.assert_tree(actual[key], expected[key], path + '.' + key)
        elif isinstance(expected, list):
            self.assertIsInstance(actual, list, path)
            self.assertEqual(len(actual), len(expected), path)
            for position, (left, right) in enumerate(zip(actual, expected)):
                self.assert_tree(left, right, f'{path}[{position}]')
        elif isinstance(expected, (float, int)) and not isinstance(expected, bool):
            self.assertIsInstance(actual, (float, int), path)
            self.assertTrue(math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12), f'{path}: {actual!r} != {expected!r}')
        else:
            self.assertEqual(actual, expected, path)

    def test_notion_research_parity(self):
        self.assert_tree(project(self.baseline['DATA']), read_json(FIXTURES / 'expected/research_projection.json'))

    def test_toml_parity_only_eight_documented_differences(self):
        fixed_clock = dt.datetime.fromisoformat(CASES['as_of'])
        source, report = build.load_and_validate(build.RADAR, build.REPO, fixed_clock.date())
        self.assertEqual(report.errors, [])
        market = {key: {} for key in ('daily', 'quote', 'index', 'fx', 'ratio')}
        data, _, _ = build.assemble(source, market, market, fixed_clock)
        with tempfile.TemporaryDirectory(prefix='radar-toml-parity-') as directory:
            adapted = adapt_toml(data, FixtureSet(directory))
        self.assert_tree(project(adapted), project(self.baseline['DATA']))

    def test_v3_view(self):
        expected = read_json(FIXTURES / 'expected/v3_view.json')
        data = self.baseline['DATA']
        for table in ('industries', 'chokepoints'):
            actual = {}
            for row in data[table]:
                judgment = row['judgment']
                keys = ('label', 'reasons', 'date', 'validUntil', 'sources')
                value = {key: judgment[key] for key in keys}
                if table == 'industries':
                    value.update(total=row['total'], anchors=judgment['anchors'], conflicts=judgment['conflicts'])
                actual[row['name']] = value
            self.assert_tree(actual, expected[table], table)
        companies = {row['id']: {'evidence': row['provenance']['financial']['evidence'],
                                 'flashDate': row['flashDate'], 'flashFresh': row['flashFresh'],
                                 'earnings': row['earnings']['status'] if row['next'] else 'tbd'}
                     for row in data['companies']}
        self.assert_tree(companies, expected['companies'], 'companies')
        weekly = data['meta']['weekly']
        weekly_view = {key: weekly[key] for key in ('mode', 'sourceWeek', 'focus', 'lead', 'calHint')}
        weekly_view.update({key: weekly['judgment'][key] for key in ('reasons', 'date', 'validUntil')})
        self.assert_tree(weekly_view, expected['weekly'], 'weekly')
        self.assertEqual(data['meta']['today'], expected['today'])
        self.assertEqual(weekly['week'], expected['iso_week'])
        daily = {market: {key: row[key] for key in ('date', 'source', 'line', 'reviewUrl', 'industries')}
                 for market, row in data['meta']['daily'].items()}
        self.assert_tree(daily, expected['daily'], 'daily')
        self.assert_tree(data['meta']['kpis'], expected['kpis'], 'kpis')
        notion = data['meta']['notion']
        warnings = [{key: row[key] for key in ('code', 'table', 'key', 'field')} for row in notion['warnings']]
        self.assert_tree(warnings, expected['warnings'], 'warnings')
        self.assert_tree(notion['quarantined'], expected['quarantined'], 'quarantined')
        self.assert_tree(notion['fallbackTables'], expected['fallbackTables'], 'fallbackTables')
        calls = self.baseline['transport']['calls']
        self.assertEqual(len(calls), expected['requests']['total'])
        self.assertEqual(Counter(call['method'] for call in calls),
                         {method: expected['requests'][method] for method in ('GET', 'POST')})
        self.assertEqual(list(dict.fromkeys(call['table'] for call in calls)), expected['requests']['order'])
        self.assertEqual(hashlib.sha256(self.baseline['snapshot'].encode('utf-8')).hexdigest(), notion['snapshotSHA256'])

    def test_auto_templates(self):
        result = run_fixture([
            {'op': 'remove_row', 'table': 'daily', 'row': '2026-10-21 A股'},
            {'op': 'remove_row', 'table': 'daily', 'row': '2026-10-20 美股'},
            {'op': 'set', 'table': 'weekly', 'row': '2026-W42', 'prop': '研判日期', 'value': '2026-10-01'},
            {'op': 'set', 'table': 'weekly', 'row': '2026-W42', 'prop': '有效至', 'value': '2026-10-08'},
        ], last_good=self.baseline['snapshot_object'])
        expected = read_json(FIXTURES / 'expected/v3_view.json')['autoTemplates']
        self.assert_tree({market: row['line'] for market, row in result['meta']['daily'].items()}, expected['daily'])
        self.assert_tree({key: result['meta']['weekly'][key] for key in ('lead', 'calHint')}, expected['weekly'])

    def test_daily_chips_follow_configuration_values_and_completed_dates(self):
        from research_view import daily_view
        config = build.research_config()['daily']
        indices = self.baseline['DATA']['indices']
        by_symbol = {row['symbol']: row for row in indices}
        for market, daily in self.baseline['meta']['daily'].items():
            self.assertEqual(daily['date'], CASES['trading_days'][market])
            self.assertEqual([row['symbol'] for row in daily['chips']], CASES['daily_chips'][market])
            for chip in daily['chips']:
                self.assertEqual(chip['label'], config['short'][chip['symbol']])
                self.assertEqual(chip['chg'], CASES['index_changes'][chip['symbol']])
                self.assertEqual(by_symbol[chip['symbol']]['asOf'], daily['date'])
        old_indices = copy.deepcopy(indices)
        next(row for row in old_indices if row['symbol'] == 'HSTECH.HK')['asOf'] = '2026-10-20'
        daily = daily_view([], old_indices, CASES['trading_days'], [], config)
        self.assertEqual([chip['symbol'] for chip in daily['A股']['chips']], ['000001.SS', '399006.SZ'])

    def test_deterministic_data_html_and_snapshot(self):
        repeated = run_fixture()
        shuffled = run_fixture([{'op': 'shuffle', 'seed': 7}])
        for variant in (repeated, shuffled):
            for name in ('data', 'html', 'snapshot'):
                with self.subTest(variant='shuffled' if variant is shuffled else 'same', file=name):
                    self.assertEqual(variant[name], self.baseline[name])

    def test_every_code_has_chinese_copy(self):
        from research_view import CODE_TEXT
        codes = {code for values in CASES['codes'].values() for code in values}
        for code in sorted(codes):
            with self.subTest(code=code):
                self.assertIn(code, CODE_TEXT)
                self.assertIsInstance(CODE_TEXT[code], str)
                self.assertRegex(CODE_TEXT[code], r'[\u4e00-\u9fff]')

    def test_atomic_writer_preserves_previous_release_if_render_fails(self):
        with tempfile.TemporaryDirectory(prefix='radar-atomic-write-') as directory:
            output = Path(directory) / 'release'
            build.write_notion_output(self.baseline['DATA'], self.baseline['snapshot_object'], output)
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            with patch.object(build, 'render', side_effect=OSError('Injected render failure')):
                with self.assertRaisesRegex(OSError, 'Injected render failure'):
                    build.write_notion_output(self.baseline['DATA'], self.baseline['snapshot_object'], output)
            self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)

    def test_cli_abort_preserves_existing_release_without_any_file_write(self):
        from notion_source import fetch_all
        with tempfile.TemporaryDirectory(prefix='radar-abort-') as directory:
            directory = Path(directory)
            fixtures = FixtureSet(directory)
            fixtures.mutate([{'op': 'http', 'match': {'kind': 'any'},
                              'responses': [{'status': 401, 'body': {'code': 'unauthorized'}}],
                              'then': 'repeat_last'}])
            transport = FakeTransport(fixtures)
            fetched = fetch_all(fixtures.contract, build.research_config()['notion'],
                                token=fixtures.env['NOTION_TOKEN'], transport=transport,
                                sleep=transport.sleep, pace=transport.pace, fixed_clock=fixtures.clock)
            fetch_path = directory / 'failed-fetch.json'
            fetch_path.write_bytes(canonical_bytes(fetched))
            output = directory / 'release'
            output.mkdir()
            (output / 'index.html').write_bytes(b'previous successful release')
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            arguments = SimpleNamespace(fixed_clock=fixtures.clock, research_snapshot=None,
                                        notion_fetch=str(fetch_path), check=False, out=str(output),
                                        offline=True, cache=str(directory / 'absent-cache.json'))
            with redirect_stdout(io.StringIO()), patch('socket.socket', side_effect=AssertionError('No network')):
                exit_code = build.notion_main(arguments, build.research_config())
            self.assertEqual(exit_code, 2)
            self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)

    def check_case(self, case):
        baseline = None if case.get('given', {}).get('baseline') == 'none' else self.baseline['snapshot_object']
        result = run_fixture(case['mutations'], last_good=baseline)
        expected = case['expect']
        self.results[outcome(result)] += 1
        self.assertEqual(result['exit'], expected['exit'], result['logs'])
        self.assertEqual(outcome(result), expected['outcome'], result.get('meta', {}).get('notion'))
        actual_codes = diagnostic_codes(result)
        required_codes = set(expected['codes'])
        self.assertFalse(required_codes - actual_codes, f'Missing codes: {required_codes - actual_codes}')
        if expected.get('other_codes') != 'ignore':
            self.assertFalse(actual_codes - required_codes - {'text_long'}, f'Unexpected codes: {actual_codes - required_codes}')
        for assertion in expected.get('assert', []):
            path = assertion['path']
            actual = path_value(result, path)
            with self.subTest(path=path):
                for operation, value in assertion.items():
                    if operation == 'path':
                        continue
                    if operation == 'absent':
                        self.assertTrue(actual is MISSING or actual == [], f'{path} exists: {actual!r}')
                    else:
                        self.assertIsNot(actual, MISSING, path)
                        if operation == 'eq':
                            self.assert_tree(actual, value, path)
                        elif operation == 'ne':
                            self.assertNotEqual(actual, value, path)
                        elif operation == 'contains':
                            self.assertIn(value, actual, path)
                        elif operation == 'not_contains':
                            self.assertNotIn(value, actual, path)
                        elif operation == 'len':
                            self.assertEqual(len(actual), value, path)
                        elif operation == 'approx':
                            self.assertTrue(math.isclose(actual, value, rel_tol=1e-9, abs_tol=1e-12), path)
                        elif operation == 'eq_baseline':
                            self.assertTrue(value, path)
                            self.assertEqual(actual, path_value(self.baseline, path), path)
                        else:
                            self.fail(f'Unknown assertion operation {operation}')


def _case_test(case):
    def test(self):
        result = self._outcome.result
        before = len(result.failures) + len(result.errors)
        try:
            self.check_case(case)
        except Exception:
            type(self).case_failures += 1
            raise
        if len(result.failures) + len(result.errors) != before:
            type(self).case_failures += 1
    test.__doc__ = case['title']
    return test


for _case in CASES['cases']:
    setattr(NotionV3Tests, 'test_case_' + _case['id'], _case_test(_case))


class FixtureHarnessTests(unittest.TestCase):
    def test_path_filters_projection_and_missing(self):
        data = {'rows': [{'id': 'A', 'n': 1}, {'id': 'B', 'n': 2}], 'snapshot': '{}\n'}
        self.assertEqual(path_value(data, 'rows[id=B].n'), 2)
        self.assertEqual(path_value(data, 'rows[*].n'), [1, 2])
        self.assertEqual(path_value(data, 'rows[-1].n'), 2)
        self.assertEqual(path_value(data, 'rows[id=C]'), [])
        self.assertIs(path_value(data, 'rows[4].n'), MISSING)
        self.assertIs(path_value(data, 'absent.field'), MISSING)

    def test_all_declared_mutations_are_executable(self):
        for case in CASES['cases']:
            with self.subTest(case=case['id']), tempfile.TemporaryDirectory(prefix='radar-mutations-') as directory:
                fixtures = FixtureSet(directory)
                fixtures.mutate(case['mutations'])
                self.assertTrue((Path(directory) / 'notion/index.json').is_file())

    def test_transport_is_strict_and_does_not_access_network(self):
        with tempfile.TemporaryDirectory(prefix='radar-transport-') as directory:
            fixtures = FixtureSet(directory)
            transport = FakeTransport(fixtures)
            with self.assertRaisesRegex(AssertionError, 'Unexpected offline request'):
                transport.request('GET', '/not-a-fixture')
            query = next(route for route in fixtures.index['routes'] if route['method'] == 'POST')
            with self.assertRaisesRegex(AssertionError, 'Unexpected query fields'):
                transport.request('POST', query['path'], {'page_size': 100, 'sorts': []})


if __name__ == '__main__':
    unittest.main()
