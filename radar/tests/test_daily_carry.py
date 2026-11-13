"""Conservative classifications and copied daily metrics with reviewed calendars."""

import copy
import datetime as dt
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import daily_carry
import latest
import yahoo_meta_close
from research_snapshot import canonical_json
from test_pr5_europe_missing_close import CLOCK as EUROPE_CLOCK, document, parse


KOREA = {'sym': '000660.KS', 'mkt': '韩股', 'cur': 'KRW'}
PARIS = {'sym': 'SU.PA', 'mkt': '欧股', 'cur': 'EUR'}
TAIWAN = {'sym': '2383.TW', 'mkt': '台股', 'cur': 'TWD'}
KOREA_CLOCK = dt.datetime.fromisoformat('2026-11-09T06:00:00+00:00')
SHA = '1' * 40


def read_chart(company, doc, clock):
    entry = doc['chart']['result'][0]
    entry['meta']['symbol'] = company['sym']
    entry['timestamp'] = [int(value) for value in entry['timestamp']]
    evidence = yahoo_meta_close.chart_evidence(doc, company['sym'], clock.isoformat())
    meta = doc['chart']['result'][0]['meta']
    evidence.update(currency=meta['currency'], timezone=meta['exchangeTimezoneName'])
    return parse(company['sym'], doc, clock), evidence


def korea_chart():
    zone = ZoneInfo('Asia/Seoul')

    def stamp(day, hour, minute=0):
        return int(dt.datetime.fromisoformat(f'{day}T{hour:02}:{minute:02}:00').replace(tzinfo=zone).timestamp())

    day = '2026-11-09'
    return {'chart': {'result': [{
        'meta': {'currency': 'KRW', 'exchangeTimezoneName': 'Asia/Seoul',
                 'currentTradingPeriod': {'regular': {'start': stamp(day, 9), 'end': stamp(day, 15, 30)}}},
        'timestamp': [stamp('2026-11-05', 9), stamp('2026-11-06', 9), stamp(day, 9)],
        'indicators': {'quote': [{'close': [590000, None, 620000]}],
                       'adjclose': [{'adjclose': [590000, None, 620000]}]},
    }]}}


def baseline(company, day, timezone, *, source='yahoo'):
    daily = {'src': source, 'asOf': day, 'receivedAt': day + 'T13:00:00+00:00',
             'returnBasis': 'yahoo-adjclose', 'phase': 'closed', 'timezone': timezone,
             'snapshotSelection': {'method': 'latest-completed-per-market'}}
    return {**company, 'price': 114.21, 'priceAsOf': day, 'pricePhase': 'closed', 'priceSource': source,
            'priceObservedAt': None, 'ld': day, 'metricAsOf': day, 'mcapUSD': 21, 'pe': 42,
            'r1d': 0.01, 'r5': 0.02, 'r20': 0.03, 'r60': None, 'ytd': 0.04, 'dd52': None, 'hi52': None,
            's0': '2026-10-01', 'sd': [0, 1], 'sc': [100.2, 114.2], 'history': {'count': 2, 'lastDate': day},
            'provenance': {'daily': daily, 'valuation': {'source': 'yahoo-quote'}}}


