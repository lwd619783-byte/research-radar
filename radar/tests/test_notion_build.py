"""Integration boundaries beyond the supplied Notion mutation matrix."""
import copy
import datetime as dt
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import build
import integrity
import notion_source
import research_snapshot
from test_notion_v3 import CASES, run_fixture

STAMP = '2026-10-21T18:15:00+08:00'


class NoCredentialEnvironment(dict):
    """Fail before any real environment lookup; retain proof of attempted reads."""
    def __init__(self):
        super().__init__()
        self.attempted_reads = []

    def get(self, key, default=None):
        if key == 'NOTION_TOKEN':
            self.attempted_reads.append(key)
            raise AssertionError('Offline paths must not read credentials')
        return super().get(key, default)

    def __getitem__(self, key):
        if key == 'NOTION_TOKEN':
            self.attempted_reads.append(key)
            raise AssertionError('Offline paths must not read credentials')
        return super().__getitem__(key)


def arguments(directory, **changes):
    values = dict(check=False, offline=False, fixed_clock=STAMP,
                  research_snapshot=None, notion_fetch=None,
                  cache=str(directory / 'absent-cache.json'), out=str(directory / 'release'),
                  force=False, audit_json=str(directory / 'report.json'))
    values.update(changes)
    return SimpleNamespace(**values)


class NotionBuildBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = run_fixture()
        if cls.baseline['exit'] != 0:
            raise AssertionError('Baseline fixtures must build before boundary tests')

    def test_check_is_local_and_never_reads_credentials(self):
        environment = NoCredentialEnvironment()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch.object(build.os, 'environ', environment), \
                 patch.object(notion_source, 'UrllibTransport') as network, \
                 patch.object(build, 'load_research', side_effect=AssertionError('No remote research on --check')) as research, \
                 patch.object(build, 'fetch_all', side_effect=AssertionError('No market requests on --check')) as market, \
                 patch('socket.socket', side_effect=AssertionError('Network forbidden')), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = build.notion_main(arguments(directory, check=True), build.research_config())
            self.assertEqual(code, 0)
            self.assertEqual(environment.attempted_reads, [])
            network.assert_not_called()
            research.assert_not_called()
            market.assert_not_called()
            self.assertFalse((directory / 'release').exists())

    def test_offline_uses_last_good_with_zero_notion_requests_and_no_secret_read(self):
        environment = NoCredentialEnvironment()
        calls = []
        original = notion_source.fetch_all

        def capture_fetch(*args, **kwargs):
            result = original(*args, **kwargs)
            calls.append(result)
            return result

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            snapshot_path = directory / 'research-snapshot.json'
            snapshot_path.write_text(research_snapshot.canonical_json(self.baseline['snapshot_object']), encoding='utf-8')
            with patch.object(build.os, 'environ', environment), \
                 patch.object(notion_source, 'UrllibTransport') as network, \
                 patch.object(notion_source, 'fetch_all', side_effect=capture_fetch), \
                 patch('socket.socket', side_effect=AssertionError('Network forbidden')), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = build.notion_main(arguments(directory, offline=True, research_snapshot=str(snapshot_path)),
                                         build.research_config())
            self.assertEqual(code, 2, 'Missing cached quotes must remain non-publishable')
            self.assertEqual(environment.attempted_reads, [])
            network.assert_not_called()
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]['requests'], 0)
            self.assertTrue(calls[0]['stopped_all'])
            self.assertFalse((directory / 'release').exists())

    def test_injected_research_and_quotes_cannot_be_published(self):
        data = self.baseline['DATA']
        self.assertTrue(data['meta']['reviewPreview'])
        self.assertIn('local_review_not_publishable', integrity.release_blockers(data))

    def test_corrupt_snapshot_roots_are_absent_for_bytes_and_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'snapshot.json'
            for body in (b'[]', b'null', b'false', b'42', b'"text"', b'{'):
                with self.subTest(body=body):
                    self.assertIsNone(research_snapshot.load_last_good(body))
                    path.write_bytes(body)
                    self.assertIsNone(research_snapshot.load_last_good(path))

    def test_missing_financial_source_updates_coverage_without_changing_market_coverage(self):
        mutations = next(case['mutations'] for case in CASES['cases'] if case['id'] == 'F01')
        result = run_fixture(mutations, last_good=self.baseline['snapshot_object'])
        self.assertEqual(result['exit'], 0)
        data = result['DATA']
        missing = [c for c in data['companies'] if c['provenance']['financial']
                   and c['provenance']['financial']['evidence'] == 'missing']
        self.assertTrue(missing)
        for company in missing:
            coverage = [r for r in data['meta']['coverage'] if r.get('symbol') == company['sym']
                        and r.get('metric') == 'financial']
            self.assertEqual(len(coverage), 1)
            self.assertEqual(coverage[0]['status'], 'missing')
            self.assertNotEqual(coverage[0]['reason'], 'verified')
        before = [r for r in self.baseline['DATA']['meta']['coverage'] if r.get('metric') != 'financial']
        after = [r for r in data['meta']['coverage'] if r.get('metric') != 'financial']
        self.assertEqual(after, before)

    def test_research_currency_cannot_relabel_existing_quote_values(self):
        original = next(c for c in self.baseline['companies'] if c['id'] == 'ZJXC')
        self.assertEqual(original['cur'], 'CNY')
        self.assertIsNotNone(original['price'])
        result = run_fixture([{'op': 'set', 'table': 'companies', 'row': 'ZJXC',
                               'prop': '币种', 'value': 'USD'}], last_good=self.baseline['snapshot_object'])
        self.assertEqual(result['exit'], 0)
        company = next(c for c in result['companies'] if c['id'] == 'ZJXC')
        if company['price'] is not None:
            self.assertEqual(company['cur'], original['cur'])
            self.assertEqual(company['price'], original['price'])
            self.assertEqual(company['provenance']['valuation']['currency'], 'CNY')
        else:
            self.assertIsNone(company.get('mcapUSD'))

    def test_live_clock_freezes_after_collection_without_refetching_notion(self):
        initial = dt.datetime.fromisoformat(STAMP)
        final = initial + dt.timedelta(minutes=2)
        moments = iter((initial, final))
        original_datetime = dt.datetime

        class CollectionClock(original_datetime):
            @classmethod
            def now(cls, tz=None):
                return next(moments)

        seen = []

        def assembled(research, config_data, market, fresh, fixed_clock, config):
            seen.append((fixed_clock, research['snapshot']['builtAt']))
            return {'meta': {'blockers': []}}, [], []

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch.object(build.os, 'environ', {'NOTION_TOKEN': 'ntn_SYNTHETIC_CLOCK_ONLY'}), \
                 patch.object(build.dt, 'datetime', CollectionClock), \
                 patch.object(notion_source, 'fetch_all', return_value=copy.deepcopy(self.baseline['fetch'])) as notion_fetch, \
                 patch.object(build, 'fetch_all', return_value=({'daily': {}, 'quote': {}, 'fx': {}, 'index': {}, 'ratio': {}}, [])) as market_fetch, \
                 patch.object(build, 'assemble_notion', side_effect=assembled), \
                 patch.object(build, 'write_notion_output') as write, \
                 patch('socket.socket', side_effect=AssertionError('Network forbidden')), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = build.notion_main(arguments(directory, fixed_clock=None), build.research_config())
            self.assertEqual(code, 0)
            self.assertEqual(notion_fetch.call_count, 1)
            self.assertEqual(market_fetch.call_count, 1)
            self.assertEqual(seen, [(final, final.isoformat())])
            write.assert_called_once()
            self.assertEqual(write.call_args.args[1]['builtAt'], final.isoformat())


if __name__ == '__main__':
    unittest.main()
