"""Dated market adapter evidence. All provider responses are local."""
from datetime import date, datetime
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

RADAR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RADAR / 'scripts'), str(RADAR / 'tools')]
from short_term_collector import market

DAY = date(2026, 11, 24)
PREVIOUS = date(2026, 11, 23)
END = int(datetime(2026,11,24,15,4,tzinfo=market.BJ).timestamp())


def quote(code, stamp='20261124150100', pct='2', amount='120000'):
    cells = [''] * 50
    for i,v in {1:'样本公司',2:code[2:],3:'10.20',4:'10',30:stamp,32:pct,37:amount,38:'5.0'}.items():
        cells[i] = v
    return f'v_{code}="' + '~'.join(cells) + '";'


class MarketHTTP:
    def __init__(self):
        self.stale = set()
        self.pages = []

    def get_text(self, url, encoding='utf-8'):
        if 'getharden/' in url:
            return json.dumps({'data':[{'date':str(DAY), 'reason':'测试板块', 'code':'000001'}]})
        codes = url.split('q=')[1].split(',')
        return '\n'.join(quote(sym,'20261123150100' if sym in self.stale else '20261124150100')
                         for sym in codes)

    def get_json(self, url, params):
        if url == market.CLIST:
            scope, page = params['fs'], params['pn']
            self.pages.append((scope,page))
            if scope == market.BEIJING:
                return {'data':{'diff':[{'f12':'920001','f26':20200101}],'total':1}}
            if scope == market.ALL_A:
                return {'data':{'diff':[{'f12':c,'f26':20200101} for c in ('000001','600000','920001')],
                                'total':3}}
            return {'data':{'total':2,'diff':[{'f12':'BK000' + str(page),'f14':'测试板块',
                        'f3':2*page,'f6':1.2e9,'f62':1e7,'f124':END}]}}
        if url == market.KLINE:
            base = [(d, i+10) for i,d in enumerate(('2026-11-17','2026-11-18','2026-11-19',
                                                        '2026-11-20','2026-11-23',str(DAY)))]
            if params['klt'] == 5:
                base = [(str(DAY)+' 10:30',17),(str(DAY)+' 13:30',18)]
            return {'data':{'code':params['secid'][3:], 'klines':[f'{d},11,{v},11' for d,v in base]}}
        if 'fqkline/get' in url:
            key = params['param'].split(',')[0]
            return {'data':{key:{'day':[['2026-08-03','10','10'],[str(DAY),'10','10.20']]}}}
        pool = [{'c':'000001','m':0,'n':'样本','zdp':2,'lbc':2}]
        if url.endswith('getTopicZBPool'):
            pool = []
        return {'data':{'qdate':params['date'],'tc':len(pool),'pool':pool}}


class FakeTdxClient:
    def get_security_count(self, market_id):
        return 2

    def get_security_list(self, market_id, start):
        codes = ('000001','399006') if market_id == 0 else ('600000','510300')
        return [{'code':codes[start]}]


class Frame(list):
    def to_dict(self, orient):
        return self


class Tdx:
    def __init__(self):
        self.client = FakeTdxClient()

    def bars(self, symbol, frequency, offset):
        return Frame([{'datetime':'2026-09-01 15:00','close':8},
                      {'datetime':str(PREVIOUS)+' 15:00','close':10},
                      {'datetime':str(DAY)+' 15:00','close':10.2}])

    def index_bars(self, symbol, frequency, offset):
        if frequency == 9:
            return self.bars(symbol, frequency, offset)
        return Frame([{'datetime':str(DAY)+' 10:30','close':10.1},
                      {'datetime':str(DAY)+' 10:35','close':15},
                      {'datetime':str(DAY)+' 15:00','close':10.2}])

    def close(self):
        pass


