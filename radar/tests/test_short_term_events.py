"""Offline event-source payloads follow the published providers' field names and units."""
from datetime import date
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from short_term_collector import events

DAY = date(2026, 11, 24)
REASON = '日换手率达到20%的前5只证券'
SEAT = dict(SECURITY_CODE='000001', TRADE_DATE=str(DAY), EXPLANATION=REASON)


def seat(name, buy, sell, dept='1', **extra):
    return {**SEAT, **extra, 'OPERATEDEPT_CODE': dept, 'OPERATEDEPT_NAME': name,
            'BUY': buy, 'SELL': sell, 'NET': buy - sell}


class FakeSources:
    def __init__(self):
        self.calls = []
        self.reports = {
            'RPT_DAILYBILLBOARD_DETAILSNEW': [{**SEAT, 'SECURITY_NAME_ABBR': '甲',
                                               'BILLBOARD_DEAL_AMT': 100_000, 'BILLBOARD_NET_AMT': 30_000}],
            'RPT_BILLBOARD_DAILYDETAILSBUY': [
                seat('机构专用', 30000, 0, '0'), seat('深股通专用', 20000, 0, '2'),
                seat('另一榜', 1e8, 0, EXPLANATION='三日异动')],
            'RPT_BILLBOARD_DAILYDETAILSSELL': [
                seat('机构专用', 30000, 0, '0'), seat('东方财富证券拉萨团结路营业部', 0, 20000, '3')],
            'RPT_LIFT_STAGE': [dict(FREE_DATE='2026-11-29', SECURITY_CODE='000001',
                                    SECURITY_NAME_ABBR='甲', LIFT_MARKET_CAP=10_000)],
            'RPT_CPH_FECALENDAR': [dict(START_DATE='2026-11-26', END_DATE='2026-11-27',
                FE_NAME='电网设备论坛', FE_TYPE='行业会议', CONTENT='新设备展示', STD_TYPE_CODE='1')],
        }

    def get_json(self, url, params):
        assert url == events.EM
        report = params['reportName']
        self.calls.append((report, params.copy()))
        return {'success': True, 'result': {'pages': 1, 'data': self.reports[report]}}

    def get_text(self, url, *, encoding, headers):
        assert url == events.THS and encoding == 'gb18030'
        return """投资日历<table class="tzrl"><tr><td rowspan="4">2026-11-26<br>星期四</td>
        <td><a>电网设备论坛将于11月26日举办</a></td><td>电力设备</td></tr>
        <tr><td colspan="2">同花顺点评</td></tr><tr><td>机器人大会</td><td>机器人</td></tr></table>"""

    def post_form_json(self, url, params, headers):
        assert url == events.CNINFO
        keyword = params['searchkey']
        def row(stamp, title, ident):
            return dict(announcementTime=stamp, announcementTitle=title,
                        secName='甲', announcementId=ident)
        return dict(hasMore=False, announcements=[
            row(1795449600000, f'<em>{keyword}</em>提示', 'id1'),
            row(1795449600000, '减持计划届满', 'id2'),
            row(1795363200000, f'{keyword}旧公告', 'id3')])


