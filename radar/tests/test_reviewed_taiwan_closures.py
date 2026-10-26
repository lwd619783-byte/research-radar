"""Synthetic regressions for independently reviewed Taiwan non-trading dates.

No network requests and no existing fixture/expected-result changes.
"""
import copy
import datetime as dt
import unittest
import latest
import reviewed_closures
from integrity import fresh_record, release_blockers
from test_completed_snapshot import session_record, epoch
from test_review_regressions import complete_dataset, monthly_record
from test_integrity import build, historical_fx

NOW = dt.datetime.fromisoformat('2026-10-26T17:45:00+08:00')
TW = {'sym': '2383.TW', 'mkt': '台股', 'cur': 'TWD'}


def record(days=('2026-10-21', '2026-10-22', '2026-10-23'), *, now=NOW, session_day='2026-10-23'):
    r = session_record(list(days), TW['mkt'], now, session_day, TW['cur'])
    r['finality']['end'] = epoch(session_day, 'Asia/Taipei', 13) + 30*60
    return r


def select(r, now=NOW, company=TW):
    return latest.select_daily([company], {company['sym']: r}, now)[0]


def full_synthetic_market(now):
    """Existing 42-company synthetic contract, with fresh provider-shaped inputs."""
    data, market = complete_dataset()
    for c in data['companies']:
        r = market['daily'][c['sym']]
        r['bars'] = [[(dt.date.fromisoformat(b[0])+dt.timedelta(days=7)).isoformat(), *b[1:]] for b in r['bars']]
        r.update(asOf='2026-10-23', receivedAt=now.isoformat())
        market['quote'][c['sym']].update(receivedAt=now.isoformat(), regularMarketTime=epoch('2026-10-23','UTC',12))
    history = [b[0] for b in market['daily']['2383.TW']['bars']]
    market['daily']['2383.TW'] = record(history, now=now)
    market['daily']['2383.TW']['bars'][-1][1:] = [99999.,99999.,100000.]
    market['quote']['2383.TW'].update(regularMarketTime=epoch('2026-10-23','Asia/Taipei',13),regularMarketPrice=99999.)
    for r in market['index'].values():
        r.update(date='2026-10-23', receivedAt=now.isoformat())
    for cur in market['fx']:
        start=epoch('2026-10-23','UTC',0)
        market['fx'][cur]=historical_fx(cur, rates=[['2026-10-23',7.,1/7 if cur=='EUR' else 7.]],
            receivedAt=now.isoformat(),finality={'method':'provider-session-boundary','start':start,'end':start+86400})
    market['ratio']={'cyb':monthly_record('2026-10-23'),'hl':monthly_record('2026-10-23',True)}
    for r in market['ratio'].values():r['receivedAt']=now.isoformat()
    return data,market


