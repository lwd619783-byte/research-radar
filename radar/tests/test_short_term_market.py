"""Dated market adapter evidence. All provider responses are local."""
from datetime import date, datetime
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

RADAR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RADAR / 'scripts'), str(RADAR / 'tools')]
from short_term_collector import analytics, market

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
    def test_real_v3_spellings_and_outside_universe_core(self):
        radar = {'companies':[{'code':'SH688012','sym':'688012.SS','mkt':'A股'},
                              {'code':'not-an-id','sym':'002028.SZ','market':'A股'}]}
        with patch.object(market,'open_tdx',return_value=Tdx()):
            raw = market.collect_market(DAY,radar,MarketHTTP())
        self.assertEqual(market.core_symbols(radar),{'688012.SH','002028.SZ'})
        self.assertIsNone(market.symbol('SZ688012'))
        self.assertEqual((raw['coreExpected'],raw['coreQuotes']),(2,2))
        self.assertTrue(raw['marketComplete'])
        off = [r for r in raw['stocks'] if not r['inMarketUniverse']]
        self.assertEqual(len(off),2)
        self.assertTrue(all(r['spark'] for r in off))
        view = analytics.build_day(DAY, raw, radar, None)
        self.assertEqual(len(view['stocks']['market']['up']),3)
        self.assertEqual(len(view['stocks']['radar']['up']),2)

    def test_sina_recovery_uses_yuan_dates_and_prior_close(self):
        cells = ['0'] * 33
        for key,val in {0:'北京样本',2:'10.00',3:'10.05',9:'123456.78',30:str(DAY),31:'15:30:03'}.items():
            cells[key] = val
        http = MarketHTTP()
        def read(clock, day=DAY):
            cells[30:32] = [str(day),clock]
            return 'var hq_str_bj920001="' + ','.join(cells) + '";'
        with patch.object(http,'get_text',return_value=read('15:30:03')):
            row = market.sina_quotes(http,['920001.BJ'],DAY)['920001.BJ']
        self.assertEqual((row['amount'],row['pct'],row['turnoverRate']),(123456.78,.005,None))
        for payload in [read('15:30:03',PREVIOUS), read('14:59:59'), read('invalid'), 'var hq_str_bj920001="";']:
            with patch.object(http,'get_text',return_value=payload):
                self.assertEqual(market.sina_quotes(http,['920001.BJ'],DAY),{})
        get_text = http.get_text
        def partial(url, **kw):
            if 'qt.gtimg.cn' in url:
                return get_text(url, **kw).replace('v_bj920001=', 'v_missing=')
            if 'sinajs.cn' in url:
                return read('15:30:03')
            return get_text(url, **kw)
        with patch.object(http,'get_text',side_effect=partial), patch.object(market,'open_tdx',return_value=Tdx()):
            raw = market.collect_market(DAY,{},http)
        self.assertTrue(raw['marketComplete'])
        self.assertEqual(raw['breadth']['turnoverCny'], 2_400_000_000+123456.78)

    def test_sina_inventory_deduplicates_and_proves_sorted_beijing_prefix(self):
        http = MarketHTTP()
        syms = [f'bj92{n:04d}' for n in range(100)] + ['sh600000','sz000001']
        def answer(url,params,headers):
            if url.endswith('Count'):
                return str(len(syms))
            start = (params['page']-1)*100
            return [dict(symbol=s, code=s[2:]) for s in syms[start:start+100]]
        cache = {}
        with patch.object(http,'get_json',side_effect=answer) as read:
            self.assertEqual(len(market.sina_inventory(http,True,cache)),100)
            self.assertEqual(len(market.sina_inventory(http,cached_pages=cache)),102)
            self.assertEqual(read.call_count,4)
            syms[100] = syms[99]
            with self.assertRaises(ValueError):
                market.sina_inventory(http)

    def test_index_minute_fallback_requires_two_dates_and_does_not_invent_auction(self):
        payload = {'data':{'sh000001':{'data':{'date':'20261124','data':[
            '0930 10 10', '1030 10.01 20', '1330 9.99 30', '1500 10.1 40']},
            'qt':{'sh000001':['1','上证指数','000001','10.1','10']+['']*25+['20261124161000']}}}}
        http = MarketHTTP()
        with patch.object(http,'get_json',return_value=payload):
            pts = market.tencent_index_points(http,DAY,'上证指数','sh000001')
            self.assertEqual([p['time'] for p in pts],['10:30','13:30','15:00'])
            self.assertAlmostEqual(pts[-1]['pct'],.01)
            payload['data']['sh000001']['data']['date'] = '20261123'
            with self.assertRaises(ValueError):
                market.tencent_index_points(http,DAY,'上证指数','sh000001')
        with patch.object(market,'index_points',return_value=[]), patch.object(market,'open_tdx',return_value=Tdx()):
            self.assertIn('index_intraday_missing',market.collect_market(DAY,{},MarketHTTP())['warnings'])

    def test_shenwan_report_requires_exact_day_and_uses_prices_for_spark(self):
        http = MarketHTTP()
        def read(url,params):
            if url.endswith('timelines/'):
                return {'data':[dict(l1='801010',trading_date=str(DAY),trading_time='10:30:00',l8=16)]}
            dates = ['2026-11-17','2026-11-18','2026-11-19','2026-11-20','2026-11-23',str(DAY)]
            rows = [dict(swindexcode='801010',swindexname='农林牧渔',bargaindate=d,closeindex=10+i,markup=1.2)
                    for i,d in enumerate(dates) if params['start_date']<=d<=params['end_date']]
            return {'data':dict(count=len(rows),results=rows)}
        with patch.object(http,'get_json',side_effect=read):
            rows,points = market.sw_industries(http,DAY,lambda c,work,fallback:work())
        self.assertEqual(rows[0]['pct'],.012)
        self.assertEqual(rows[0]['spark'],[11,12,13,14,15])
        self.assertEqual(points[0]['time'],'10:30')
        self.assertIsNone(rows[0]['amount'])

    def test_public_sw_closes_must_reconcile_for_all_31_unique_industries(self):
        dates = ['2026-11-17','2026-11-18','2026-11-19','2026-11-20','2026-11-23',str(DAY)]
        summary = dict(as_of=str(DAY), source='AlphaOnly申万一级行业日度数据',
                       rows=[dict(industry_name=n, ret_1d=100/14, ret_5d=50) for n in market.SW_LEVEL_ONE])
        hist = dict(as_of=str(DAY), dates=dates, industries={n:dict(close=[10,11,12,13,14,15])
                                                              for n in market.SW_LEVEL_ONE})
        http = MarketHTTP()
        def read(url):
            if url.endswith('/industry-data.js'):
                return '// public daily result\nwindow.INDUSTRY_DATABASE = ' + json.dumps(summary) + ';'
            return 'window.INDUSTRY_GLDI_HISTORY=' + json.dumps(hist) + ';'
        with patch.object(http,'get_text',side_effect=read):
            rows, points = market.published_sw_industries(http, DAY)
            self.assertEqual((len(rows), points), (31, []))
            row = next(r for r in rows if r['name']=='国防军工')
            self.assertEqual((row['code'],row['spark'],row['amount']), ('SW801740',[11,12,13,14,15],None))
            for obj, change in [(summary, {'as_of':str(PREVIOUS)}),
                                (hist, {'dates':[str(PREVIOUS)]*6}),
                                (summary, {'rows':summary['rows'][:-1]}),
                                (summary, {'rows':[summary['rows'][0]]*31}),
                                (summary['rows'][0], {'ret_1d':0})]:
                with patch.dict(obj, change), self.assertRaises(ValueError):
                    market.published_sw_industries(http, DAY)

    def test_published_board_ranking_rejects_stale_pages_duplicate_and_unproven_detail(self):
        http = MarketHTTP()
        def page(n,stamp=DAY):
            return (f'<h2>概念板块行情一览</h2><span>当前数据日期更新于 <strong>{stamp}</strong> · 共 <strong>2</strong> 个板块</span>'
                    f'<tr><td data-label="概念"><a href="/bk/{n}.html">样本{n}</a></td><td data-label="涨跌幅">1.23%</td></tr>')
        def detail(n,stamp=DAY):
            return f'板块代码 BK{n:04d}.DC 最新交易日 {stamp} 当日涨跌幅 1.23%'
        for side, valid in [([page(1),page(2),detail(1),detail(2)],True),
                            ([page(1),page(2,PREVIOUS)],False),([page(1),page(1)],False),
                            ([page(1),page(2),detail(1,PREVIOUS)],False)]:
            with patch.object(http,'get_text',side_effect=side):
                if valid:
                    rows,_ = market.published_concepts(http,DAY)
                    self.assertEqual([r['code'] for r in rows],['BK0001','BK0002'])
                    self.assertTrue(all(r['amount'] is None for r in rows))
                else:
                    with self.assertRaises(ValueError):
                        market.published_concepts(http,DAY)

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
