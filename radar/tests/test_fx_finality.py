"""Legacy producer cache and unfinished FX-day regressions; no network calls."""
import copy
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from test_integrity import NOW, build, quotes, historical_fx
from test_review_regressions import complete_dataset
from integrity import dated_fx, fresh_record

HERE=Path(__file__).resolve().parents[2]/'audit/truthfulness-2026-10-18'
FIX=HERE/'fixtures'

class FxFinalityTests(unittest.TestCase):
    def test_actual_legacy_producer_cache_is_rejected_even_same_day_and_fresh(self):
        legacy=json.loads((FIX/'legacy-fx-cache.json').read_text())['fx']['CNY']
        now=dt.datetime.fromisoformat(legacy['receivedAt'])+dt.timedelta(hours=1)
        self.assertEqual(set(legacy),{'value','src','asOf','schemaVersion','receivedAt'})
        self.assertEqual(legacy['schemaVersion'],2)
        self.assertGreater(legacy['value'],0)
        self.assertTrue(fresh_record(legacy,now,legacy['asOf']))
        self.assertIsNone(dated_fx(legacy,'CNY',legacy['asOf'],now))

    def test_failed_live_fx_fetch_cannot_revive_legacy_cache_or_hide_usd(self):
        legacy=json.loads((FIX/'legacy-fx-cache.json').read_text())['fx']['CNY']
        now=dt.datetime.fromisoformat(legacy['receivedAt'])+dt.timedelta(hours=24)
        day=legacy['asOf'];data,cache=complete_dataset()
        data['companies']=[next(c for c in data['companies'] if c['cur']==cur) for cur in ('CNY','USD')]
        data['config']['indices']=[]
        cache['fx']={'CNY':legacy}
        for c in data['companies']:
            d=cache['daily'][c['sym']];delta=dt.date.fromisoformat(day)-dt.date.fromisoformat(d['asOf'])
            for bar in d['bars']:bar[0]=(dt.date.fromisoformat(bar[0])+delta).isoformat()
            d.update(asOf=day,receivedAt=now.isoformat())
            cache['quote'][c['sym']].update(receivedAt=now.isoformat(),regularMarketTime=dt.datetime.fromisoformat(day).replace(hour=12,tzinfo=dt.UTC).timestamp())
        # Exercise actual fetch_all exception collection, merge fallback and assemble.
        with patch.object(quotes,'daily',side_effect=lambda h,s:cache['daily'][s]), \
             patch.object(quotes,'fx',side_effect=RuntimeError('simulated FX transport failure')) as fx, \
             patch.object(quotes,'monthly',side_effect=lambda *a:cache['ratio']['cyb']), \
             patch.object(quotes,'yahoo_quotes',return_value=cache['quote']):
            fresh,notes=build.fetch_all(data,cache,False)
        fx.assert_called_once();self.assertEqual(fresh['fx'],{})
        self.assertTrue(any('fx CNY 抓取失败' in n for n in notes))
        merged=build.merge(fresh,cache)
        self.assertIs(merged['fx']['CNY'],legacy)
        D,_,_=build.assemble(data,merged,fresh,now)
        nonusd,usd=D['companies']
        self.assertIsNone(nonusd['mcapUSD']);self.assertIsNone(nonusd['provenance']['valuation']['fx'])
        self.assertEqual(nonusd['provenance']['valuation']['marketCapStatus'],'missing_or_incompatible')
        self.assertNotIn('CNY',D['meta']['fx'])
        self.assertIsNotNone(usd['mcapUSD'])
        self.assertEqual(usd['provenance']['valuation']['fx']['src'],'USD-identity')

    def test_rates_without_finality_and_tampered_finality_are_rejected(self):
        for key in ('rates','finality','rateTimestamps','priceBasis','timezone','currency'):
            with self.subTest(key=key):
                r=historical_fx();r.pop(key)
                self.assertIsNone(dated_fx(r,'CNY','2026-10-16',NOW))
        for change in ({'end':True},{'start':1792281600},{'method':'matching-date-only'}):
            r=historical_fx();r['finality'].update(change)
            self.assertIsNone(dated_fx(r,'CNY','2026-10-16',NOW))

    def test_equities_closed_but_same_day_fx_bar_still_open_is_not_used(self):
        observed=dt.datetime(2026,10,16,20,tzinfo=dt.UTC)
        class Clock(dt.datetime):
            @classmethod
            def now(cls,tz=None):return observed.astimezone(tz) if tz else observed.replace(tzinfo=None)
        class Http:
            def yahoo(self,path):
                return {'chart':{'result':[{'meta':{'exchangeTimezoneName':'UTC','dataGranularity':'1d',
                    'currentTradingPeriod':{'regular':{'start':1792108800,'end':1792195200}},
                    'regularMarketPrice':99,'regularMarketTime':observed.timestamp()},
                    'timestamp':[1792022400,1792108800],
                    'indicators':{'quote':[{'close':[7.,99.]}]}}]}}
        with patch.object(quotes.dt,'datetime',Clock):r=quotes.fx(Http(),'CNY')
        self.assertEqual(r['asOf'],'2026-10-15')
        self.assertEqual(r['rates'],[['2026-10-15',7.,7.]])
        data,mk=complete_dataset();data['companies']=[next(c for c in data['companies'] if c['cur']=='CNY')]
        c=data['companies'][0]
        for group in ('daily','quote'):
            mk[group][c['sym']]['receivedAt']=observed.isoformat()
        self.assertEqual(mk['daily'][c['sym']]['phase'],'closed')
        mk['fx']['CNY']=r
        row=build.assemble(data,mk,mk,observed)[0]['companies'][0]
        self.assertIsNotNone(row['mcapUSD'])
        self.assertTrue(row['mcapEstimated'])
        self.assertEqual(row['provenance']['valuation']['fx']['value'],7.)
        self.assertEqual(row['provenance']['valuation']['fx']['asOf'],'2026-10-15')

    def test_waiting_cannot_turn_an_intraday_cached_value_into_a_close(self):
        r=historical_fx(receivedAt='2026-10-16T12:00:00+00:00')
        cache_now=dt.datetime(2026,10,17,4,tzinfo=dt.UTC)
        self.assertTrue(fresh_record(r,cache_now,'2026-10-16'))
        self.assertIsNone(dated_fx(r,'CNY','2026-10-16',cache_now))
        r['receivedAt']='2026-10-17T00:00:00+00:00'
        self.assertIsNotNone(dated_fx(r,'CNY','2026-10-16',NOW))

    def test_public_snapshot_hashes_and_current_42_company_coverage(self):
        manifest=json.loads((HERE/'fx-finality-capture.json').read_text())
        for filename,metadata in manifest['files'].items():
            raw=(FIX/filename).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),metadata['sha256'])
            if filename.endswith('.gz'):
                self.assertEqual(hashlib.sha256(gzip.decompress(raw)).hexdigest(),metadata['uncompressedSHA256'])
        old=json.loads(gzip.decompress((FIX/'market-original.json.gz').read_bytes()))
        self.assertEqual(len(old['daily']),42)
        self.assertTrue(all(r.get('rates') for r in old['fx'].values()))
        mk=json.loads(gzip.decompress((FIX/'market-finality.json.gz').read_bytes()))
        now=dt.datetime.fromisoformat(manifest['replayAt'])
        data,report=build.load_and_validate(build.RADAR,build.REPO,now.date());self.assertFalse(report.errors)
        D,stale,missing=build.assemble(data,mk,mk,now)
        self.assertFalse(stale);self.assertFalse(missing)
        # Immutable captured payloads predate the quote marketState contract.
        # Their hashes still verify; do not invent a closed state during replay.
        self.assertEqual(sum(c['mcapUSD'] is not None for c in D['companies']),42)
        self.assertEqual(sum(c['pe'] is not None for c in D['companies']),40)
        self.assertTrue(all(c['provenance']['valuation']['phase']=='unknown' for c in D['companies']))
        self.assertTrue(any(r['status']=='partial' for r in D['meta']['coverage']))
        self.assertEqual(sum(c['provenance']['financial']['status']=='verified' for c in D['companies']),40)
        self.assertEqual(sum(all(c[k] is not None for k in ('revg','earng','gm')) for c in D['companies']),38)  # Includes KBL H1; only 37 are complete within the original 40.
        self.assertEqual(sum(c['financialSignalEligible'] for c in D['companies']),36)

if __name__=='__main__':unittest.main()
