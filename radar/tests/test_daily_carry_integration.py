"""Exercise daily carry through production assembly and release binding."""
import copy
import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import acceptance_bundle as bundle
import build
import daily_carry
import market_calendar
from production_collect import step_summary
from release_operations import prevent_publication_regression, validate_current_carry_baseline
from test_daily_carry import KOREA, KOREA_CLOCK, PARIS, SHA, baseline, korea_chart, read_chart
from test_integrity import dataset
from test_pr5_calendar_release import synthetic_market
from test_pr5_europe_missing_close import CLOCK as EUROPE_CLOCK, document


class DailyCarryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.data, _ = dataset()

    def assemble(self, market, now, baseline_data=None, evidence=None, transport=None):
        return build.assemble(self.data, market, market, now, calendar_policy=True,
            daily_baseline=baseline_data, daily_evidence=evidence, daily_transport=transport)[0]

    def baseline(self, market, now):
        return {'runId': '123'}, self.assemble(market, now), {'productionSHA': SHA}

    def check_bound(self, output, now, prior):
        bundle.validate_carried_daily(output, now)
        bundle.validate_carried_daily_baseline(output, now, *prior)

    def test_korea_and_europe_use_only_the_verified_prior_close(self):
        for company, chart, now in ((KOREA, korea_chart(), KOREA_CLOCK),
                                    (PARIS, document('Europe/Paris'), EUROPE_CLOCK)):
            with self.subTest(symbol=company['sym']):
                symbol = company['sym']
                market = synthetic_market(self.data, now)
                day = market_calendar.context(symbol, now)['expectedCompletedDate']
                row = baseline(company, day, market_calendar.context(symbol, now)['timezone'])
                spec = market_calendar.calendar_data()['exchanges'][market_calendar.exchange_for(symbol)]
                row['provenance']['daily']['receivedAt'] = market_calendar.session_close(spec, dt.date.fromisoformat(day)).isoformat()
                prior = ({'runId': '123'}, {'companies': [row]}, {'productionSHA': SHA})
                market['daily'][symbol], raw = read_chart(company, chart, now)
                self.assertIn('mixed_or_missing_market_dates_need_label_approval', build.release_blockers(self.assemble(market, now)))
                output = self.assemble(market, now, prior, {symbol: raw})
                self.assertEqual(build.release_blockers(output), [])
                self.check_bound(output, now, prior)
                picked = next(item for item in output['companies'] if item['sym'] == symbol)
                self.assertEqual(picked['price'], row['price'])
                self.assertEqual(picked['carried']['reason'], daily_carry.CLOSE_NULL)
                self.assertFalse(picked['priceSelection']['useQuote'])
                self.assertNotEqual(picked['mcapUSD'], row['mcapUSD'])
                self.assertIn(f'{day} 收盘，本次未取得', step_summary(output))
                tampered = copy.deepcopy(output)
                next(item for item in tampered['companies'] if item['sym'] == symbol)['r5'] = 0.66
                with self.assertRaisesRegex(bundle.BundleError, 'carried_daily_baseline_mismatch'):
                    bundle.validate_carried_daily_baseline(tampered, now, *prior)

    def test_exact_dynamic_limit_passes_and_one_above_blocks_every_carry(self):
        now = dt.datetime.fromisoformat('2026-11-10T20:00:00+08:00')
        market = synthetic_market(self.data, now)
        prior = self.baseline(market, now)
        limit = len(self.data['companies']) // 10
        companies = [row for row in prior[1]['companies'] if row['mkt'] == 'A股' and row['ld']][:limit + 1]
        self.assertEqual(len(companies), limit + 1)
        transport = {}
        for row in companies[:limit]:
            del market['daily'][row['sym']]
            transport[row['sym']] = {'failure': 'transport_error_no_retry'}
        output = self.assemble(market, now, prior, transport=transport)
        self.assertEqual(build.release_blockers(output), [])
        self.assertEqual(output['meta']['carriedDaily']['count'], limit)
        self.check_bound(output, now, prior)
        symbol = companies[-1]['sym']
        del market['daily'][symbol]
        transport[symbol] = {'failure': 'transport_error_no_retry'}
        blocked = self.assemble(market, now, prior, transport=transport)
        self.assertIn('carried_daily_exceeds_limit', build.release_blockers(blocked))
        self.assertFalse(any(row.get('carried') for row in blocked['companies']))

    def test_unavailable_baseline_and_index_do_not_gain_a_carry(self):
        now = KOREA_CLOCK
        symbol = KOREA['sym']
        market = synthetic_market(self.data, now)
        prior = self.baseline(market, now)
        del market['daily'][symbol]
        transport = {symbol: {'failure': 'transport_error_no_retry'}}
        missing_row = (prior[0], {'companies': [row for row in prior[1]['companies'] if row['sym'] != symbol]}, prior[2])
        for unavailable in (None, missing_row):
            result = self.assemble(market, now, unavailable, transport=transport)
            self.assertIn('mixed_or_missing_market_dates_need_label_approval', build.release_blockers(result))
            self.assertNotIn('carriedDaily', result['meta'])
        market['index'].pop('^GSPC')
        result = self.assemble(market, now, prior, transport=transport)
        self.assertEqual(result['meta']['carriedDaily']['count'], 1)
        self.assertIn('index_observation_missing_or_stale', build.release_blockers(result))

    def test_carried_original_date_does_not_advance_or_rewind_release_clock(self):
        now = KOREA_CLOCK
        previous = now - dt.timedelta(minutes=5)
        market = synthetic_market(self.data, now)
        prior = self.baseline(synthetic_market(self.data, previous), previous)
        symbol = KOREA['sym']
        del market['daily'][symbol]
        output = self.assemble(market, now, prior, transport={symbol: {'failure': 'transport_error_no_retry'}})
        self.check_bound(output, now, prior)
        candidate = {'fixedClock': now.isoformat(), 'dataSHA256': bundle.data_digest(output)}
        current = {'fixedClock': previous.isoformat(), 'dataSHA256': bundle.data_digest(prior[1])}
        prevent_publication_regression(candidate, output, current, prior[1])
        validate_current_carry_baseline(output, candidate, prior[0], prior[1], SHA)
        with self.assertRaisesRegex(bundle.BundleError, 'carried_daily_baseline_mismatch'):
            validate_current_carry_baseline(output, candidate, prior[0], prior[1], '2' * 40)
        with self.assertRaisesRegex(ValueError, 'publication_older_than_production'):
            prevent_publication_regression(current, prior[1], candidate, output)