class MarketTests(unittest.TestCase):
    def test_three_market_codes_dated_quote_units_and_close_time(self):
        for code in ('430047','831961','872392','920001'):
            self.assertEqual(market.symbol(code),code+'.BJ')
        self.assertIsNone(market.symbol('510300'))
        ids = {'000001.SZ'}
        good = market.quote_rows(quote('sz000001'), ids, DAY)['000001.SZ']
        self.assertEqual(good['amount'],1_200_000_000)
        self.assertEqual(good['turnoverRate'],.05)
        self.assertEqual(good['pct'],.02)
        for stamp in ('20261124145900','20261123150100','invalid'):
            self.assertEqual(market.quote_rows(quote('sz000001',stamp),ids,DAY),{})
        self.assertEqual(market.quote_rows(quote('sh000001'),ids,DAY),{})

    def test_all_inventory_pages_or_no_sector_ranking(self):
        http = MarketHTTP()
        rows = market.clist(http,'board','f12')
        self.assertEqual([r['f12'] for r in rows],['BK0001','BK0002'])
        with patch.object(http,'get_json',return_value={'data':{'total':2,'diff':[{'f12':'BK0001'}]}}):
            with self.assertRaisesRegex(ValueError,'overlap'):
                market.clist(http,'board','f12')

    def test_full_pipeline_uses_three_universes_dated_klines_and_dated_pools(self):
        with patch.object(market,'open_tdx',return_value=Tdx()):
            raw = market.collect_market(DAY,{},MarketHTTP())
        self.assertTrue(raw['closeConfirmed'])
        self.assertTrue(raw['marketComplete'])
        self.assertEqual(raw['breadth']['turnoverCny'],3_600_000_000)
        self.assertEqual(raw['breadth']['up'],3)
        self.assertEqual(raw['breadth']['brokenRate'],0)
        self.assertEqual(raw['breadth']['yesterdayPremium'],.02)
        self.assertEqual(raw['previousLimitPool'][0]['height'],2)
        top = raw['concepts'][-1]
        self.assertEqual(top['spark'],[11,12,13,14,15])
        self.assertEqual(top['fiveDayReturn'],.5)
        self.assertEqual(set(p['time'] for p in raw['intraday']),{'10:30','13:30','15:00'})
        self.assertTrue(all(r.get('listedBefore') or r.get('listed') for r in raw['stocks']))
        self.assertIn('同花顺',top['reason'])

    def test_missing_exchange_quotes_never_leak_aggregate_counts(self):
        http = MarketHTTP()
        http.stale = {'bj920001'}
        with patch.object(market,'open_tdx',return_value=Tdx()):
            raw = market.collect_market(DAY,{'companies':[{'sym':'000001.SZ','mkt':'A股'}]},http)
        self.assertFalse(raw['marketComplete'])
        self.assertTrue(raw['closeConfirmed'])
        self.assertNotIn('up',raw['breadth'])
        self.assertNotIn('turnoverCny',raw['breadth'])
        self.assertIn('market_coverage_partial',raw['warnings'])
        self.assertEqual({r['code'] for r in raw['stocks']},{'000001.SZ','600000.SH'})

    def test_wrong_date_pool_rejected_even_with_explicit_requested_date(self):
        http = MarketHTTP()
        with patch.object(http,'get_json',return_value={'data':{'qdate':'20261124','tc':0,'pool':[]}}):
            with self.assertRaises(ValueError):
                market.limit_pool(http,'getTopicZTPool',PREVIOUS)
        with self.assertRaises(ValueError):
            market.boards(http,'concepts',PREVIOUS,lambda *args:[])

    def test_full_session_halt_counts_as_covered_but_does_not_enter_return_or_turnover(self):
        http = MarketHTTP()
        http.stale = {'bj920001'}
        read = http.get_json
        halted = {'SECURITY_CODE':'920001','SECUCODE':'920001.BJ','SUSPEND_START_TIME':'2026-11-24 09:30:00',
                  'SUSPEND_END_TIME':None,'SUSPEND_EXPIRE':'连续停牌','PREDICT_RESUME_DATE':None}
        def answer(url,params):
            if 'reportName' in params:
                self.assertIn("DATETIME='2026-11-24'", params['filter'])
                return {'result':{'pages':1, 'data':[halted]}}
            return read(url,params)
        with patch.object(market,'open_tdx',return_value=Tdx()), patch.object(http,'get_json',side_effect=answer):
            result = market.collect_market(DAY,{},http)
        self.assertTrue(result['marketComplete'])
        self.assertEqual(result['breadth']['up'],2)
        self.assertEqual(result['breadth']['turnoverCny'],2_400_000_000)
        self.assertNotIn('920001.BJ',[r['code'] for r in result['stocks']])
        for k,v in [('SUSPEND_START_TIME', '2026-11-24 13:00:00'),
                    ('SUSPEND_END_TIME', '2026-11-24 10:00:00'),
                    ('PREDICT_RESUME_DATE', '2026-11-24 00:00:00')]:
            with patch.dict(halted, {k:v}), patch.object(http,'get_json',side_effect=answer):
                self.assertEqual(market.suspension_list(http,DAY),set())

    def test_earlier_session_height_is_distinct_from_current_day_return(self):
        http = MarketHTTP()
        read = http.get_json
        def answer(url,params):
            if url.endswith('getTopicZTPool') and params['date'] == PREVIOUS.strftime('%Y%m%d'):
                return {'data':{'qdate':'20261124','tc':0,'pool':[]}}
            if url.endswith('getYesterdayZTPool'):
                return {'data':{'qdate':'20261124','tc':1,'pool':[dict(c='600000',n='样本',ylbc=3,zdp=-2)]}}
            return read(url,params)
        with patch.object(market,'open_tdx',return_value=Tdx()), patch.object(http,'get_json',side_effect=answer):
            result = market.collect_market(DAY,{},http)
        self.assertEqual(result['breadth']['yesterdayPremium'],-.02)
        self.assertEqual(result['previousLimitPool'],[dict(code='600000.SH',name='样本',height=3,date=str(PREVIOUS))])
        self.assertEqual(market.core_symbols({'companies':[{'sym':'600000.SS','mkt':'A股'}]}),{'600000.SH'})

    def test_full_outage_does_not_confirm_a_trading_session(self):
        with patch.object(market,'open_tdx',side_effect=OSError), \
                patch.object(MarketHTTP,'get_json',side_effect=TimeoutError), \
                patch.object(MarketHTTP,'get_text',side_effect=TimeoutError):
            raw = market.collect_market(DAY,{},MarketHTTP())
        self.assertFalse(raw['closeConfirmed'])
        self.assertFalse(raw['marketComplete'])
        self.assertEqual(raw['breadth'],{})
        self.assertIsNone(raw['limitPool'])
        self.assertIsNone(raw['previousLimitPool'])
