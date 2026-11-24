"""Deterministic raw observations, without accounts, HTTP or market gateways."""
from datetime import date
from pathlib import Path
import sys
import unittest

RADAR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RADAR / 'scripts'), str(RADAR / 'tools')]
from short_term_collector.analytics import build_day, dated_stock_quotes
from short_term_merge import normalize_history

MON = date(2026, 11, 23)
TUE = date(2026, 11, 24)
R = {'companies': [{'sym': '000002.SZ', 'mkt': 'A股', 'ind': '光互连'},
                   {'code': 'SH688001', 'market': 'A股', 'ind': '光互连'},
                   {'code': '000009', 'mkt': '港股', 'ind': '地产'}],
     'industries': [{'name': '光互连', 'total': 16}, {'name': '运输', 'total': 12}],
     'chokepoints': [{'name': '光模块', 'ind': '光互连'}]}


def quote(code, name, pct, **kwargs):
    return {'code': code, 'name': name, 'pct': pct, 'amount': 1e9, 'listed': '2026-01-01', **kwargs}


def observations(day=TUE):
    return {'date': day.isoformat(), 'marketComplete': True,
            'stocks': [quote('000001.SZ', '甲', .1, listed='2026-10-25'),
                       quote('000002.SZ', '乙', -.08, amount=999999999),
                       quote('000003.SZ', '*ST丙', .5), quote('000004.SZ', '丁退', -.7),
                       quote('000005.SZ', '戊', .2, listed='2026-10-26'),
                       quote('000006.SZ', '己', -.24, listed=None),
                       quote('000007.SZ', '庚', -.05, listed=None, listedBefore='2025-01-01'),
                       quote('000008.SZ', 'N辛', .4), quote('000009.SZ', '壬', .1, amount=1),
                       quote('688001.SH', '癸', .03, amount=4)],
            'industries': [quote('BK01', '光互连', .03, netFlow=-2e8, spark=[9,10,11,12,13,14]),
                           quote('BK02', '物流', -.03), quote('BK03', '日常消费', 0)],
            'concepts': [quote('GN01', '光模块新材料', -.01), quote('GN02', '运输', .02),
                         quote('GN03', '光电配件', .05, constituents=['000002','688001'])],
            'breadth': {'up': 2010, 'down': 2000, 'flat': 100, 'turnoverCny': 1000000000000,
                        'limitUp': 10, 'limitDown': 8, 'brokenRate': .2, 'yesterdayPremium': -.01},
            'limitPool': [{'code': '000001', 'name': '甲', 'height': 4},
                          {'code': '000003', 'name': '丙', 'height': 2}],
            'previousLimitPool': [{'code': '000001', 'name': '甲', 'height': 3},
                                  {'code': '000002', 'name': '乙', 'height': 2},
                                  {'code': '000003', 'name': '丙', 'height': 1}],
            'intraday': [{'date': day.isoformat(), 'time': '10:30', 'name': '上证指数', 'pct': .012},
                         {'date': '2026-10-01', 'time': '13:30', 'name': '不同时点', 'pct': -.5}]}


