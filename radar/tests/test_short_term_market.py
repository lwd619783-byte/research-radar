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
                        'f3':7.14,'f6':1.2e9,'f62':1e7,'f124':END}]}}
        if url == market.KLINE:
            base = [(d, i+10) for i,d in enumerate(('2026-11-17','2026-11-18','2026-11-19',
                                                        '2026-11-20','2026-11-23',str(DAY)))]
            if params['klt'] == 5:
                base = [(str(DAY)+' 10:30',17),(str(DAY)+' 13:30',18),(str(DAY)+' 15:00',15)]
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

    def test_auction_requires_executed_target_minute_identity_and_close(self):
        http = MarketHTTP()
        data = dict(code='000001', market=1, name='上证指数', preClose=100)
        def bar(clock, price=101, volume=10, amount=1010, stamp=DAY):
            return f'{stamp} {clock},100,{price},102,100,{volume},{amount},101'
        close = bar('15:00')
        with patch.object(http,'get_json',return_value={'data':data}):
            def read(*lines):
                data['trends'] = list(lines)
                return market.em_session_points(http,'1.000001','上证指数',DAY)
            points = read(bar('09:25'),close)
            self.assertEqual([p['time'] for p in points],['09:25','15:00'])
            self.assertTrue(points[0]['auctionConfirmed'])
            self.assertAlmostEqual(points[0]['pct'],.01)
            with patch.dict(data,code='BK0001',market=90):
                board_points = market.em_session_points(http,'90.BK0001','样本',DAY,board=True)
            self.assertEqual([(p['source'],p['basis'],p['interval']) for p in board_points],
                             [('eastmoney_trends2','eastmoney_previous_close','opening_auction'),
                              ('eastmoney_trends2','eastmoney_previous_close','1m')])
            for row in [bar('09:30'),bar('09:25',volume=0),bar('09:25',amount=0),
                        bar('09:25',stamp=PREVIOUS),bar('09:25',price=0)]:
                self.assertEqual([p['time'] for p in read(row,close)],['15:00'])
            for lines in [(bar('09:25'),), (bar('09:25'),bar('15:00',price=-1)),
                          (bar('09:25'),bar('09:25'),close)]:
                with self.assertRaises(ValueError):
                    read(*lines)
            for typo in [dict(code='399006'),dict(market=0),dict(name='样本')]:
                with patch.dict(data,typo), self.assertRaises(ValueError):
                    read(bar('09:25'),close)

    def test_board_extremes_crosschecked_history_turnover_and_dated_flow(self):
        http = MarketHTTP()
        dates = ['2026-11-17','2026-11-18','2026-11-19','2026-11-20','2026-11-23',str(DAY)]
        closes = {'BK0001':99, 'BK0002':100, 'BK0003':101}
        def read(url,params):
            code = params['secid'][3:]
            close = closes[code]
            if url == market.KLINE:
                self.assertEqual(params['klt'],101)
                bars = [f'{d},100,{v},102,98,10,6060,2,{v-100}' for d,v in
                        zip(dates,[98,98.5,99,99.5,100,close])]
                return {'data':dict(code=code,klines=bars)}
            if 'trends2' in url:
                ticks = [f'{DAY} {t},100,{close},102,98,10,6060,100' for t in ('10:30','13:30','15:00')]
                return {'data':dict(code=code,market=90,preClose=100,trends=ticks)}
            return {'data':dict(code=code,klines=[f'{DAY},-1234,0,0,-1000,-234'])}
        rows = [dict(code=c,name=c,pct=(p-100)/100) for c,p in closes.items()]
        def attempt(_, callback, fallback=None):
            try:
                return callback()
            except (KeyError,ValueError,StopIteration):
                return fallback
        with patch.object(http,'get_json',side_effect=read):
            result,points = market.em_board_details(http,rows,DAY,attempt)
            self.assertEqual({p['code'] for p in points},{'BK0001','BK0003'})
            self.assertEqual({(p['source'],p['basis'],p['interval']) for p in points},
                             {('eastmoney_trends2','eastmoney_previous_close','1m')})
            self.assertEqual(len(points),6)
            self.assertEqual(result[0]['spark'],[98.5,99,99.5,100,99])
            self.assertAlmostEqual(result[-1]['fiveDayReturn'],101/98-1)
            self.assertTrue(all((r['amount'],r['netFlow'])==(6060,-1234) for r in result))
            mismatched = [dict(code='BK0001',name='错误收益',pct=.85)]
            changed,points = market.em_board_details(http,mismatched,DAY,attempt)
            self.assertNotIn('spark',changed[0])
            self.assertNotIn('amount',changed[0])
            self.assertEqual(points,[])
        for code,klines in [('BK9999',[f'{DAY},-10,0,0,-9,-1']),
                            ('BK0001',[f'{PREVIOUS},-10,0,0,-9,-1']),
                            ('BK0001',[f'{DAY},-10,0,0,20,100'])]:
            with patch.object(http,'get_json',return_value={'data':dict(code=code,klines=klines)}):
                with self.assertRaises(ValueError):
                    market.board_net_flow(http,'BK0001',DAY)

    def test_only_complete_dated_membership_and_quotes_prove_board_turnover(self):
        http = MarketHTTP()
        listing = (f'概念板块行情一览 当前数据日期更新于 {DAY} · 共 1 个板块'
                   '<tr><td data-label="概念"><a href="/bk/816.html">样本</a></td>'
                   '<td data-label="涨跌幅">1.23%</td></tr>')
        detail = f'板块代码 BK0816.DC 最新交易日 {DAY} 当日涨跌幅 1.23%'
        def table(count, stamp):
            return (f'<h2>样本板块股票</h2><div>行情日期 {stamp} · 按当日涨跌幅排序 · 共 {count} 只</div>'
                    '<tr><td data-label="股票名称 / 代码"><a href="/stock/000001/">样本 000001.SZ</a></td></tr>'
                    '<tr><td data-label="股票名称 / 代码"><a href="/stock/600000/">样本 600000.SH</a></td></tr>'
                    '<tr><td data-label="领涨股票"><a href="/stock/000002/">样本 000002.SZ</a></td></tr>')
        for count,stamp,complete in [(2,DAY,True),(3,DAY,False),(2,PREVIOUS,None)]:
            with patch.object(http,'get_text',side_effect=[listing,detail+table(count,stamp)]):
                rows,_ = market.published_concepts(http,DAY)
            row = rows[0]
            self.assertIs(row.get('constituentsComplete'),complete)
            if complete is not None:
                self.assertEqual(row['constituents'],['000001.SZ','600000.SH'])
            quotes = {'000001.SZ':dict(date=str(DAY),amount=1350)}
            market.constituent_turnover(rows,quotes,set(),DAY)
            self.assertIsNone(row['amount'])
            market.constituent_turnover(rows,quotes,{'600000.SH'},DAY)
            self.assertEqual(row['amount'],1350 if complete else None)

    def test_shenwan_report_requires_exact_day_and_uses_prices_for_spark(self):
        http = MarketHTTP()
        def read(url,params):
            if url.endswith('timelines/'):
                return {'data':[dict(l1='801010',trading_date=str(DAY),trading_time=t,l8=16)
                                for t in ('10:30:00','10:30:25','13:30:59')]}
            dates = ['2026-11-17','2026-11-18','2026-11-19','2026-11-20','2026-11-23',str(DAY)]
            rows = [dict(swindexcode='801010',swindexname='农林牧渔',bargaindate=d,closeindex=10+i,markup=1.2)
                    for i,d in enumerate(dates) if params['start_date']<=d<=params['end_date']]
            return {'data':dict(count=len(rows),results=rows)}
        with patch.object(http,'get_json',side_effect=read):
            rows,points = market.sw_industries(http,DAY,lambda c,work,fallback:work())
        self.assertEqual(rows[0]['pct'],.012)
        self.assertEqual(rows[0]['spark'],[11,12,13,14,15])
        self.assertEqual(points[0]['time'],'10:30')
        self.assertEqual(len(points),1)
        self.assertEqual((points[0]['source'],points[0]['basis'],points[0]['interval']),
                         ('shenwan_timelines','shenwan_daily_previous_close','point'))
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

    def test_public_sw_member_card_requires_dated_same_industry_complete_count(self):
        row = dict(name='银行',code='SW801780',pct=.0005)
        http = MarketHTTP()
        def page(count=1, stamp=DAY, code='801780', pct='+0.05'):
            return (f'<link rel="canonical" href="https://www.yyqyx.com/b/{code}.SI">'
                    f'银行 申万一级行业 {pct}% 主力净额 -10.14亿元 成分股 {count} 只 数据日 {stamp}'
                    '<h2 id="sec5">全部成分股（按代码）</h2>'
                    f'<p>共 {count} 只成分股，按代码顺序。</p><div class="tags">'
                    '<a class="tag" href="https://www.yyqyx.com/s/000001.SZ">样本</a></div>'
                    '<a class="tag" href="https://www.yyqyx.com/s/600000.SH">无关</a>')
        for count in [1,10]:
            with patch.object(http,'get_text',return_value=page(count)):
                result = market.sw_members(http,row,DAY)
            self.assertEqual(result['constituents'],['000001.SZ'])
            self.assertEqual(result['constituentsComplete'],count==1)
        for kwargs in [dict(stamp=PREVIOUS),dict(code='801080'),dict(count=0),dict(pct='+1.99')]:
            with patch.object(http,'get_text',return_value=page(**kwargs)), self.assertRaises(ValueError):
                market.sw_members(http,row,DAY)

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
        self.assertEqual({(p['source'],p['basis'],p['interval']) for p in raw['intraday'] if p.get('code')},
                         {('eastmoney_kline','eastmoney_unadjusted_daily_previous_close','5m')})
        self.assertTrue(all(r.get('listedBefore') or r.get('listed') for r in raw['stocks']))
        self.assertIn('同花顺',top['reason'])

    def test_single_board_retry_retains_other_panel_quotes_and_first_minute(self):
        index = dict(date=str(DAY),time='13:30',name='上证指数',pct=.02)
        old = dict(date=str(DAY),time='10:30',name='测试板块',code='BK0001',pct=.198)
        for panel,other,scope,warning in [('concepts','industries','m:90 t:3 f:!50','concept_boards_missing'),
                                         ('industries','concepts','m:90 t:2 f:!50','industry_boards_missing')]:
            with self.subTest(panel=panel):
                http = MarketHTTP()
                raw = {panel:[], other:[{'code':'历史已核行','date':str(DAY)}],
                       'stocks':[{'code':'000001.SZ','date':str(DAY),'amount':123}],
                       'date':str(DAY),'intraday':[index,old],'marketComplete':False,
                       'warnings':[warning,'auction_0925_missing','core_quotes_partial']}
                original = json.dumps(raw)
                revised = market.retry_missing_boards(DAY,raw,http)
                self.assertEqual(json.dumps(raw),original)
                self.assertEqual(http.pages,[(scope,1),(scope,2)])
                self.assertEqual([r['code'] for r in revised[panel]],['BK0001','BK0002'])
                self.assertEqual(revised[other],raw[other])
                self.assertEqual(revised['stocks'],raw['stocks'])
                self.assertFalse(revised['marketComplete'])
                self.assertEqual(revised['intraday'][:2],[index,old])
                self.assertEqual([p for p in revised['intraday'] if
                                  p.get('code')=='BK0001' and p['time']=='10:30'],[old])
                self.assertEqual(len(revised['intraday']),7)
                self.assertNotIn(warning,revised['warnings'])
                self.assertTrue({'auction_0925_missing','core_quotes_partial'} <= set(revised['warnings']))
                reread = market.retry_missing_boards(DAY,revised,http)
                self.assertEqual(reread,revised)
                self.assertEqual(len(http.pages),2)

    def test_board_retry_rejects_stale_close_and_never_changes_failed_panel(self):
        raw = dict(date=str(DAY),industries=[{'code':'SW801780'}],concepts=[],
                   intraday=[],warnings=['concept_boards_missing','board_flow_missing'])
        http = MarketHTTP()
        read = http.get_json
        def stale(url,params):
            if 'clist/get' in url:
                return {'data':{'total':1,'diff':[dict(f12='BK0001',f14='上日板块',
                                                         f3=2.5,f124=END-86400)]}}
            return read(url,params)
        with patch.object(http,'get_json',side_effect=stale) as calls:
            self.assertEqual(market.retry_missing_boards(PREVIOUS,raw,http),raw)
            calls.assert_not_called()
            revised = market.retry_missing_boards(DAY,raw,http)
        self.assertEqual(revised,raw)
        self.assertIsNot(revised,raw)
        self.assertEqual(calls.call_count,2)

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

    def test_final_directory_recovers_only_missing_quotes_with_core_first(self):
        for recover_all in (True,False):
            http = MarketHTTP()
            initial_json = http.get_json
            calls = []
            def directory(url,params):
                if url == market.CLIST and params['fs'] == market.ALL_A:
                    return {'data':{'total':4,'diff':[{'f12':c,'f26':20200101} for c in
                                                    ('000001','600000','920001','600002')]}}
                return initial_json(url,params)
            def read(url,**kwargs):
                if 'qt.gtimg.cn/q=' in url:
                    batch = url.split('q=')[1].split(',')
                    calls.append(batch)
                    if len(calls)==1:
                        return quote('bj920001')
                    return '\n'.join(quote(s,stamp='20261123150100' if
                                          s=='sz000001' else '20261124150100') for s in batch)
                if 'hq.sinajs.cn/list=' in url and len(calls)==3 and recover_all:
                    self.assertTrue(url.endswith('=sz000001'))
                    cells = ['0'] * 32
                    for i,v in {0:'有效补采',2:'10',3:'10.2',9:'1200000000',30:str(DAY),31:'15:03:01'}.items():
                        cells[i] = v
                    return 'var hq_str_sz000001="' + ','.join(cells) + '";'
                raise OSError()
            radar = {'companies':[{'code':'SH600000','mkt':'A股'}]}
            with (patch.object(market,'open_tdx',return_value=Tdx()),
                  patch.object(http,'get_text',side_effect=read),
                  patch.object(http,'get_json',side_effect=directory)):
                raw = market.collect_market(DAY,radar,http)
            self.assertEqual(calls,[['sz000001','sh600000','bj920001'],['sh600002'],['sh600000','sz000001']])
            self.assertEqual(raw['coreQuotes'],1)
            self.assertEqual(raw['marketComplete'],recover_all)
            self.assertEqual('up' in raw['breadth'],recover_all)
            self.assertEqual('market_coverage_partial' in raw['warnings'],not recover_all)
            if recover_all:
                self.assertEqual(raw['breadth']['turnoverCny'],4*1_200_000_000)
                self.assertTrue(all(r['date']==str(DAY) for r in raw['stocks']))
                self.assertIn('有效补采',{r['name'] for r in raw['stocks']})

    def test_missing_quotes_retry_skips_proven_halts_and_respects_budget(self):
        def run(budget, *, halts=('000001.SZ',), batch=40):
            http = MarketHTTP()
            calls = []
            def read(url,**kwargs):
                if 'qt.gtimg.cn/q=' in url:
                    calls.append(url.split('q=')[1].split(','))
                    return quote('bj920001') if len(calls)==1 else quote('sh600000')
                raise OSError()
            with (patch.object(market,'open_tdx',return_value=Tdx()),
                  patch.object(market,'suspension_list',return_value=set(halts)),
                  patch.object(market,'RECOVERY_BATCH_SIZE',batch),
                  patch.object(market,'RECOVERY_MAX_BATCHES',1),
                  patch.object(market,'RECOVERY_SECONDS',budget),
                  patch.object(http,'get_text',side_effect=read)):
                return market.collect_market(DAY,{},http), calls
        recovered,calls = run(150)
        self.assertEqual(calls[-1],['sh600000'])
        self.assertTrue(recovered['marketComplete'])
        self.assertEqual(recovered['breadth']['up'],2)
        expired,calls = run(0)
        self.assertEqual(len(calls),1)
        self.assertFalse(expired['marketComplete'])
        self.assertNotIn('turnoverCny',expired['breadth'])
        capped,calls = run(150,halts=(),batch=1)
        self.assertEqual(calls[1:],[['sz000001']])
        self.assertFalse(capped['marketComplete'])

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
