"""Offline synthetic sessions and saved public diagnostics; NEVER new requests."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error
from test_completed_snapshot import monday_dataset, MONDAY, FRIDAY, epoch, session_record
from test_review_regressions import complete_dataset, monthly_record
from test_integrity import build, quotes, historical_fx, NOW
import latest
import acceptance_probe as probe
from integrity import ZONES

ROOT=Path(__file__).resolve().parents[2]

class LatestMarketTests(unittest.TestCase):
    def test_current_quote_and_completed_metrics_are_independent_without_splice(self):
        data,mk=monday_dataset();before=copy.deepcopy(mk)
        for c in data['companies']:
            mk['quote'][c['sym']]['regularMarketPrice']=321.
        D,_,_=build.assemble(data,mk,mk,MONDAY)
        rows={r['sym']:r for r in D['companies']}
        self.assertEqual(rows['000660.KS']['price'],321.)
        self.assertEqual(rows['000660.KS']['priceAsOf'],'2026-10-19')
        self.assertEqual(rows['000660.KS']['pricePhase'],'intraday')
        self.assertEqual(rows['000660.KS']['metricAsOf'],FRIDAY)
        self.assertNotIn(999.,rows['000660.KS']['sc'])
        self.assertIsNotNone(rows['000660.KS']['mcapUSD'])
        self.assertTrue(rows['000660.KS']['mcapEstimated'])
        self.assertEqual(sum(c['mcapLocal'] is not None for c in D['companies']),42)
        self.assertEqual(mk['daily'],before['daily'])

    def test_completed_metrics_never_trim_other_markets_to_oldest_date(self):
        data,mk=complete_dataset();c=next(c for c in data['companies'] if c['mkt']=='美股')
        r=mk['daily'][c['sym']];r['bars']=r['bars'][:-1];r['asOf']=r['bars'][-1][0]
        D=build.assemble(data,mk,mk,NOW)[0]
        self.assertEqual(D['meta']['asOfByMarket']['A股'],[FRIDAY])
        self.assertIn('2026-10-15',D['meta']['asOfByMarket']['美股'])
        self.assertNotIn('mixed_or_missing_market_dates_need_label_approval',D['meta']['blockers'])
        self.assertEqual(D['meta']['snapshot']['policy'],'latest-quote-and-market-completed-daily')

    def test_older_quote_does_not_roll_back_newer_completed_price(self):
        data,mk=complete_dataset();c=data['companies'][0]
        mk['quote'][c['sym']].update(regularMarketPrice=999.,regularMarketTime=epoch('2026-10-15',ZONES[c['mkt']],15))
        D=build.assemble(data,mk,mk,NOW)[0];r=D['companies'][0]
        self.assertEqual(r['priceAsOf'],FRIDAY)
        self.assertEqual(r['price'],mk['daily'][c['sym']]['bars'][-1][1])
        self.assertEqual(r['provenance']['valuation']['asOf'],'2026-10-15')

    def test_unknown_quote_state_remains_unknown_and_partial(self):
        data,mk=complete_dataset();c=data['companies'][0];mk['quote'][c['sym']]['marketState']=None
        D=build.assemble(data,mk,mk,NOW)[0];r=D['companies'][0]
        self.assertIsNotNone(r['mcapUSD']);self.assertEqual(r['provenance']['valuation']['phase'],'unknown')
        self.assertTrue(any(x['symbol']==c['sym'] and x.get('metric')=='PE' and x['status']=='partial' for x in D['meta']['coverage']))
        self.assertFalse(D['meta']['coverageComplete'])

    def test_quote_freshness_currency_and_future_observation_still_fail(self):
        data,mk=complete_dataset();c=data['companies'][0];q=mk['quote'][c['sym']]
        for changes in ({'receivedAt':'2020-01-01T00:00:00+00:00'},{'currency':'BAD'},{'regularMarketTime':(NOW+dt.timedelta(hours=1)).timestamp()}):
            with self.subTest(changes=changes):
                self.assertFalse(latest.select_quote({**q,**changes},FRIDAY,c['mkt'],c['cur'],NOW)[0])

    def test_fx_estimate_is_explicit_and_rejects_future_undated_or_too_old(self):
        r=historical_fx('CNY',receivedAt=MONDAY.isoformat())
        v=latest.select_fx(r,'CNY','2026-10-19',MONDAY)
        self.assertTrue(v['estimated']);self.assertEqual(v['dateGapDays'],3)
        self.assertEqual(v['asOf'],FRIDAY)
        self.assertIsNone(latest.select_fx(r,'CNY','2026-10-15',MONDAY))
        self.assertIsNone(latest.select_fx(r,'CNY','2026-10-23',MONDAY))
        self.assertIsNone(latest.select_fx({'value':7,'asOf':FRIDAY},'CNY',FRIDAY,MONDAY))

    def test_missing_fx_does_not_destroy_native_market_cap(self):
        data,mk=complete_dataset();mk['fx']={};D=build.assemble(data,mk,mk,NOW)[0]
        r=next(c for c in D['companies'] if c['cur']=='CNY')
        self.assertIsNone(r['mcapUSD']);self.assertGreater(r['mcapLocal'],0)

    def test_negative_eps_and_missing_eps_are_distinct_without_inventing_pe(self):
        data,mk=complete_dataset()
        for sym,eps in [('LITE',-92.96),('000660.KS',None)]:mk['quote'][sym].update(trailingPE=None,epsTrailingTwelveMonths=eps)
        D=build.assemble(data,mk,mk,NOW)[0];rows={r['sym']:r for r in D['companies']}
        self.assertEqual(rows['LITE']['provenance']['valuation']['peStatus'],'not_meaningful')
        self.assertEqual(rows['000660.KS']['provenance']['valuation']['peStatus'],'missing')
        for sym in ('LITE','000660.KS'):self.assertIsNone(rows[sym]['pe'])
        self.assertTrue(any(r['symbol']=='LITE' and r.get('metric')=='PE' and r['status']=='not_applicable' and r['evidence']['epsTrailingTwelveMonths']==-92.96 for r in D['meta']['coverage']))

    def test_unknown_index_phase_is_visible_partial_but_stale_value_is_blocked(self):
        data,mk=complete_dataset();sym=data['config']['indices'][0]['symbol'];mk['index'][sym]['phase']='unknown'
        D=build.assemble(data,mk,mk,NOW)[0]
        self.assertEqual(len(D['indices']),8)
        self.assertEqual(next(r for r in D['meta']['coverage'] if r['kind']=='index' and r['symbol']==sym)['status'],'partial')
        mk['index'][sym]['date']='2020-01-01';D=build.assemble(data,mk,mk,NOW)[0]
        self.assertEqual(len(D['indices']),7);self.assertIn('index_observation_missing_or_stale',D['meta']['blockers'])

    def test_ratio_aligns_common_daily_date_not_equity_date_or_collection_time(self):
        a=monthly_record('2026-10-16');b=monthly_record('2026-10-15',True)
        a['dailyObservations']=[['2026-10-15',90.],['2026-10-16',100.]]
        aligned=latest.comparable_ratio(a,b,NOW)
        self.assertEqual(aligned[0],'2026-10-15');self.assertEqual(aligned[1][-1],['2026-10',90.])
        data,mk=complete_dataset();mk['ratio']={'cyb':a,'hl':b};D=build.assemble(data,mk,mk,NOW)[0]
        self.assertEqual(D['ratio']['asOf'],'2026-10-15');self.assertFalse(D['ratio']['simultaneousObservationProven'])
        self.assertEqual(D['ratio']['completedMonths'],120)
        self.assertEqual(D['ratio']['n120'],0)

    def test_saved_tencent_metadata_proves_hkd_only_not_state_or_timezone(self):
        e=json.loads((ROOT/'audit/latest-market-2026-10-19/targeted-source-evidence.json').read_text())['tencent']
        for code,expected in [('hk00522','HKD'),('sh688498',None)]:
            v=e[code];qt=['']*v['qtLength']
            for k,x in v['quoteFields'].items():qt[int(k)]=x
            result=quotes.tencent_metadata({'qt':{code:qt}},code)
            self.assertEqual(result['currency'],expected);self.assertEqual(result['phase'],'unknown');self.assertIsNone(result['timezone'])
            self.assertEqual(result['providerLocalTime'],v['quoteFields']['30'])

    def test_ratio_rejects_invalid_future_duplicate_or_contradictory_daily_observations(self):
        a=monthly_record('2026-10-16');b=monthly_record('2026-10-16',True)
        for rows in ([['2026-10-16',999.]], [['2026-10-19',100.]], [['bad',100.]],
                     [['2026-10-15',100.],['2026-10-15',100.]], [['2026-10-15',float('nan')]]):
            with self.subTest(rows=rows):
                self.assertIsNone(latest.comparable_ratio({**a,'dailyObservations':rows},b,NOW))

    def test_cached_daily_metrics_remain_partial_without_downgrading_fresh_quote(self):
        data,mk=complete_dataset();fresh={**mk,'daily':{}}
        D=build.assemble(data,mk,fresh,NOW)[0]
        daily=[r for r in D['meta']['coverage'] if r.get('metric')=='daily']
        self.assertTrue(all(r['status']=='partial' and r['reason']=='cached_or_stale_daily' for r in daily))
        self.assertFalse(D['meta']['coverageComplete'])

    def test_real_saved_yahoo_single_points_are_not_history_after_range_changes(self):
        e=json.loads((ROOT/'audit/latest-market-2026-10-19/targeted-source-evidence.json').read_text())
        self.assertEqual(len(e['yahoo']),9)
        self.assertTrue(all(v['count']==1 for v in e['yahoo'].values()))
        self.assertEqual(e['deniedPaths'],[])

    def test_saved_actual_quote_coverage_and_no_new_network(self):
        e=json.loads((ROOT/'audit/latest-market-2026-10-19/valuation-fx-evidence.json').read_text())
        self.assertEqual(e['phaseTotalRequests'],29);self.assertEqual(len(e['quote']),42);self.assertEqual(len(e['fx']),6)
        self.assertEqual(sum(quotes.positive(q.get('regularMarketPrice')) for q in e['quote'].values()),42)
        self.assertEqual(sum(quotes.positive(q.get('marketCap')) for q in e['quote'].values()),42)
        self.assertEqual(sum(quotes.positive(q.get('trailingPE')) for q in e['quote'].values()),40)

    def test_collector_assembles_all_eight_indices_with_explicit_backups(self):
        data,mk=complete_dataset();gaps={'399006.SZ','000922.SS','HSTECH.HK'}
        def inspect(category,code,source,budget,fetch,quality):
            row={'category':category,'code':code,'source':source,'connection':True,'parse':True,'quality':True,'publicationGate':True,'requests':[]}
            if category.startswith('company-'):value=mk['daily'].get(code)
            elif category.startswith('index-'):
                value=None if source=='yahoo' and code in gaps else {**mk['index'][code],'src':source,'phase':'unknown' if source=='tencent' else 'closed'}
                if value is None:row.update(quality=False,publicationGate=False,failure='yahoo_index_insufficient_daily_bars')
            elif category=='fx':value=mk['fx'][code]
            else:value=mk['ratio'][code] if source=='tencent' else None
            return row,value
        sink={}
        with patch.object(probe,'inspect',side_effect=inspect),patch.object(probe.quotes,'yahoo_quotes',return_value=mk['quote']):
            _,_,_,gates=probe.collect(data,probe.Budget(),snapshot_sink=sink,snapshot_clock=NOW)
        self.assertEqual(len(sink['data']['indices']),8)
        self.assertEqual({c['symbol'] for c in sink['data']['indices'] if c['source']=='tencent'},gaps)
        self.assertFalse(gates['primaryOnlyAssembly'])
        self.assertTrue(all(c['phase']=='unknown' for c in sink['data']['indices'] if c['source']=='tencent'))

    def test_primary_refusal_never_tries_mirror(self):
        h=quotes.Http()
        with patch.object(h,'json',side_effect=quotes.AccessRefused('source_access_refused')) as request:
            with self.assertRaises(quotes.AccessRefused):h.yahoo('/v8/finance/chart/T')
        self.assertEqual(request.call_count,1)
        self.assertTrue(request.call_args.args[0].startswith('https://query1.finance.yahoo.com/'))

    def test_http_refusal_stops_later_quote_batches_on_same_path(self):
        h=quotes.Http();url='https://query1.finance.yahoo.com/v7/finance/quote'
        with patch.object(h.op,'open',side_effect=urllib.error.HTTPError(url,403,'denied',{},None)) as request:
            for batch in ('A','B'):
                with self.assertRaises(quotes.AccessRefused):h.get(url+'?symbols='+batch)
        self.assertEqual(request.call_count,1)

    def test_access_denial_is_attributed_only_to_dependent_metrics(self):
        daily={'category':'company-yahoo-daily','symbol':'LITE'}
        quote={'category':'quote-session'}
        item={'kind':'company','symbol':'LITE','metric':'PE'}
        self.assertFalse(probe.access_affects(item,daily))
        self.assertTrue(probe.access_affects(item,quote))
        self.assertFalse(probe.access_affects({**item,'metric':'r20'},quote))
        self.assertTrue(probe.access_affects({**item,'metric':'r20'},daily))
        self.assertFalse(probe.access_affects({**item,'metric':'financial'},quote))
        self.assertTrue(probe.access_affects({'kind':'ratio'}, {'category':'ratio-tencent','symbol':'cyb'}))

if __name__=='__main__':unittest.main()