class ReviewedTaiwanClosuresTests(unittest.TestCase):
    def test_official_closed_tail_selects_actual_22_without_rewriting_original(self):
        r = record(); before = copy.deepcopy(r)
        self.assertEqual(r['phase'], 'closed')
        selected = select(r)['2383.TW']
        self.assertEqual(selected['asOf'], '2026-10-22')
        self.assertEqual(selected['bars'], before['bars'][:-1])
        self.assertEqual(selected['receivedAt'], before['receivedAt'])
        self.assertEqual(selected['finality'], before['finality'])
        self.assertEqual(selected['snapshotSelection']['sourceAsOf'], '2026-10-23')
        self.assertEqual(r, before)

    def test_official_26_and_weekend_tail_cannot_be_reported_as_trades(self):
        r = record(('2026-10-21','2026-10-22','2026-10-23','2026-10-24','2026-10-25','2026-10-26'), session_day='2026-10-26')
        self.assertEqual([b[0] for b in select(r)['2383.TW']['bars']], ['2026-10-21','2026-10-22'])

    def test_missing_required_22_is_not_replaced_by_21(self):
        self.assertEqual(select(record(('2026-10-21','2026-10-23'))), {})

    def test_old_receipt_stays_rejected(self):
        r = record(); r['receivedAt'] = (NOW-dt.timedelta(hours=37)).isoformat()
        self.assertEqual(select(r), {})
        self.assertFalse(fresh_record(r, NOW, '2026-10-22', '台股'))

    def test_receipt_exactly_36_hours_keeps_existing_boundary(self):
        r = record(); r['receivedAt'] = (NOW-dt.timedelta(hours=36)).isoformat()
        self.assertTrue(fresh_record(r, NOW, '2026-10-22', '台股'))
        r['receivedAt'] = (NOW-dt.timedelta(hours=36,seconds=1)).isoformat()
        self.assertFalse(fresh_record(r, NOW, '2026-10-22', '台股'))

    def test_no_calendar_substitute_for_missing_provider_proof(self):
        for key in ('finality','barTimestamps','timezone'):
            with self.subTest(key=key):
                r = record(); r.pop(key)
                self.assertEqual(select(r), {})
        r = record();r['finality']['method']='guessed'
        self.assertEqual(select(r), {})

    def test_unknown_phase_and_future_source_date_stay_rejected(self):
        r = record();r['phase']='unknown';self.assertEqual(select(r), {})
        r = record(('2026-10-22','2026-10-23','2026-10-27'))
        self.assertEqual(select(r), {})

    def test_27_before_actual_close_accepts_observed_22_with_fresh_receipt(self):
        for time in ('06:50:00','08:45:00','12:15:00','13:29:59'):
            with self.subTest(time=time):
                now=dt.datetime.fromisoformat('2026-10-27T'+time+'+08:00')
                r=record(now=now)
                self.assertEqual(select(r,now)['2383.TW']['asOf'],'2026-10-22')
                self.assertTrue(fresh_record(r,now,'2026-10-22','台股'))

    def test_27_at_and_after_close_requires_actual_27(self):
        for time in ('13:30:00','18:15:00'):
            with self.subTest(time=time):
                now=dt.datetime.fromisoformat('2026-10-27T'+time+'+08:00')
                r=record(now=now)
                self.assertEqual(select(r,now),{})
                self.assertFalse(fresh_record(r,now,'2026-10-22','台股'))
                r=record(('2026-10-21','2026-10-22','2026-10-23','2026-10-27'),now=now,session_day='2026-10-27')
                r['phase']='closed'
                self.assertEqual(select(r,now)['2383.TW']['asOf'],'2026-10-27')
                self.assertNotIn('2026-10-23',[b[0] for b in select(r,now)['2383.TW']['bars']])

    def test_normal_trading_day_cannot_be_silently_skipped_before_close(self):
        now=dt.datetime.fromisoformat('2026-10-27T12:15:00+08:00')
        r=record(('2026-10-22','2026-10-27'),now=now,session_day='2026-10-27')
        r['finality']['end']=epoch('2026-10-27','Asia/Taipei',11);r['phase']='closed'
        self.assertEqual(select(r,now),{})

    def test_other_market_and_outside_window_freshness_are_unchanged(self):
        r=record()
        self.assertIsNone(reviewed_closures.expected_close('A股',NOW))
        self.assertTrue(fresh_record(r,NOW,'2026-10-23','A股'))
        self.assertFalse(fresh_record(r,NOW,'2026-10-21','A股'))
        self.assertIsNone(reviewed_closures.expected_close('台股',dt.datetime.fromisoformat('2026-10-28T08:45:00+08:00')))

    def test_closed_date_quotes_cannot_override_corrected_daily_or_valuation(self):
        for day in ('2026-10-23','2026-10-26'):
            q={'schemaVersion':2,'receivedAt':NOW.isoformat(),'regularMarketTime':epoch(day,'Asia/Taipei',13),
               'currency':'TWD','regularMarketPrice':999.,'marketCap':1e12,'trailingPE':99.,'marketState':'CLOSED'}
            chosen,status,observed=latest.select_quote(q,'2026-10-22','台股','TWD',NOW)
            self.assertEqual(chosen,{})
            self.assertEqual(status,'quote_on_confirmed_market_closure')
            self.assertEqual(observed,day)

    def test_actual_22_quote_remains_usable_and_older_quote_does_not(self):
        q={'schemaVersion':2,'receivedAt':NOW.isoformat(),'regularMarketTime':epoch('2026-10-22','Asia/Taipei',13),
           'currency':'TWD','regularMarketPrice':100.,'marketState':'CLOSED'}
        self.assertEqual(latest.select_quote(q,'2026-10-22','台股','TWD',NOW)[1],'available')
        q['regularMarketTime']=epoch('2026-10-21','Asia/Taipei',13)
        self.assertEqual(latest.select_quote(q,'2026-10-22','台股','TWD',NOW)[0],{})

    def test_build_uses_actual_close_and_retains_source_date_without_fake_quote(self):
        data,mk=complete_dataset();c=next(c for c in data['companies'] if c['sym']=='2383.TW')
        r=record();r['bars'][-1][1:]=[999.,999.,1000.];mk['daily']['2383.TW']=r
        mk['quote']['2383.TW'].update(receivedAt=NOW.isoformat(),regularMarketTime=epoch('2026-10-23','Asia/Taipei',13),regularMarketPrice=999.)
        before=copy.deepcopy(mk)
        row=next(x for x in build.assemble(data,mk,mk,NOW)[0]['companies'] if x['sym']=='2383.TW')
        self.assertEqual(row['metricAsOf'],'2026-10-22')
        self.assertEqual(row['priceAsOf'],'2026-10-22')
        self.assertEqual(row['price'],r['bars'][-2][1])
        self.assertNotIn(999.,row['sc'])
        self.assertIsNone(row['pe']);self.assertIsNone(row['mcapUSD'])
        self.assertEqual(row['provenance']['daily']['snapshotSelection']['sourceAsOf'],'2026-10-23')
        self.assertEqual(row['provenance']['valuation']['sourceAsOf'],'2026-10-23')
        self.assertEqual(mk,before)

    def test_full_merge_and_build_42_companies_keep_no_market_blockers(self):
        for now in (NOW,dt.datetime.fromisoformat('2026-10-27T08:45:00+08:00')):
            with self.subTest(now=now):
                data,fresh=full_synthetic_market(now);before=copy.deepcopy(fresh)
                merged=build.merge(fresh,{})
                self.assertIs(merged['daily']['2383.TW'],fresh['daily']['2383.TW'])
                result,stale,missing=build.assemble(data,merged,fresh,now)
                result['meta']['fixture']=True
                self.assertEqual(result['meta']['blockers'],[])
                self.assertEqual(stale,[]);self.assertEqual(missing,[])
                self.assertEqual(sum(c['price'] is not None for c in result['companies']),42)
                self.assertEqual(release_blockers(result),['synthetic_fixture_not_publishable'])
                row=next(c for c in result['companies'] if c['sym']=='2383.TW')
                self.assertEqual(row['metricAsOf'],'2026-10-22')
                self.assertEqual(row['priceAsOf'],'2026-10-22')
                self.assertEqual(row['price'],fresh['daily']['2383.TW']['bars'][-2][1])
                self.assertNotIn(99999.,row['sc'])
                self.assertIsNone(row['pe']);self.assertIsNone(row['mcapUSD'])
                self.assertEqual(fresh,before)

    def test_full_build_real_gap_after_27_close_remains_blocked(self):
        now=dt.datetime.fromisoformat('2026-10-27T18:15:00+08:00')
        data,fresh=full_synthetic_market(now)
        result,stale,missing=build.assemble(data,build.merge(fresh,{}),fresh,now)
        self.assertIn('mixed_or_missing_market_dates_need_label_approval',release_blockers(result))
        self.assertIn('stale_quotes_not_safe_in_all_frozen_views',release_blockers(result))
        row=next(c for c in result['companies'] if c['sym']=='2383.TW')
        self.assertIsNone(row['price'])

    def test_later_clock_cannot_promote_payload_received_before_official_reopening_close(self):
        now=dt.datetime.fromisoformat('2026-10-27T14:00:00+08:00')
        for receipt in ('2026-10-27T12:15:00+08:00','2026-10-27T14:00:00+08:00'):
            with self.subTest(receipt=receipt):
                r=record(('2026-10-21','2026-10-22','2026-10-23','2026-10-27'),
                         now=dt.datetime.fromisoformat(receipt),session_day='2026-10-27')
                r['finality']['end']=epoch('2026-10-27','Asia/Taipei',11)
                r['phase']='closed'
                self.assertEqual(select(r,now),{})

    def test_extended_five_day_carry_without_false_tail_still_requires_provider_proof(self):
        now=dt.datetime.fromisoformat('2026-10-27T08:45:00+08:00')
        for missing in (('finality',),('barTimestamps',),('timezone',),('finality','barTimestamps','timezone')):
            with self.subTest(missing=missing):
                r=record(('2026-10-21','2026-10-22'),now=now)
                for key in missing:r.pop(key)
                self.assertEqual(select(r,now),{})


if __name__ == '__main__':
    unittest.main()