class DailyCarryTests(unittest.TestCase):
    def test_open_market_korea_and_europe_are_classified_by_null_close(self):
        for company, doc, clock in ((KOREA, korea_chart(), KOREA_CLOCK),
                                    (PARIS, document('Europe/Paris'), EUROPE_CLOCK)):
            with self.subTest(symbol=company['sym']):
                record, evidence = read_chart(company, doc, clock)
                chosen, _ = latest.select_daily([company], {company['sym']: record}, clock, calendar_policy=True)
                self.assertEqual(chosen, {})
                self.assertEqual(record['phase'], 'intraday')
                self.assertEqual(daily_carry.classify_missing(company, record, evidence, None, clock),
                                 daily_carry.CLOSE_NULL)

    def test_explicitly_absent_row_and_unambiguous_request_failure(self):
        doc = document('Europe/Paris')
        entry = doc['chart']['result'][0]
        del entry['timestamp'][1]
        del entry['indicators']['quote'][0]['close'][1]
        del entry['indicators']['quote'][0]['high'][1]
        del entry['indicators']['adjclose'][0]['adjclose'][1]
        record, evidence = read_chart(PARIS, doc, EUROPE_CLOCK)
        self.assertEqual(daily_carry.classify_missing(PARIS, record, evidence, None, EUROPE_CLOCK),
                         daily_carry.ROW_MISSING)
        for failure in ('transport_error_no_retry', 'TimeoutError',
                        {'failure': 'http_error_no_more_retries', 'requests': [{'httpStatus': 503}]}):
            self.assertEqual(daily_carry.classify_missing(PARIS, None, None, failure, EUROPE_CLOCK),
                             daily_carry.REQUEST_FAILED)
        for failure in (None, 'json_parse_failed', 'access_refused_stop_path', 'http_error_no_more_retries',
                        {'failure': 'http_error_no_more_retries', 'requests': [{'httpStatus': 403}]},
                        {'failure': 'transport_error_no_retry', 'requests': [{'httpStatus': 403}]}):
            self.assertIsNone(daily_carry.classify_missing(PARIS, None, None, failure, EUROPE_CLOCK))

    def test_empty_provider_chart_requires_own_identity_and_receipt(self):
        evidence = {'lastThree': [], 'currency': 'EUR', 'timezone': 'Europe/Paris',
                    'receivedAt': EUROPE_CLOCK.isoformat()}
        self.assertEqual(daily_carry.classify_missing(PARIS, None, evidence, None, EUROPE_CLOCK),
                         daily_carry.ROW_MISSING)
        for delta in ({'currency': 'USD'}, {'timezone': 'Asia/Tokyo'}, {'receivedAt': None}, {'chartShapeValid': False}):
            self.assertIsNone(daily_carry.classify_missing(PARIS, None, evidence | delta, None, EUROPE_CLOCK))

    def test_contradictory_records_override_an_explicit_null(self):
        record, evidence = read_chart(KOREA, korea_chart(), KOREA_CLOCK)
        bad_bars = copy.deepcopy(record['bars'])
        bad_bars[0][1] = -1
        future_bars = [*record['bars'], ['2026-11-10', 620000., None, None]]
        cases = {
            'currency': {'currency': 'USD'}, 'timezone': {'timezone': 'Asia/Tokyo'},
            'bad_bars': {'bars': bad_bars}, 'future_date': {'asOf': '2026-11-10', 'bars': future_bars},
            'invalid_independent_proof': {'independentCloseProof': {}}, 'invalid_yahoo_proof': {'yahooMetaClose': {}},
            'premature_close': {'phase': 'closed'}, 'unconfirmed_finality': {'finality': {}},
            'future_receipt': {'receivedAt': '2026-11-09T06:00:01Z'},
        }
        for name, changes in cases.items():
            with self.subTest(case=name):
                self.assertIsNone(daily_carry.classify_missing(KOREA, record | changes, evidence,
                                                               'TimeoutError', KOREA_CLOCK))
        for changes in ({'date': '2026-11-08'}, {'date': '2026-11-10'}, {'closeStatus': 'invalid'},
                        {'closeStatus': 'positive', 'close': 1.0}):
            bad_evidence = copy.deepcopy(evidence)
            bad_evidence['lastThree'][1].update(changes)
            self.assertIsNone(daily_carry.classify_missing(KOREA, record, bad_evidence, None, KOREA_CLOCK))
        self.assertIsNone(daily_carry.classify_missing(KOREA, record, evidence,
            {'failure': 'access_refused_stop_path', 'requests': [{'httpStatus': 403}]}, KOREA_CLOCK))
        before_open = dt.datetime.fromisoformat('2026-11-09T08:55:00+09:00')
        self.assertIsNone(daily_carry.classify_missing(KOREA, record, evidence, None, before_open))

    def test_reviewed_closure_blocks_carry_even_when_expected_row_is_absent(self):
        clock = dt.datetime.fromisoformat('2026-10-27T02:00:00Z')
        zone = ZoneInfo('Asia/Taipei')
        stamp = lambda day: int(dt.datetime.fromisoformat(day + 'T09:00:00').replace(tzinfo=zone).timestamp())
        bad_day = '2026-10-26'
        evidence = {'lastThree': [{'date': bad_day, 'timestamp': stamp(bad_day), 'close': 110., 'closeStatus': 'positive'}],
                    'currency': 'TWD', 'timezone': 'Asia/Taipei', 'receivedAt': clock.isoformat()}
        record = {'schemaVersion': 2, 'priceBasis': 'raw', 'src': 'yahoo', 'phase': 'closed', 'currency': 'TWD',
                  'asOf': bad_day, 'timezone': 'Asia/Taipei', 'receivedAt': clock.isoformat(),
                  'bars': [[bad_day, 110., None, None]], 'barTimestamps': {bad_day: stamp(bad_day)}}
        self.assertIsNone(daily_carry.classify_missing(TAIWAN, record, evidence, None, clock))

    def test_verified_close_and_previous_trading_day_cross_weekend_and_real_holiday(self):
        clock = dt.datetime.fromisoformat('2026-10-12T08:00:00Z')
        self.assertEqual(daily_carry.previous_completed_date(KOREA['sym'], clock), '2026-10-08')
        old = baseline(KOREA, '2026-10-08', 'Asia/Seoul')
        metrics, daily, marker = daily_carry.select_carry(KOREA, old, SHA, '123', daily_carry.CLOSE_NULL, clock)
        self.assertEqual(metrics, {key: old[key] for key in daily_carry.DAILY_METRIC_FIELDS})
        self.assertEqual(metrics['price'], 114.21)
        self.assertNotIn('mcapUSD', metrics)
        self.assertEqual(daily['src'], daily_carry.SOURCE)
        self.assertEqual(daily['carriedSource'], 'yahoo')
        self.assertEqual(marker, {'date': old['ld'], 'carriedSince': old['ld'], 'baselineProductionSHA': SHA,
                                  'baselineRunId': '123', 'reason': daily_carry.CLOSE_NULL})
        for invalid in (None, baseline(KOREA, '2026-10-07', 'Asia/Seoul'),
                        {**old, 'pricePhase': 'intraday'}, {**old, 'priceObservedAt': old['ld'] + 'T05:00:00Z'},
                        {**old, 'priceSource': 'yahoo-quote'}, {**old, 'priceAsOf': '2026-10-12'}):
            self.assertIsNone(daily_carry.select_carry(KOREA, invalid, SHA, '123', daily_carry.CLOSE_NULL, clock))
        old['provenance']['daily']['receivedAt'] = '2026-10-08T06:29:59+00:00'
        self.assertIsNone(daily_carry.select_carry(KOREA, old, SHA, '123', daily_carry.CLOSE_NULL, clock))

    def test_carry_chains_keep_original_date_and_drop_old_runtime_proof(self):
        day = '2026-11-06'
        old = baseline(KOREA, day, 'Asia/Seoul', source=yahoo_meta_close.SOURCE)
        old['provenance']['daily']['yahooMetaClose'] = {'date': day}
        before = canonical_json(old)
        first = daily_carry.select_carry(KOREA, old, SHA, '123', daily_carry.CLOSE_NULL, KOREA_CLOCK)
        metrics, daily, marker = first
        self.assertEqual(before, canonical_json(old))
        self.assertNotIn('yahooMetaClose', daily)
        carried = {**old, **metrics, 'carried': marker, 'priceSource': daily_carry.SOURCE,
                   'provenance': {'daily': daily}}
        next_clock = dt.datetime.fromisoformat('2026-11-09T08:00:00Z')
        _, again, second_marker = daily_carry.select_carry(KOREA, carried, '2' * 40, '124',
                                                           daily_carry.REQUEST_FAILED, next_clock)
        self.assertEqual(again['carriedSource'], yahoo_meta_close.SOURCE)
        self.assertEqual(second_marker['carriedSince'], day)
        self.assertEqual(second_marker['baselineRunId'], '124')
        self.assertIsNone(daily_carry.select_carry(KOREA, carried, '2' * 40, '124', daily_carry.CLOSE_NULL,
                                                  dt.datetime.fromisoformat('2026-11-10T08:00:00Z')))
