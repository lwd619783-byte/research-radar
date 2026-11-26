"""Offline event-source payloads follow the published providers' field names and units."""
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

RADAR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RADAR / 'tools'), str(RADAR / 'scripts')]
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
    @staticmethod
    def notice(ident, title, stamp='2026-11-10 16:00', code='600001'):
        issued = datetime.fromisoformat(stamp).replace(tzinfo=events.BJ)
        return dict(announcementId=ident, announcementTitle=title, secCode=code, secName='甲公司',
                    announcementTime=issued.timestamp() * 1000,
                    adjunctUrl=f'finalpage/{issued.date()}/{ident}.PDF')

    def test_forward_window_uses_announced_dates_and_only_within_five_natural_days(self):
        sample = dict(when=datetime(2026, 11, 10, 16, tzinfo=events.BJ), ident='1225000001',
                      code='600001', name='甲公司')
        wording = ('减持期间：2026 年 11 月 25 日～2027 年 2 月 24 日。'
                   '拟减持起始日期为2026年11月29日，减持结束日期为2027年2月28日。'
                   '减持期间2026年11月24日至2027年2月23日。'
                   '减持期间2026年11月30日至2027年2月28日。')
        rows, has_dates = events._notice_windows(sample, wording, DAY, '减持')
        self.assertTrue(has_dates)
        self.assertEqual([x['title'] for x in rows], ['减持计划窗口'] * 2)
        self.assertIn('2026-11-25 至 2027-02-24', rows[0]['detail'])
        self.assertIn('披露日 2026-11-10，巨潮公告编号 1225000001', rows[0]['detail'])
        self.assertIn('2026-11-29', rows[1]['detail'])
        relative = '减持期间：自本公告披露之日起15个交易日后的3个月内。'
        for unproven in (relative, '前次减持期间：2026年11月25日至2027年2月24日。',
                         '本次拟减持数量不超过总股本1%。本报告期为2026年11月25日至2027年2月24日。'):
            self.assertEqual(events._notice_windows(sample, unproven, DAY, '减持'), ([], False))
        raw = '减持期间：自减持计划披露之日起15个交易日后的3个月内进行，即从2026年11月25日至2027年2月24日止。'
        self.assertEqual(len(events._notice_windows(sample, raw, DAY, '减持')[0]), 1)
        for word in ('公司股票将于2026年11月27日开市起复牌。', '公司股票自2026年11月27日开市起停牌。'):
            self.assertEqual(len(events._notice_windows(sample, word, DAY, '异常波动')[0]), 1)
        self.assertEqual(events._notice_windows(sample, '若公司股票于2026年11月27日开市起复牌，则另行公告。',
                                                DAY, '异常波动'), ([], False))

    def test_early_plan_suppressed_after_update_and_late_pass_fetches_only_today(self):
        plan = self.notice('1225000001', '股东减持计划的预披露公告')
        withdrawn = self.notice('1225000002', '提前终止减持计划的公告', '2026-11-24 18:20')
        still_valid = self.notice('1225000003', '股东减持计划预披露公告', code='600002')
        not_yet = self.notice('1225000004', '更正减持计划公告', '2026-11-24 20:30:01', '600002')
        relative = self.notice('1225000005', '股东拟减持股份公告', code='600003')
        halt = self.notice('1225000006', '股票交易异常波动暨停牌核查公告', '2026-11-23 19:00')

        def source(url, params, headers):
            rows = [withdrawn, not_yet, still_valid, plan, relative] if params['searchkey'] == '减持' else [halt]
            return dict(announcements=rows, totalAnnouncement=len(rows))

        def document(http, n):
            return {'1225000003':'减持期间：2026年11月29日至2027年2月28日。',
                    '1225000005':'计划自本公告披露之日起15个交易日后的3个月内减持。',
                    '1225000006':'公司股票将于2026年11月25日开市起停牌。'}[n['ident']]

        http = FakeSources()
        with patch.object(http, 'post_form_json', side_effect=source) as lists, patch.object(
                events, '_notice_pdf', side_effect=document) as pdf:
            items, warnings = events.collect_disclosure_risks(DAY, http)
            self.assertEqual(pdf.call_count, 3)
            self.assertEqual([x['title'] for x in items], ['减持计划窗口', '异常波动停牌安排', '减持计划变更公告'])
            self.assertIn('（600002）', items[0]['detail'])
            self.assertIn('（600001）', items[-1]['detail'])
            self.assertEqual(warnings, ['巨潮减持部分公告未核到明确计划日期'])
            pdf.reset_mock()
            lists.reset_mock()
            late, warnings = events.collect_disclosure_risks(DAY, http, recent_only=True)
            self.assertEqual(late, [items[-1]])
            self.assertEqual(warnings, [])
            pdf.assert_not_called()
            self.assertEqual([c.args[1]['seDate'] for c in lists.call_args_list], [f'{DAY}~{DAY}'] * 2)

    def test_pdf_failures_leave_verified_notice_and_reject_unrelated_attachments(self):
        http = FakeSources()
        for url in ('https://foreign.test/x.pdf', 'finalpage/2026-11-23/999.pdf'):
            with self.assertRaises(ValueError):
                events._notice_pdf(http, dict(ident='1225000001', path=url))
        notice = self.notice('1225000001', '股东减持计划预披露公告', '2026-11-24 18:00')
        def listed(url, params, headers):
            return dict(hasMore=False, announcements=[notice] if params['searchkey'] == '减持' else [])
        with patch.object(http, 'post_form_json', side_effect=listed), patch.object(
                events, '_notice_pdf', side_effect=ImportError):
            rows, warnings = events.collect_disclosure_risks(DAY, http)
        self.assertEqual([x['title'] for x in rows], ['减持公告'])
        self.assertIn('巨潮计划日期核对缺少本机 PDF 读取组件', warnings)

    def test_deadline_and_incomplete_listing_never_construct_a_future_window(self):
        http = FakeSources()
        notice = self.notice('1225000001', '股东减持计划预披露公告', '2026-11-24 18:00')
        def source(url, params, headers):
            return dict(announcements=[notice], totalAnnouncement=1) if params['searchkey'] == '减持' else dict(
                announcements=[], totalAnnouncement=0)
        with patch.object(http, 'post_form_json', side_effect=source), patch.object(
                events.time, 'monotonic', side_effect=[100, 281]), patch.object(events, '_notice_pdf') as read:
            items, warnings = events.collect_disclosure_risks(DAY, http)
            read.assert_not_called()
        self.assertEqual([r['title'] for r in items], ['减持公告'])
        self.assertEqual(warnings, ['巨潮减持原公告核对时限内未完成'])
        truncated = dict(announcements=[notice], totalAnnouncement=2)
        with patch.object(http, 'post_form_json', side_effect=[truncated, dict(announcements=[], totalAnnouncement=0)]), (
                patch.object(events, '_notice_pdf')) as read:
            items, warnings = events.collect_disclosure_risks(DAY, http)
            read.assert_not_called()
        self.assertEqual([r['title'] for r in items], ['减持公告'])
        self.assertEqual(warnings, ['巨潮减持公告分页未完整'])

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

    def test_batch_seats_match_only_same_stock_session_and_reason(self):
        http = FakeSources()
        main = http.reports['RPT_DAILYBILLBOARD_DETAILSNEW']
        base = main[0]
        main.extend([{**base, 'SECURITY_CODE': code, 'BILLBOARD_DEAL_AMT': amount,
                      'EXPLANATION': reason} for code, amount, reason in (
                          ('123283', 9e7, '日涨幅达到15%的前5只可转债'),
                          ('000002', 8e7, '连续三个交易日异动'),
                          ('000001', 1e4, '另一原因'), ('600410', 1e7, REASON))])
        for side in ('BUY', 'SELL'):
            http.reports['RPT_BILLBOARD_DAILYDETAILS' + side].extend([
                seat('沪股通专用', 40000, 10000, SECURITY_CODE='600410'),
                seat('旧数据', 9e8, 1e7, SECURITY_CODE='600410', TRADE_DATE='2026-11-23')])
        warnings = []
        summary = events.dragon(DAY, http, warnings)
        self.assertEqual(warnings, [])
        self.assertEqual(len(http.calls), 3)
        for _, params in http.calls[1:]:
            self.assertIn('(SECURITY_CODE in ("600410","000001"))', params['filter'])
            self.assertNotIn('123283', params['filter'])
        first, second = summary['items']
        self.assertIn('600410', first['stock'])
        self.assertEqual(first['seats'], '沪深股通 +3.0 万元')
        self.assertIn('000001', second['stock'])
        self.assertNotIn('3.0 万元', second['seats'].split('沪深股通')[-1])

    def test_missing_seat_report_keeps_dated_list_without_making_up_seats(self):
        http = FakeSources()
        del http.reports['RPT_BILLBOARD_DAILYDETAILSSELL']
        warnings = []
        items = events.dragon(DAY, http, warnings)['items']
        self.assertEqual(len(items), 1)
        self.assertIn('暂缺', items[0]['seats'])
        self.assertIn('龙虎榜部分席位明细暂缺', warnings)

    def test_cninfo_page_failure_preserves_verified_rows_and_warns(self):
        http = FakeSources()
        payload = http.post_form_json(events.CNINFO, {'searchkey': '异常波动'}, {})
        payload['totalAnnouncement'] = 32
        edge = datetime(2026, 11, 24, 20, 30, tzinfo=events.BJ)
        row = payload['announcements'][0]
        payload['announcements'] += [
            {**row}, None, {**row, 'announcementId': 'overflow', 'announcementTime': 1e30},
            {**row, 'announcementId': 'cutoff', 'announcementTime': edge.timestamp() * 1000},
            {**row, 'announcementId': 'later', 'announcementTime': edge.timestamp() * 1000 + 1}]
        warnings = []
        with patch.object(http, 'post_form_json', side_effect=[payload, TimeoutError()]) as read:
            mines = events.disclosures(DAY, http, '异常波动', warnings)
        self.assertEqual(len(mines), 2)
        self.assertEqual(warnings, ['巨潮异常波动公告分页未完整'])
        self.assertEqual([call.args[1]['pageNum'] for call in read.call_args_list], [1, 2])
        with patch.object(http, 'post_form_json', side_effect=TimeoutError), self.assertRaises(TimeoutError):
            events.disclosures(DAY, http, '异常波动', [])

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
