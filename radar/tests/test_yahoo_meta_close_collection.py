"""Offline reproductions of the Asian and European missing-close batches."""
import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import acceptance_bundle as bundle
import acceptance_probe as probe
import build
import market_calendar
import quotes
import yahoo_meta_close as meta_close
from test_integrity import dataset
from test_pr5_calendar_release import synthetic_market


ASIA_CLOCK = dt.datetime.fromisoformat('2026-11-10T04:48:00+08:00')
EUROPE_CLOCK = dt.datetime.fromisoformat('2026-11-10T15:48:00+08:00')
EXPECTED = '2026-11-09'
PREVIOUS = '2026-11-06'
NEXT = '2026-11-10'


def chart(company, *, close=None, row=True, market_time=None, next_close=None):
    symbol = company['sym']
    spec = market_calendar.calendar_data()['exchanges'][market_calendar.exchange_for(symbol)]
    zone = ZoneInfo(spec['timezone'])

    def stamp(day, local):
        return int(dt.datetime.fromisoformat(day + 'T' + local).replace(tzinfo=zone).timestamp())

    session = {'start': stamp(NEXT, spec['open']), 'end': stamp(NEXT, spec['close']),
               'gmtoffset': int(dt.datetime.fromtimestamp(stamp(NEXT, spec['open']), zone).utcoffset().total_seconds())}
    dates = [PREVIOUS, EXPECTED] if row else [PREVIOUS]
    closes = [90, close] if row else [90]
    if next_close is not None:
        dates.append(NEXT)
        closes.append(next_close)
    return {'chart': {'result': [{'meta': {'symbol': symbol, 'currency': company['cur'],
                'exchangeTimezoneName': spec['timezone'], 'currentTradingPeriod': {'regular': session},
                'regularMarketPrice': 101.25, 'regularMarketTime': stamp(EXPECTED, market_time or spec['close'])},
            'timestamp': [stamp(day, spec['open']) for day in dates],
            'indicators': {'quote': [{'close': closes}], 'adjclose': [{'adjclose': closes}]}}]}}