class ShortTermAnalyticsTests(unittest.TestCase):
    def test_filter_threshold_proof_exclusions_and_independent_core(self):
        day = build_day(TUE, observations(), R, None)
        market, core = day['stocks']['market'], day['stocks']['radar']
        self.assertEqual([r['name'] for r in market['up']], ['甲'])
        self.assertEqual([r['name'] for r in market['down']], ['庚'])
        self.assertEqual([r['name'] for r in core['down']], ['乙'])
        self.assertEqual([r['name'] for r in core['up']], ['癸'])
        self.assertEqual(market['up'][0]['turnover'], '10.00 亿')

    def test_ranking_limits_sorted_both_sides_and_spark(self):
        raw = observations()
        raw['stocks'] = [quote(f'{100+i:06d}.SZ', str(i), i/100) for i in range(-6,7)]
        day = build_day(TUE, raw, R, None)
        for side, expected in [('up', [.06,.05,.04,.03,.02]), ('down', [-.06,-.05,-.04,-.03,-.02])]:
            self.assertEqual([r['pct'] for r in day['stocks']['market'][side]], expected)
            self.assertEqual([r['rank'] for r in day['stocks']['market'][side]], [1,2,3,4,5])
        self.assertEqual(day['industries']['up'][0]['spark'], [10,11,12,13,14])
        self.assertEqual(day['industries']['up'][0]['netFlow'], '-2.00 亿')

    def test_board_match_core_member_majority_and_four_quadrants(self):
        day = build_day(TUE, observations(), R, None)
        matrix = {q['key']:[r['name'] for r in q['items']] for q in day['matrix']}
        self.assertEqual(matrix, {'q-res':['光电配件', '光互连'], 'q-dip':['光模块新材料'],
                                  'q-pulse':['运输'], 'q-kill':['物流']})
        self.assertIn('16/20', day['concepts']['down'][0]['radarLink'])
        self.assertIsNone(day['industries']['down'][0]['radarLink'])

    def test_cycle_uses_prior_cohort_identity_and_absence_is_not_zero(self):
        raw = observations()
        day = build_day(TUE, raw, R, None)
        self.assertEqual([t['rate'] for t in day['cycle']['tiers']], ['1/1 (100%)','0/1 (0%)','1/1 (100%)'])
        self.assertEqual(day['cycle']['activeStep'], 2)
        raw['previousLimitPool'] = None
        self.assertIsNone(build_day(TUE, raw, R, None)['cycle']['activeStep'])
        raw['previousLimitPool'] = [{'date': '2025-01-01', 'code':'000001', 'height':3}]
        self.assertFalse(build_day(TUE, raw, R, None)['cycle']['tiers'])

    def test_timeline_uses_only_exact_time_and_date_or_three_node_fallback(self):
        raw = observations()
        day = build_day(TUE, raw, R, None)
        self.assertEqual([t['time'] for t in day['timeline']], ['10:30','15:00','17:30','20:15'])
        self.assertIn('+1.20%', day['timeline'][0]['detail'])
        raw['intraday'] = None
        self.assertEqual([t['time'] for t in build_day(TUE, raw, R, None)['timeline']], ['15:00','17:30','20:15'])

    def test_anchors_pass_partial_fail_missing_data_and_changed_claim(self):
        monday = build_day(MON, observations(MON), R, None)
        raw = observations()
        raw['breadth'].update(turnoverCny=1.01e12, limitUp=3)
        raw['industries'][0]['pct'] = -.01
        raw['limitPool'][0]['height'] = 2
        result = build_day(TUE, raw, R, monday)
        self.assertEqual(result['breadth']['turnoverDelta'], '100.00 亿')
        self.assertEqual([r['status'] for r in result['yesterdayReconcile']['items']], ['pass','partial','fail'])
        monday['anchors'][0]['title'] = '人工改变观察事项'
        raw['breadth']['limitUp'] = None
        result = build_day(TUE, raw, R, monday)
        self.assertEqual([r['code'] for r in result['yesterdayReconcile']['items']], ['ANCHOR 03'])
        self.assertIn('ANCHOR 01、ANCHOR 02', result['yesterdayReconcile']['summary'])
        monday['date'] = '2026-11-20'
        result = build_day(TUE, raw, R, monday)
        self.assertEqual(result['breadth']['turnoverDelta'], '—')
        self.assertEqual(result['yesterdayReconcile']['items'], [])

    def test_missing_universe_no_false_global_counts_and_legacy_market_flag(self):
        raw = observations()
        raw.pop('marketComplete')
        result = build_day(TUE, raw, R, None)
        self.assertIsNone(result['breadth']['up'])
        self.assertIsNone(result['sentimentScore'])
        self.assertEqual(result['stocks']['market'], {'up': [], 'down': []})
        self.assertTrue(result['stocks']['radar']['down'])
        raw['universeComplete'] = True
        self.assertEqual(build_day(TUE, raw, R, None)['breadth']['up'],2010)

    def test_wrong_date_weekend_and_official_holiday_refused(self):
        for requested, raw in [(MON, observations()),(date(2026,11,22), observations(date(2026,11,22))),
                               (date(2026,10,1),observations(date(2026,10,1)))]:
            with self.subTest(requested=requested), self.assertRaises(ValueError):
                build_day(requested, raw, R, None)

    def test_wrong_dates_conflicting_and_repeated_stock_codes(self):
        raw = observations()
        a = quote('000002.SZ', '乙', -.08)
        raw['stocks'] = [a, {**a, 'code': 'SZ000002'},
                         quote('600001.BJ', '错市场', .3), quote('000003.SZ', '错日', .8, date='2026-11-23'),
                         quote('000004.SZ', '无效报价', float('nan')), quote('000005.SZ', '无效现价', .1, price=0)]
        usable, complete = dated_stock_quotes(raw,TUE)
        self.assertFalse(complete)
        self.assertEqual(usable, [a])
        self.assertEqual(dated_stock_quotes(raw, MON), ([], False))
        raw['stocks'].append({**a,'pct': .23})
        self.assertEqual(dated_stock_quotes(raw,TUE), ([], False))
        result = build_day(TUE, raw, R, None)
        self.assertFalse(result['stocks']['radar']['down'])
        self.assertIsNone(result['breadth']['up'])

    def test_day_with_dirty_text_passes_cloud_contract_and_drops_handles(self):
        raw = observations()
        raw['industries'][0]['reason'] = '买入 @角色；待核'
        day = build_day(TUE, raw, R, None)
        self.assertEqual(day['industries']['up'][0]['reason'],'介入 匿名用户；待查')
        history = {'schemaVersion':'4.0-short-term', 'generatedAt':'2026-11-24T20:30:00+08:00',
                   'days':[day], 'meta':{}, 'catalysts':[]}
        self.assertEqual(normalize_history(history)['days'],[day])


if __name__ == '__main__':
    unittest.main()
