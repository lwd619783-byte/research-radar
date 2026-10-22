"""Pure-view boundaries independent of the fixture acceptance suite."""
import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import research_view as view


class ResearchViewTests(unittest.TestCase):
    def test_iso_week_and_validity_are_calendar_boundaries(self):
        self.assertEqual(view.iso_week(dt.date(2021, 1, 1)), '2020-W53')
        props = {'研判理由': '依据订单变化', '来源': 'https://issuer.test/report',
                 '研判日期': '2026-10-10', '有效至': '2026-10-24'}
        self.assertEqual(view.judgment(props, '2026-10-24')['label'], 'ai')
        self.assertEqual(view.judgment(props, '2026-10-25')['reasons'], ['expired'])
        self.assertEqual(view.judgment(props, '2026-10-24', substituted=True)['reasons'], ['row_quarantined'])
        self.assertEqual(view.judgment(props, '2026-10-24', source_week='2026-W42')['reasons'], ['not_current_week'])

    def test_daily_templates_use_rounded_values_and_stable_ties(self):
        def phrase(values):
            indices = [{'symbol': str(n), 'name': f'指数{n}'} for n in range(len(values))]
            chips = [{'symbol': str(n), 'label': str(n), 'chg': value} for n, value in enumerate(values)]
            return view.daily_template(chips, indices)
        self.assertEqual(phrase([]), '')
        self.assertEqual(phrase([0.00001, -0.00001]), '主要指数基本持平')
        self.assertEqual(phrase([0, .01]), '主要指数未见下跌，指数1涨 1.00% 领涨')
        self.assertEqual(phrase([0, -.01]), '主要指数未见上涨，指数1跌 1.00% 领跌')
        self.assertEqual(phrase([.01, .01]), '主要指数集体上涨，指数0涨 1.00% 领涨')
        self.assertEqual(phrase([-.01, -.01]), '主要指数集体下跌，指数0跌 1.00% 领跌')
        self.assertEqual(phrase([.00005, -.00005]), '主要指数涨跌互现，指数0 +0.01%，指数1 −0.01%')

    def test_daily_chips_never_mix_trading_dates(self):
        indices = [{'symbol': '000001.SS', 'name': '上证指数', 'asOf': '2026-10-21', 'chg': .01},
                   {'symbol': 'HSTECH.HK', 'name': '恒生科技', 'asOf': '2026-10-20', 'chg': -.02}]
        result = view.daily_view([], indices, {'A股': '2026-10-21', '美股': '2026-10-20'}, [])
        self.assertEqual(len(result['A股']['chips']), 1)
        self.assertEqual(result['A股']['line'], '主要指数集体上涨，上证指数涨 1.00% 领涨')
        self.assertEqual(result['美股']['line'], '')

    def test_anchors_require_comparable_samples_and_do_not_rewrite_ai_scores(self):
        industries = [{'name': '测试', 's': [4, 2, 3, 4], 'judgment': {'label': 'ai'}}]
        companies = [{'ind': '测试', 'revg': x, 'financialRevenueComparable': True} for x in [.5, .6, .7]]
        companies.append({'ind': '测试', 'revg': 100, 'financialRevenueComparable': False})
        view.add_anchors(industries, [{'ind': '测试', 'tight': '🔴极紧'}], companies)
        self.assertEqual(industries[0]['judgment']['anchors']['业绩兑现'], {'anchor': 5, 'n': 3, 'medianRevenueYoYPct': 60.0})
        self.assertEqual(industries[0]['s'], [4, 2, 3, 4])
        self.assertEqual(len(industries[0]['judgment']['conflicts']), 2)
        view.add_anchors(industries, [], companies[:2])
        self.assertEqual(industries[0]['judgment']['anchors'], {})


if __name__ == '__main__':
    unittest.main()