class YahooMetaCloseCollectionTests(unittest.TestCase):
    def setUp(self):
        self.data, _ = dataset()
        network = patch('socket.socket', side_effect=AssertionError('Offline only'))
        network.start()
        self.addCleanup(network.stop)

    def run_rounds(self, companies, documents, clock, *, seconds=300, limit=240, retry_documents=None,
                   initial_date=PREVIOUS):
        calls, rows, evidence, daily = [], [], {}, {}
        receipt = (clock - dt.timedelta(seconds=1)).isoformat()
        elapsed = 0

        def advance(delay):
            nonlocal elapsed
            elapsed += delay

        def yahoo(h, path):
            symbol = path.split('/')[-1].split('?')[0]
            self.assertEqual(path, f'/v8/finance/chart/{symbol}?range=5y&interval=1d&includeAdjustedClose=true')
            h.budget.take('yahoo-chart', deadline=h.deadline)
            if not h.retry_429:
                calls.append((symbol, elapsed))
            response = (retry_documents or {}).get(symbol, documents[symbol]) if not h.retry_429 else documents[symbol]
            h.documents.append(response)
            h.events.append({'httpStatus': 200, 'receivedAt': receipt})
            return response

        with patch.object(probe.time, 'monotonic', side_effect=lambda: elapsed), \
             patch.object(probe.time, 'sleep', side_effect=advance), \
             patch.object(probe.ProbeHttp, 'yahoo', yahoo), \
             patch.object(quotes, 'stamp', side_effect=lambda **record: {
                 **record, 'schemaVersion': 2, 'receivedAt': receipt}):
            initial = probe.Budget()
            for company in companies:
                symbol = company['sym']
                daily[symbol] = probe.company_yahoo_daily(
                    probe.ProbeHttp(initial, 'yahoo'), symbol, initial, rows, evidence, clock)
                self.assertEqual(daily[symbol]['asOf'], initial_date)
            budget = probe.Budget(limit=limit, seconds=seconds)
            probe.retry_missing_daily(companies, daily, evidence, rows, budget, clock)
        return daily, evidence, calls, elapsed

    def assemble(self, clock, daily):
        market = synthetic_market(self.data, clock)
        market['daily'].update(daily)
        result, _, _ = build.assemble(self.data, market, market, clock, calendar_policy=True)
        bundle.validate_yahoo_meta_closes(result, clock)
        return result, {company['sym']: company for company in result['companies']}

    def test_asian_batch_retries_in_two_shared_rounds_and_keeps_real_gates(self):
        companies = [c for c in self.data['companies'] if c['mkt'] in ('A股', '港股', '韩股', '日股', '台股')]
        self.assertEqual(len(companies), 27)
        documents = {c['sym']: chart(c, market_time='16:08' if c['mkt'] == '港股' else None) for c in companies}
        daily, evidence, calls, elapsed = self.run_rounds(companies, documents, ASIA_CLOCK)
        self.assertEqual(calls, [(c['sym'], delay) for delay in (60, 120) for c in companies])
        self.assertEqual(elapsed, 120)
        self.assertTrue(all(value['lastThree'][-1]['closeStatus'] == 'null' for value in evidence.values()))
        result, rows = self.assemble(ASIA_CLOCK, daily)
        for company in companies:
            row = rows[company['sym']]
            if company['mkt'] in ('港股', '台股'):
                self.assertIsNone(row['ld'])
                self.assertNotIn('yahooMetaClose', row['provenance']['daily'])
            else:
                self.assertEqual(row['ld'], EXPECTED)
                self.assertEqual(row['price'], 101.25)
                self.assertEqual(row['priceSource'], meta_close.SOURCE)
                self.assertEqual(row['provenance']['daily']['yahooMetaClose']['date'], EXPECTED)
                self.assertIsNone(row['r1d'])
                self.assertIsNone(row['hi52'])
        self.assertIn('mixed_or_missing_market_dates_need_label_approval', build.release_blockers(result))

    def test_european_batch_accepts_null_and_missing_rows_with_proven_close(self):
        companies = [c for c in self.data['companies'] if c['sym'] in ('ENR.DE', 'SU.PA')]
        documents = {c['sym']: chart(c, row=c['sym'] == 'ENR.DE') for c in companies}
        daily, evidence, calls, _ = self.run_rounds(companies, documents, EUROPE_CLOCK)
        self.assertEqual(len(calls), 4)
        self.assertEqual(evidence['SU.PA']['lastThree'][-1]['date'], PREVIOUS)
        result, rows = self.assemble(EUROPE_CLOCK, daily)
        for company in companies:
            row = rows[company['sym']]
            self.assertEqual(row['ld'], EXPECTED)
            self.assertEqual(row['provenance']['daily']['src'], meta_close.SOURCE)
        self.assertNotIn('mixed_or_missing_market_dates_need_label_approval', build.release_blockers(result))

    def test_real_daily_on_retry_wins_and_no_second_retry_is_needed(self):
        company = next(c for c in self.data['companies'] if c['sym'] == 'ENR.DE')
        symbol = company['sym']
        daily, _, calls, elapsed = self.run_rounds([company], {symbol: chart(company)}, EUROPE_CLOCK,
            retry_documents={symbol: chart(company, close=107.5)})
        self.assertEqual(calls, [(symbol, 60)])
        self.assertEqual(elapsed, 60)
        self.assertEqual(daily[symbol]['src'], 'yahoo')
        self.assertEqual(daily[symbol]['bars'][-1][1], 107.5)

    def test_retry_requests_and_total_time_are_bounded(self):
        companies = [c for c in self.data['companies'] if c['sym'] in ('ENR.DE', 'SU.PA')]
        documents = {c['sym']: chart(c) for c in companies}
        for seconds, limit, count, elapsed_expected in ((60, 240, 0, 0), (120, 240, 2, 60), (300, 1, 1, 60)):
            with self.subTest(seconds=seconds, limit=limit):
                _, _, calls, elapsed = self.run_rounds(companies, documents, EUROPE_CLOCK, seconds=seconds, limit=limit)
                self.assertEqual(len(calls), count)
                self.assertEqual(elapsed, elapsed_expected)

    def test_before_close_snapshot_does_not_supply_completed_close(self):
        company = next(c for c in self.data['companies'] if c['sym'] == 'ENR.DE')
        symbol = company['sym']
        daily, _, calls, _ = self.run_rounds([company], {symbol: chart(company, market_time='17:29:59')}, EUROPE_CLOCK)
        self.assertEqual(len(calls), 2)
        self.assertEqual(daily[symbol]['asOf'], PREVIOUS)
        self.assertNotIn('yahooMetaClose', daily[symbol])

    def test_newer_intraday_row_does_not_hide_missing_previous_close(self):
        company = next(c for c in self.data['companies'] if c['sym'] == 'ENR.DE')
        symbol = company['sym']
        clock = dt.datetime.fromisoformat('2026-11-10T10:15:00+01:00')
        original = chart(company, next_close=110)
        daily, _, calls, _ = self.run_rounds([company], {symbol: original}, clock, initial_date=NEXT)
        self.assertEqual(len(calls), 2)
        self.assertEqual(daily[symbol]['src'], meta_close.SOURCE)
        self.assertEqual(daily[symbol]['asOf'], EXPECTED)

        daily, _, calls, _ = self.run_rounds([company], {symbol: original}, clock, initial_date=NEXT,
            retry_documents={symbol: chart(company, close=109)})
        self.assertEqual(len(calls), 1)
        self.assertEqual(daily[symbol]['src'], 'yahoo')
        self.assertEqual(daily[symbol]['asOf'], EXPECTED)

        item = original['chart']['result'][0]['meta']
        item['regularMarketTime'] = int(dt.datetime.fromisoformat('2026-11-10T10:00:00+01:00').timestamp())
        daily, _, calls, _ = self.run_rounds([company], {symbol: original}, clock, initial_date=NEXT)
        self.assertEqual(len(calls), 2)
        self.assertEqual(daily[symbol]['asOf'], NEXT)
        self.assertNotIn('yahooMetaClose', daily[symbol])

    def test_newer_premature_provider_close_remains_a_conflict(self):
        company = next(c for c in self.data['companies'] if c['sym'] == 'ENR.DE')
        symbol = company['sym']
        clock = dt.datetime.fromisoformat('2026-11-10T10:15:00+01:00')
        original = chart(company, next_close=110)
        meta = original['chart']['result'][0]['meta']
        meta['currentTradingPeriod']['regular']['end'] = int(
            dt.datetime.fromisoformat('2026-11-10T10:00:00+01:00').timestamp())
        daily, _, calls, _ = self.run_rounds([company], {symbol: original}, clock, initial_date=NEXT)
        self.assertEqual(len(calls), 2)
        self.assertEqual(daily[symbol]['phase'], 'closed')
        self.assertNotIn('yahooMetaClose', daily[symbol])
        result, rows = self.assemble(clock, daily)
        self.assertIsNone(rows[symbol]['ld'])
        self.assertIn('mixed_or_missing_market_dates_need_label_approval', build.release_blockers(result))
