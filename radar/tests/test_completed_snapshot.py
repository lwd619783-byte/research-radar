"""Historical common-day policy regressions (not product default); offline only."""
import copy
import datetime as dt
import gzip
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from test_integrity import build, quotes, historical_fx
from test_review_regressions import complete_dataset
from integrity import ZONES, release_blockers
from snapshot import completed_bars, select_daily, select_quote, select_index

def historical_assemble(*args):
    return build.assemble(*args, snapshot_policy='common-completed')


MONDAY = dt.datetime(2026, 10, 19, 1, 19, tzinfo=dt.UTC)
FRIDAY = '2026-10-16'


def epoch(day, zone, hour=9):
    return dt.datetime.fromisoformat(day).replace(hour=hour, tzinfo=ZoneInfo(zone)).timestamp()


def session_record(days, market='日股', now=MONDAY, session_day='2026-10-19', currency='JPY'):
    zone = ZONES[market]
    return {'schemaVersion': 2, 'receivedAt': now.isoformat(), 'src': 'yahoo',
        'bars': [[day, 100.+i, 100.+i, 110.+i] for i,day in enumerate(days)],
        'asOf': days[-1], 'phase': 'intraday' if days[-1]==session_day and now.timestamp()<epoch(session_day,zone,16) else 'closed',
        'priceBasis': 'raw', 'returnBasis': 'yahoo-adjclose', 'currency': currency,
        'timezone': zone, 'barTimestamps': {day:epoch(day,zone) for day in days},
        'finality': {'method':'provider-session-boundary', 'start':epoch(session_day,zone), 'end':epoch(session_day,zone,16)}}


def monday_dataset():
    data,mk=complete_dataset()
    for group in mk.values():
        for record in group.values():record['receivedAt']=MONDAY.isoformat()
    for c in data['companies']:
        r=mk['daily'][c['sym']]
        if c['sym'] in ('000660.KS','3110.T'):
            base=r['bars']
            proof=session_record([b[0] for b in base]+['2026-10-19'],c['mkt'],currency=c['cur'])
            proof['bars']=copy.deepcopy(base)+[['2026-10-19',999.,999.,1000.]]
            mk['daily'][c['sym']]=proof
        q=mk['quote'][c['sym']]
        q['regularMarketTime']=epoch(FRIDAY,ZONES[c['mkt']],16)
        if c['sym'] in ('000660.KS','3110.T','2383.TW'):
            q.update(regularMarketTime=(MONDAY-dt.timedelta(minutes=1)).timestamp(),marketState='REGULAR',marketCap=9e12,trailingPE=999.)
        if c['sym'] in ('LITE','000660.KS'):q['trailingPE']=None
    fixture=Path(__file__).resolve().parents[2]/'audit/truthfulness-2026-10-18/fixtures/market-finality.json.gz'
    cxmt=json.loads(gzip.decompress(fixture.read_bytes()))['daily']['688825.SS']
    cxmt['receivedAt']=MONDAY.isoformat()
    mk['daily']['688825.SS']=cxmt
    return data,mk