class EventTests(unittest.TestCase):
    def test_whole_pipeline_dedup_and_calibrated_stage(self):
        raw = dict(status=200, data=[
            dict(title='美国非农就业人数', pub_time='2026-11-27 20:30', star=5),
            dict(title='中国制造业PMI', pub_time='2027-01-08 09:00', star=3),
            dict(title='中国窗口以外', pub_time='2027-01-09 09:00', star=5),
            dict(title='美国已公布', pub_time='2026-11-24 12:00', star=3),
            dict(title='欧元区就业数据', pub_time='2026-11-27 20:30', star=5),
            dict(title='美国低重要度', pub_time='2026-11-27 20:30', star=2)])
        http = FakeSources()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'calendar.json'
            path.write_text(json.dumps(raw), encoding='utf-8')
            with patch.dict(os.environ, {'SHORT_TERM_JIN10_CALENDAR_FILE': str(path)}, clear=True):
                result = events.collect_events(DAY, {'industries': [
                    dict(name='电力设备', fiveDayReturn=.08)], 'concepts': []}, http)
        self.assertEqual(result['warnings'], [])
        lhb = result['dragonTiger']['items'][0]
        self.assertIn('机构 +3.0 万元', lhb['seats'])
        self.assertIn('沪深股通 +2.0 万元', lhb['seats'])
        self.assertIn('东财拉萨 -2.0 万元', lhb['seats'])
        self.assertNotIn('其他席位', lhb['seats'])
        result_events = {r['title']: r for r in result['events']}
        self.assertEqual(len(result_events), 4)
        self.assertEqual(result_events['电网设备论坛']['phaseTag'], '临近防兑现')
        self.assertEqual(result_events['电网设备论坛']['daysLeft'], 'T-2天')
        self.assertIn('+8.00%', result_events['电网设备论坛']['expectationNote'])
        self.assertIn('暂缺', result_events['机器人大会']['expectationNote'])
        self.assertEqual(result_events['中国制造业PMI']['daysLeft'], 'T-45天')
        self.assertEqual(result_events['美国非农就业人数']['phaseTag'], '宏观定调锚')
        self.assertEqual([m['title'] for m in result['mines']], ['大额解禁', '减持公告', '异常波动公告'])

    def test_unlock_value_units_and_window(self):
        http = FakeSources()
        sample = http.reports['RPT_LIFT_STAGE'][0]
        http.reports['RPT_LIFT_STAGE'] += [
            {**sample, 'FREE_DATE': '2026-11-30'}, {**sample, 'FREE_DATE': str(DAY)},
            {**sample, 'LIFT_MARKET_CAP': 9999.99}, {**sample, 'LIFT_MARKET_CAP': None}]
        mines = events.unlocks(DAY, http)
        self.assertEqual(len(mines), 1)
        self.assertIn('1.00 亿元', mines[0]['detail'])

    def test_five_per_side_and_anonymous_institution_multiplicity(self):
        buy = [seat('机构专用', 20000, 0, '0')] * 2
        buy += [seat(str(i), i, 0, str(i)) for i in range(1, 6)]
        sell = [seat('机构专用', 20000, 0, '0'), seat('深股通', 0, 10000)]
        desc = events.seat_summary(buy, sell)
        self.assertIn('机构 +4.0 万元', desc)
        buy = [seat(str(i), i * 10000, 0) for i in range(1, 7)]
        self.assertIn('其他席位 +20.0 万元', events.seat_summary(buy, sell))

    def test_one_source_fails_without_replacing_other_events(self):
        http = FakeSources()
        with patch.object(http, 'get_json', side_effect=TimeoutError), patch.dict(os.environ, {}, clear=True):
            result = events.collect_events(DAY, {}, http)
        self.assertEqual(result['dragonTiger']['items'], [])
        self.assertIn('龙虎榜暂缺', result['warnings'])
        self.assertIn('金十日历暂缺', result['warnings'])
        self.assertEqual(len(result['events']), 2)
        self.assertEqual(len(result['mines']), 2)

    def test_em_pagination_keeps_filter_and_discards_incomplete_table(self):
        http = FakeSources()
        pages = [
            {'result': {'pages': 2, 'data': [{'name': 'first'}]}},
            {'result': {'pages': 2, 'data': [{'name': 'second'}]}}]
        with patch.object(http, 'get_json', side_effect=pages) as call:
            rows = events.em_rows(http, 'RPT_LIFT_STAGE', 'cutoff', 'FREE_DATE')
        self.assertEqual([r['name'] for r in rows], ['first', 'second'])
        self.assertEqual(call.call_args_list[1].args[1]['pageNumber'], 2)
        self.assertEqual(call.call_args_list[1].args[1]['filter'], 'cutoff')

    def test_mcp_token_uses_official_calendar_only(self):
        async def fake_mcp(token):
            self.assertEqual(token, 'fixture')
            return dict(status=200, data=[dict(title='美国测试事件', star=5, pub_time='2026-11-27 21:00')])
        with patch.dict(os.environ, {'JIN10_MCP_TOKEN':'fixture'}, clear=True), patch.object(events, '_jin10_mcp', fake_mcp):
            rows = events.jin10_events(DAY, FakeSources())
        self.assertEqual([r['title'] for r in rows], ['美国测试事件'])
