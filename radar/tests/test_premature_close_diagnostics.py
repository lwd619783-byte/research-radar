"""Keep parsed daily timing available on a failed collect without exporting payloads."""

import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import collection_diagnostic
import production_collect as collector
from notion_fixture_market import fixture_market
from notion_fixtures import FakeTransport, FixtureSet
from research_snapshot import ResearchAbort


SYMBOL = '000660.KS'
DAY = '2026-11-09'
EXPECTED = '2026-11-06'
BLOCKER = 'mixed_or_missing_market_dates_need_label_approval'
STATUS = 'no_common_completed_observation'
CLOCK = dt.datetime.fromisoformat('2026-11-09T06:05:00+00:00')
SESSION_START = int(dt.datetime.fromisoformat('2026-11-09T00:00:00+00:00').timestamp())
SESSION_END = int(dt.datetime.fromisoformat('2026-11-09T06:00:00+00:00').timestamp())
SENTINEL = 'ntn_SYNTHETIC_SECRET_NOT_A_REAL_CREDENTIAL'
ISSUE = {'kind': 'daily', 'status': STATUS, 'symbol': SYMBOL}
TIMING = {'phase': 'closed', 'receivedAt': CLOCK.isoformat(), 'lastBarTimestamp': SESSION_START,
          'finality': {'start': SESSION_START, 'end': SESSION_END}}


class PrematureCloseDiagnosticTests(unittest.TestCase):
    def test_collect_and_export_keep_only_failed_daily_timing(self):
        def market(*args, **kwargs):
            response = fixture_market(*args, **kwargs)
            data = kwargs['snapshot_sink']['data']
            data['meta'].update(blockers=[BLOCKER], issues=[ISSUE])
            company = next(row for row in data['companies'] if row['sym'] == SYMBOL)
            company['marketCalendar'] = {'quoteDate': DAY, 'expectedCompletedDate': EXPECTED}
            kwargs['market_sink']['daily'] = {SYMBOL: {
                'asOf': DAY, 'phase': 'closed', 'receivedAt': CLOCK.isoformat(),
                'finality': {**TIMING['finality'], 'method': 'provider-session-boundary', 'raw': SENTINEL},
                'barTimestamps': {DAY: SESSION_START, EXPECTED: SESSION_START - 259200},
                'bars': SENTINEL, 'response': SENTINEL}}
            return response

        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': collector.REPOSITORY,
               'GITHUB_REF': 'refs/heads/' + collector.LIVE_BRANCH, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_RUN_ID': '123', 'GITHUB_SHA': 'a' * 40}
        with tempfile.TemporaryDirectory() as temporary, patch('socket.socket.connect', side_effect=AssertionError('Offline only')):
            base = Path(temporary)
            transport = FakeTransport(FixtureSet(base / 'fixtures'))
            work = base / 'work'
            with self.assertRaises(ResearchAbort):
                collector.collect(out=base/'bundle/receipt.json', work=work, token=SENTINEL,
                                  transport=transport, market_collect=market, clock=lambda: CLOCK,
                                  env=env, live_dry_run=True, sleep=transport.sleep, pace=transport.pace)
            self.assertFalse((base/'bundle').exists())
            with patch.dict(collection_diagnostic.os.environ, {}, clear=True):
                result = collection_diagnostic.export(work, base/'artifact')
            self.assertFalse(result['publicationAuthorized'])
            diagnostic = (base/'artifact'/'diagnostic.json').read_text('utf-8')
            self.assertNotIn(SENTINEL, diagnostic)
            self.assertEqual(json.loads(diagnostic)['marketIssues'], [
                {**ISSUE, **TIMING, 'sourceDate': DAY, 'expectedCompletedDate': EXPECTED}])

    def test_timing_does_not_escape_for_other_status_kinds_or_symbols(self):
        issues = [{**ISSUE, **TIMING, 'symbol': SENTINEL},
                  {**ISSUE, **TIMING, 'status': 'stale'},
                  {**ISSUE, **TIMING, 'kind': 'valuation', 'status': 'pe_missing'}]
        self.assertEqual(collector.safe_market_issues(issues), [
            {'kind': 'daily', 'status': STATUS}, {**ISSUE, 'status': 'stale'},
            {**ISSUE, 'kind': 'valuation', 'status': 'pe_missing'}])

    def test_timing_sanitizer_rejects_malformed_values_and_keeps_a_valid_boundary(self):
        for timestamp in (SENTINEL, True, -1, 10**100, float('nan'), float('inf')):
            with self.subTest(timestamp=timestamp):
                row = {**ISSUE, 'phase': [SENTINEL], 'receivedAt': SENTINEL, 'lastBarTimestamp': timestamp,
                       'finality': {'start': timestamp, 'end': SESSION_END, 'raw': SENTINEL}}
                self.assertEqual(collector.safe_market_issues([row]), [
                    {**ISSUE, 'finality': {'end': SESSION_END}}])

    def test_receipt_time_is_canonical_and_timezone_aware(self):
        rows = [{**ISSUE, 'receivedAt': '2026-11-09T15:05:00.123456+09:00'},
                {**ISSUE, 'receivedAt': '2026-11-09T06:05:00'},
                {**ISSUE, 'receivedAt': '2026-11-09T06:05:00.00000000+00:00'}]
        self.assertEqual(collector.safe_market_issues(rows), [
            {**ISSUE, 'receivedAt': '2026-11-09T06:05:00.123456+00:00'}, ISSUE, ISSUE])

    def test_repeated_issues_keep_one_timing_block_per_symbol_and_fit_export_bound(self):
        symbols = sorted(collector.DIAGNOSTIC_SYMBOLS)
        dates = dict.fromkeys(('sourceDate', 'observedDate', 'requiredDate', 'expectedCompletedDate'), DAY)
        row = {**ISSUE, **dates, **TIMING}
        rows = [{**row, 'symbol': symbol} for symbol in symbols] + [row] * 100
        diagnostic = collector.safe_collection_diagnostic(BLOCKER, blockers=sorted(collector.DIAGNOSTIC_CODES),
                                                          market_issues=rows, stage='release_gates')
        with tempfile.TemporaryDirectory() as temporary, patch.dict(collection_diagnostic.os.environ, {}, clear=True):
            work, artifact = Path(temporary)/'work', Path(temporary)/'artifact'
            collector.save_json(work/'diagnostic.json', diagnostic)
            collection_diagnostic.export(work, artifact)
            issues = json.loads((artifact/'diagnostic.json').read_text('utf-8'))['marketIssues']
        self.assertEqual(len(issues), 100)
        self.assertEqual([issue['symbol'] for issue in issues if 'finality' in issue], symbols)