class CompletedSnapshotTests(unittest.TestCase):
    def test_monday_mixed_seven_markets_unifies_prices_not_intraday_valuations(self):
        data,mk=monday_dataset();before=copy.deepcopy(mk)
        D,stale,missing=historical_assemble(data,mk,mk,MONDAY)
        self.assertFalse(stale);self.assertFalse(missing)
        self.assertEqual(D['meta']['snapshot']['status'],'complete')
        self.assertEqual(D['meta']['asOf'],FRIDAY)
        self.assertTrue(all(c['ld']==FRIDAY for c in D['companies']))
        self.assertEqual(mk,before)  # original cache/request receipts are never rewritten
        self.assertNotIn('mixed_or_missing_market_dates_need_label_approval',release_blockers(D))
        self.assertNotIn('unconfirmed_close_or_intraday_needs_label_approval',release_blockers(D))
        rows={c['sym']:c for c in D['companies']}
        for sym in ('000660.KS','3110.T','2383.TW'):
            self.assertIsNone(rows[sym]['mcapUSD']);self.assertIsNone(rows[sym]['pe'])
            self.assertEqual(rows[sym]['provenance']['valuation']['selectionStatus'],'quote_date_mismatch_or_missing')
        self.assertEqual(sum(c['mcapUSD'] is not None for c in D['companies']),39)
        self.assertIsNone(rows['LITE']['pe'])
        self.assertEqual(rows['000660.KS']['provenance']['valuation']['sourcePeStatus'],'missing')
        cxmt=rows['688825.SS']
        self.assertEqual(cxmt['history']['count'],54)
        self.assertEqual(cxmt['s0'],'2026-07-27')
        for key in ('r60','hi52','dd52'):self.assertIsNone(cxmt[key])
        self.assertEqual(sum(c['financialPartial'] for c in D['companies']),2)
        self.assertFalse(any(c['financialSignalEligible'] for c in D['companies'] if c['financialPartial']))
        self.assertTrue(all(c['provenance']['valuation']['fx']['asOf']==FRIDAY for c in D['companies'] if c['mcapUSD'] is not None))

    def test_provider_intraday_bar_is_removed_only_with_frozen_session_proof(self):
        r=session_record(['2026-10-15',FRIDAY,'2026-10-19'])
        self.assertEqual([b[0] for b in completed_bars(r)],['2026-10-15',FRIDAY])
        r.pop('finality');self.assertEqual(completed_bars(r),[])
        r['phase']='unknown';self.assertEqual(completed_bars(r),[])

    def test_waiting_does_not_finalize_cached_intraday_bar(self):
        r=session_record([FRIDAY,'2026-10-19'])
        c={'sym':'J','mkt':'日股','cur':'JPY'}
        later=MONDAY+dt.timedelta(hours=8)
        selected,meta=select_daily([c],{'J':r},later)
        self.assertEqual(meta['selectedDate'],FRIDAY)
        self.assertEqual(selected['J']['receivedAt'],MONDAY.isoformat())

    def test_unknown_or_invalid_finality_never_falls_back_to_closed_flag(self):
        for change in ({'phase':'unknown'}, {'finality':{}}, {'timezone':'bad-zone'},
                       {'barTimestamps':{}}, {'receivedAt':'2026-10-19'}, {'schemaVersion':1}):
            with self.subTest(change=change):
                r=session_record([FRIDAY]);r.update(change)
                self.assertEqual(completed_bars(r),[])

    def test_us_date_is_exchange_local_not_utc(self):
        # 2026-10-20 00:30Z is still October 19 in New York.
        now=dt.datetime(2026,10,20,1,tzinfo=dt.UTC)
        q={'schemaVersion':2,'receivedAt':now.isoformat(),'marketState':'POST',
           'regularMarketTime':dt.datetime(2026,10,20,0,30,tzinfo=dt.UTC).timestamp(),'currency':'USD'}
        accepted,status,day=select_quote(q,'2026-10-19','美股','USD',now)
        self.assertEqual(status,'available');self.assertIs(accepted,q);self.assertEqual(day,'2026-10-19')

    def test_weekend_and_holiday_use_observed_days_without_fabricated_sessions(self):
        c={'sym':'J','mkt':'日股','cur':'JPY'}
        for now,last in ((dt.datetime(2026,10,18,1,tzinfo=dt.UTC),FRIDAY),
                         (MONDAY,'2026-10-15')):  # hypothetical Friday local holiday
            with self.subTest(last=last):
                r=session_record([last],now=now)
                selected,meta=select_daily([c],{'J':r},now)
                self.assertEqual(meta['selectedDate'],last)
                self.assertEqual(selected['J']['bars'],r['bars'])
        r=session_record(['2026-10-14'])
        self.assertIsNone(select_daily([c],{'J':r},MONDAY)[1]['selectedDate'])  # 5 days is still stale

    def test_no_common_actual_day_does_not_pick_nearest_or_relabel(self):
        cs=[{'sym':'J','mkt':'日股','cur':'JPY'},{'sym':'K','mkt':'韩股','cur':'KRW'}]
        records={'J':session_record([FRIDAY]),'K':session_record(['2026-10-15'],'韩股',currency='KRW')}
        selected,meta=select_daily(cs,records,MONDAY)
        self.assertFalse(selected);self.assertIsNone(meta['selectedDate'])
        self.assertEqual(meta['status'],'incomplete')

    def test_timezone_mismatch_and_future_session_same_day_do_not_prove_close(self):
        r=session_record([FRIDAY],'美股',currency='JPY')
        selected,meta=select_daily([{'sym':'J','mkt':'日股','cur':'JPY'}],{'J':r},MONDAY)
        self.assertFalse(selected);self.assertEqual(meta['status'],'incomplete')
        # A next-session boundary cannot prove today's unfinished bar closed.
        now=dt.datetime(2026,10,16,1,tzinfo=dt.UTC)
        r=session_record([FRIDAY],now=now)
        self.assertEqual(completed_bars(r),[])

    def test_stale_cached_history_is_never_silently_refreshed_by_selection(self):
        data,mk=monday_dataset();fresh=copy.deepcopy(mk)
        symbol=data['companies'][0]['sym'];fresh['daily'].pop(symbol)
        D,stale,_=historical_assemble(data,mk,fresh,MONDAY)
        self.assertIn(data['companies'][0]['name'],stale)
        self.assertIn('stale_quotes_not_safe_in_all_frozen_views',release_blockers(D))

    def test_missing_and_unknown_company_do_not_claim_complete_snapshot(self):
        data,mk=monday_dataset()
        for value in (None,{'schemaVersion':2,'phase':'unknown'}):
            with self.subTest(value=value):
                broken=copy.deepcopy(mk);broken['daily'][data['companies'][0]['sym']]=value
                D,_,missing=historical_assemble(data,broken,broken,MONDAY)
                self.assertTrue(missing);self.assertEqual(D['meta']['snapshot']['status'],'incomplete')
                self.assertIn('mixed_or_missing_market_dates_need_label_approval',release_blockers(D))

    def test_quote_unknown_intraday_future_receipt_and_currency_mismatch_stay_missing(self):
        q={'schemaVersion':2,'receivedAt':MONDAY.isoformat(),'marketState':'CLOSED',
           'regularMarketTime':epoch(FRIDAY,'Asia/Tokyo',16),'currency':'JPY','marketCap':100,'trailingPE':10}
        for changes,expected in (({'marketState':None},'quote_close_unconfirmed'),
                                 ({'marketState':'REGULAR'},'quote_close_unconfirmed'),
                                 ({'currency':'USD'},'quote_currency_mismatch'),
                                 ({'receivedAt':'2026-10-16T06:00:00+00:00'},'quote_stale_or_invalid_receipt')):
            with self.subTest(changes=changes):
                self.assertEqual(select_quote({**q,**changes},FRIDAY,'日股','JPY',MONDAY)[1],expected)
        future=MONDAY+dt.timedelta(minutes=1)
        self.assertEqual(select_quote({**q,'regularMarketTime':future.timestamp()},'2026-10-19','日股','JPY',MONDAY)[1],'quote_observation_after_receipt')

    def test_fx_exact_day_required_for_valuation_and_meta(self):
        data,mk=monday_dataset();c=next(c for c in data['companies'] if c['cur']=='CNY')
        mk['fx']['CNY']=historical_fx('CNY',rates=[['2026-10-15',7.,7.]],receivedAt=MONDAY.isoformat())
        D=historical_assemble(data,mk,mk,MONDAY)[0]
        row=next(r for r in D['companies'] if r['sym']==c['sym'])
        self.assertIsNone(row['mcapUSD']);self.assertIsNone(row['provenance']['valuation']['fx'])
        self.assertNotIn('CNY',D['meta']['fx']);self.assertIsNotNone(row['pe'])

    def test_index_recomputes_change_from_exact_completed_history(self):
        h=session_record(['2026-10-15',FRIDAY,'2026-10-19'])
        r={'schemaVersion':2,'receivedAt':MONDAY.isoformat(),'date':'2026-10-19',
           'phase':'intraday','price':999.,'chg':9.,'dailyHistory':h,'src':'yahoo'}
        v=select_index(r,FRIDAY,MONDAY)
        self.assertEqual(v['price'],101.);self.assertAlmostEqual(v['chg'],.01)
        self.assertEqual(v['date'],FRIDAY);self.assertEqual(v['sourceDate'],'2026-10-19')
        r['dailyHistory']=session_record([FRIDAY])
        self.assertIsNone(select_index(r,FRIDAY,MONDAY))
        r['dailyHistory']=None;r.update(date=FRIDAY,phase='unknown')
        self.assertIsNone(select_index(r,FRIDAY,MONDAY))

    def test_index_unknown_and_wrong_day_are_not_rendered_and_still_block(self):
        data,mk=monday_dataset();key=data['config']['indices'][0]['symbol']
        for change in ({'phase':'unknown'},{'date':'2026-10-19'}):
            with self.subTest(change=change):
                broken=copy.deepcopy(mk);broken['index'][key].update(change)
                D=historical_assemble(data,broken,broken,MONDAY)[0]
                self.assertEqual(len(D['indices']),len(data['config']['indices'])-1)
                self.assertIn('index_date_or_phase_needs_label_approval',release_blockers(D))

    def test_yahoo_adapter_keeps_session_proof_and_quote_state_without_extra_requests(self):
        zone='Asia/Tokyo';days=[FRIDAY,'2026-10-19']
        class H:
            def __init__(self):self.calls=[]
            def crumb(self):return 'synthetic'
            def yahoo(self,path):
                self.calls.append(path)
                if '/v7/' in path:
                    return {'quoteResponse':{'result':[{'symbol':'J','marketCap':100,'trailingPE':10,'currency':'JPY',
                        'regularMarketTime':epoch('2026-10-19',zone),'marketState':'REGULAR'}]}}
                return {'chart':{'result':[{'meta':{'currency':'JPY','exchangeTimezoneName':zone,
                    'currentTradingPeriod':{'regular':{'start':epoch('2026-10-19',zone),'end':epoch('2026-10-19',zone,16)}}},
                    'timestamp':[epoch(day,zone) for day in days],
                    'indicators':{'quote':[{'close':[100,999],'high':[110,1000]}],'adjclose':[{'adjclose':[100,999]}]}}]}}
        h=H()
        with patch.object(quotes,'stamp',side_effect=lambda **kw:dict(kw,schemaVersion=2,receivedAt=MONDAY.isoformat())):
            r=quotes.yahoo_daily(h,'J');q=quotes.yahoo_quotes(h,['J'])['J']
        self.assertEqual(len(h.calls),2);self.assertEqual(r['phase'],'intraday')
        self.assertEqual(completed_bars(r),[[FRIDAY,100.,100.,110.]])
        self.assertEqual(q['marketState'],'REGULAR')

if __name__=='__main__':unittest.main()
