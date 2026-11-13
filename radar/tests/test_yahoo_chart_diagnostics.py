"""Failure artifacts retain only bounded Yahoo chart evidence."""

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
DAY = '2026-11-11'
CLOCK = dt.datetime.fromisoformat('2026-11-11T17:56:36.052038+00:00')
RECEIPT = CLOCK.isoformat()
OPEN = 1794355200
SENTINEL = 'ntn_SYNTHETIC_SECRET_NOT_A_REAL_CREDENTIAL'
BLOCKER = 'mixed_or_missing_market_dates_need_label_approval'
ISSUE = {'kind': 'daily', 'status': 'no_common_completed_observation', 'symbol': SYMBOL}
CHART = {
    'lastThree': [
        {'date': '2026-11-09', 'timestamp': OPEN - 172800, 'closeStatus': 'positive', 'close': 599000},
        {'date': '2026-11-10', 'timestamp': OPEN - 86400, 'closeStatus': 'positive', 'close': 593000},
        {'date': DAY, 'timestamp': OPEN, 'closeStatus': 'null', 'close': None},
    ],
    'regularMarketPrice': 607000,
    'regularMarketTime': OPEN + 23413,
    'currentTradingPeriod': {
        name: {'start': OPEN + 86400, 'end': OPEN + 108000, 'gmtoffset': 32400}
        for name in ('pre', 'regular', 'post')},
    'receivedAt': RECEIPT,
}


class YahooChartDiagnosticTests(unittest.TestCase):
    def test_failed_collect_exports_chart_even_when_parser_has_no_daily_record(self):
        def market(*args, **kwargs):
            result = fixture_market(*args, **kwargs)
            data = kwargs['snapshot_sink']['data']
            data['meta'].update(blockers=[BLOCKER], issues=[ISSUE])
            company = next(row for row in data['companies'] if row['sym'] == SYMBOL)
            company['marketCalendar'] = {'expectedCompletedDate': DAY}
            kwargs['market_sink'].update(daily={}, dailyEvidence={SYMBOL: {**CHART, 'raw': SENTINEL}})
            return result

        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': collector.REPOSITORY,
               'GITHUB_REF': 'refs/heads/' + collector.LIVE_BRANCH, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_RUN_ID': '123', 'GITHUB_SHA': 'a' * 40}
        with tempfile.TemporaryDirectory() as temporary, patch('socket.socket.connect', side_effect=AssertionError('Offline only')):
            base = Path(temporary)
            transport = FakeTransport(FixtureSet(base / 'fixtures'))
            work = base / 'work'
            with self.assertRaisesRegex(ResearchAbort, BLOCKER):
                collector.collect(out=base/'bundle/receipt.json', work=work, token=SENTINEL,
                                  transport=transport, market_collect=market, clock=lambda: CLOCK,
                                  env=env, live_dry_run=True, sleep=transport.sleep, pace=transport.pace)
            self.assertFalse((base/'bundle').exists())
            with patch.dict(collection_diagnostic.os.environ, {}, clear=True):
                result = collection_diagnostic.export(work, base/'artifact')
            self.assertFalse(result['publicationAuthorized'])
            diagnostic = (base/'artifact/diagnostic.json').read_text('utf-8')
            self.assertNotIn(SENTINEL, diagnostic)
            self.assertEqual(json.loads(diagnostic)['marketIssues'], [
                {**ISSUE, 'expectedCompletedDate': DAY, 'yahooChart': CHART}])

    def test_chart_whitelist_keeps_distinct_missing_and_null_without_extra_fields(self):
        last = CHART['lastThree'][-1]
        chart = {**CHART, 'receipt': SENTINEL, 'regularMarketPrice': True, 'regularMarketTime': float(OPEN),
                 'lastThree': [CHART['lastThree'][0], {**last, 'response': SENTINEL},
                               {**last, 'closeStatus': 'close_missing'},
                               {'date': SENTINEL, 'timestamp': True, 'closeStatus': 'invalid', 'close': SENTINEL}],
                 'currentTradingPeriod': {'regular': {'start': OPEN, 'end': 10**100, 'gmtoffset': 86400,
                                                     'response': SENTINEL}, 'response': SENTINEL}}
        expected = {**ISSUE, 'yahooChart': {'lastThree': [last, {**last, 'closeStatus': 'close_missing'},
                      {'closeStatus': 'invalid', 'close': None}], 'receivedAt': RECEIPT,
                      'currentTradingPeriod': {'regular': {'start': OPEN}}}}
        sanitized = collector.safe_market_issues([{**ISSUE, 'yahooChart': chart}])
        self.assertEqual(sanitized, [expected])
        self.assertEqual(collector.safe_market_issues(sanitized), sanitized)

    def test_evidence_only_once_on_failed_whitelisted_daily_rows(self):
        item = {**ISSUE, 'yahooChart': CHART, 'phase': 'closed', 'receivedAt': RECEIPT}
        other = [{'symbol': SENTINEL}, {'status': 'stale'}, {'kind': 'valuation', 'status': 'pe_missing'}]
        result = collector.safe_market_issues([{**item, **changes} for changes in other] + [item, item])
        self.assertEqual(result[-2:], [item, ISSUE])
        self.assertTrue(all('yahooChart' not in row for row in result[:3]))

    def test_chart_budget_keeps_the_27_symbol_cohort_and_preserves_base_issues_at_capacity(self):
        symbols = sorted(collector.DIAGNOSTIC_SYMBOLS)
        dates = dict.fromkeys(('sourceDate', 'observedDate', 'requiredDate', 'expectedCompletedDate'), DAY)
        row = {**ISSUE, **dates, 'phase': 'closed', 'receivedAt': RECEIPT, 'lastBarTimestamp': OPEN,
               'finality': {'start': OPEN, 'end': OPEN + 23400}, 'yahooChart': CHART}
        cohort = [{**row, 'symbol': symbol} for symbol in symbols]
        ordinary = collector.safe_collection_diagnostic(BLOCKER, market_issues=cohort[:27])
        self.assertTrue(all('yahooChart' in issue for issue in ordinary['marketIssues']))
        diagnostic = collector.safe_collection_diagnostic(BLOCKER, blockers=sorted(collector.DIAGNOSTIC_CODES),
            market_issues=cohort + [row] * 100, stage='release_gates')
        with tempfile.TemporaryDirectory() as temporary, patch.dict(collection_diagnostic.os.environ, {}, clear=True):
            work, artifact = Path(temporary)/'work', Path(temporary)/'artifact'
            collector.save_json(work/'diagnostic.json', diagnostic)
            collection_diagnostic.export(work, artifact)
            issues = json.loads((artifact/'diagnostic.json').read_text('utf-8'))['marketIssues']
            self.assertLessEqual(sum(path.stat().st_size for path in artifact.iterdir()), collection_diagnostic.MAX_ARTIFACT)
        self.assertEqual(len(issues), 100)
        self.assertEqual([issue['symbol'] for issue in issues if 'finality' in issue], symbols)
        self.assertTrue(0 < sum('yahooChart' in issue for issue in issues) < len(symbols))
