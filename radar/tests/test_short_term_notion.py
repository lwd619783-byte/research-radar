"""Offline tests for optional V4 Notion calibration, including pagination rollback."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

RADAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR / 'scripts'))
from short_term_notion import apply_overrides
from short_term_merge import load_short_term

FIXTURE = RADAR / 'tests/fixtures/short_term_v4/sample_short_term_history.json'
LEDGER_ID = '10101010-abcd-1234-8888-101010101010'
EVENT_ID = '20202020-abcd-1234-8888-202020202020'
ENV = dict(NOTION_TOKEN='synthetic-offline-token', SHORT_TERM_LEDGER_DATA_SOURCE_ID=LEDGER_ID,
           SHORT_TERM_CATALYST_DATA_SOURCE_ID=EVENT_ID)


def page(values):
    properties = {}
    for name, (kind, item) in values.items():
        if kind in ('title', 'rich_text'):
            value = [{'plain_text': item}]
        elif kind == 'select':
            value = {'name': item}
        elif kind == 'date':
            value = {'start': item}
        else:
            value = item
        properties[name] = {'type': kind, kind: value}
    return {'object': 'page', 'properties': properties}


def response(rows, cursor=None):
    return 200, {}, json.dumps(dict(object='list', results=rows,
                                    has_more=cursor is not None, next_cursor=cursor)).encode()


class NotionOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = json.loads(FIXTURE.read_text(encoding='utf-8'))
        day = cls.history['days'][0]
        cls.ledger = {'交易日期': ('title', day['date']), '定调结论': ('rich_text', '台账校正'),
                      '散户情绪分': ('number', 0), '短线周期阶段': ('select', '冰点期'),
                      '明日锚点_1': ('rich_text', '量能观察'), '对账状态_1': ('select', 'fail'),
                      '对账实盘_1': ('rich_text', '收盘量能偏低')}
        cls.event = {'事件ID': ('title', cls.history['catalysts'][0]['id']),
                     '开始日期': ('date', day['date']), '日期窗口': ('rich_text', day['date']),
                     '星级': ('select', '5'), '类别': ('select', 'macro'),
                     '事件标题': ('rich_text', '修订事件'), '核心看点': ('rich_text', '政策口径'),
                     '映射方向': ('rich_text', '基建'), '阶段标签': ('rich_text', '公布日'),
                     '预期与兑现推演': ('rich_text', '观察量能变化')}

    def test_missing_configuration_never_contacts_notion(self):
        with patch('short_term_notion.UrllibTransport', side_effect=AssertionError):
            for env in ({}, {'NOTION_TOKEN': 'alone'}, {'SHORT_TERM_LEDGER_DATA_SOURCE_ID': LEDGER_ID}):
                self.assertIs(apply_overrides(self.history, environ=env), self.history)

    def test_both_tables_and_pagination_and_isolation(self):
        old = copy.deepcopy(self.history)
        disabled = page({**self.ledger, '停用': ('checkbox', True), '定调结论': ('rich_text', '停用行')})
        invalid = page({**self.ledger, '散户情绪分': ('number', 101)})
        wrong_date = page({**self.ledger, '交易日期': ('title', '2026-02-30')})
        transport = Mock()
        transport.request.side_effect = [response([page(self.ledger)], 'second'),
            response([disabled, invalid, wrong_date]), response([page(self.event)])]
        result = apply_overrides(self.history, environ=ENV, transport=transport)
        self.assertEqual(self.history, old)
        day = result['days'][0]
        self.assertEqual(day['headline'], '台账校正')
        self.assertEqual(day['ego']['score'], 0)
        self.assertEqual(day['cycle']['activeStep'], 0)
        self.assertEqual(day['anchors'][0]['title'], '量能观察')
        self.assertEqual(day['yesterdayReconcile']['items'][0]['status'], 'fail')
        hits = [x for x in result['catalysts'] if x['id'] == self.event['事件ID'][1]]
        self.assertEqual(len(hits), 1)
        self.assertEqual((hits[0]['daysLeft'], hits[0]['stars'], hits[0]['title']), ('T-0天', 5, '修订事件'))
        self.assertEqual(transport.request.call_args_list[1].args, ('POST',
            f'/v1/data_sources/{LEDGER_ID}/query', {'page_size': 100, 'start_cursor': 'second'}))

    def test_timeout_404_and_invalid_rows_preserve_snapshot(self):
        overlong = page({**self.event, '事件标题': ('rich_text', '长' * 81)})
        bad_type = page(self.event)
        bad_type['properties']['星级']['type'] = 'rich_text'
        for failure in (TimeoutError(), (404, {}, b''), (200, {}, b'[]')):
            transport = Mock()
            transport.request.side_effect = [response([page(self.ledger)], 'second'), failure,
                                             response([overlong, bad_type])]
            self.assertEqual(apply_overrides(self.history, environ=ENV, transport=transport), self.history)

    def test_failed_calendar_does_not_discard_valid_ledger(self):
        transport = Mock()
        transport.request.side_effect = [response([page(self.ledger)]), (404, {}, b'')]
        result = apply_overrides(self.history, environ=ENV, transport=transport)
        self.assertEqual(result['days'][0]['headline'], '台账校正')
        self.assertEqual(result['catalysts'], self.history['catalysts'])

    def test_unsafe_override_is_rejected_per_row_before_replacing_local_data(self):
        base = load_short_term(FIXTURE, environ={})
        today, prior = base['days'][:2]
        good_ledger = {name: self.ledger[name] for name in (
            '定调结论', '散户情绪分', '短线周期阶段')}
        good_ledger.update({'交易日期': ('title', prior['date']),
                            '定调结论': ('rich_text', '@样本，买入')})
        bad_ledger = {**self.ledger, '对账实盘_1': (
            'rich_text', 'https://example:synthetic@example.invalid/')}
        first_event, second_event = base['catalysts'][:2]
        bad_event = {**self.event, '事件ID': ('title', first_event['id']),
                     '核心看点': ('rich_text', 'https://example.invalid/?api_key=synthetic')}
        good_event = {**self.event, '事件ID': ('title', second_event['id'])}
        transport = Mock()
        transport.request.side_effect = [
            response([page(bad_ledger), page(good_ledger),
                      page({**bad_ledger, '交易日期': ('title', prior['date'])})]),
            response([page(bad_event), page(good_event)])]
        with patch('short_term_notion.UrllibTransport', return_value=transport):
            result = load_short_term(FIXTURE, environ=ENV)
        self.assertEqual([row['date'] for row in result['days']], [row['date'] for row in base['days']])
        self.assertEqual(result['days'][0], today)
        self.assertEqual(result['days'][1]['headline'], '匿名用户，介入')
        self.assertEqual(result['meta']['isStale'], base['meta']['isStale'])
        by_id = {event['id']: event for event in result['catalysts']}
        self.assertEqual(set(by_id), {event['id'] for event in base['catalysts']})
        self.assertEqual(by_id[first_event['id']], first_event)
        self.assertEqual(by_id[second_event['id']]['title'], '修订事件')

    def test_sparse_anchor_is_idempotent_across_collect_and_build(self):
        history = copy.deepcopy(self.history)
        history['days'][0]['anchors'] = []
        ledger = self.ledger.copy()
        ledger['明日锚点_3'] = ledger.pop('明日锚点_1')
        transport = Mock()
        transport.request.side_effect = [response([page(ledger)]), response([])] * 2
        once = apply_overrides(history, environ=ENV, transport=transport)
        twice = apply_overrides(once, environ=ENV, transport=transport)
        self.assertEqual(twice, once)
        self.assertEqual([a['code'] for a in twice['days'][0]['anchors']], ['ANCHOR 03'])

    def test_sparse_reconcile_uses_actual_identifier_and_manual_evidence(self):
        history = copy.deepcopy(self.history)
        today, prior = history['days'][:2]
        today['yesterdayReconcile']['items'] = today['yesterdayReconcile']['items'][2:]
        prior['anchors'] = prior['anchors'][1:]
        ledger = {**self.ledger, '对账状态_2': ('select', 'partial'), '对账实盘_2': ('rich_text','上一交易日第二项的收盘记录')}
        transport = Mock()
        transport.request.side_effect = [response([page(ledger)]), response([])]
        result = apply_overrides(history, environ=ENV, transport=transport)
        items = result['days'][0]['yesterdayReconcile']['items']
        self.assertEqual([i['code'][:9] for i in items], ['ANCHOR 02','ANCHOR 03'])
        self.assertEqual(items[0]['claim'], prior['anchors'][0]['title'])
        self.assertEqual(items[0]['status'], 'partial')
        self.assertEqual(items[1], today['yesterdayReconcile']['items'][0])

    def test_no_prior_claim_or_missing_manual_observation_never_creates_result(self):
        for prior_available in (False, True):
            with self.subTest(prior=prior_available):
                history = copy.deepcopy(self.history)
                history['days'][0]['yesterdayReconcile']['items'] = []
                row = self.ledger.copy()
                if prior_available:
                    row.pop('对账实盘_1')
                else:
                    # The last available day is Friday, not the expected Monday.
                    history['days'].pop(1)
                transport = Mock()
                transport.request.side_effect = [response([page(row)]), response([])]
                result = apply_overrides(history, environ=ENV, transport=transport)
                self.assertEqual(result['days'][0]['yesterdayReconcile']['items'], [])

    def test_prior_manual_change_invalidates_mismatched_automatic_claim(self):
        history = copy.deepcopy(self.history)
        prior = {**self.ledger, '交易日期': ('title', history['days'][1]['date']),
                 '明日锚点_1': ('rich_text','新观察项')}
        # The second pass applies the new prior title even if the next day's
        # correction arrived first from the remote pagination order.
        for has_today_entry in (False, True):
            rows = [page(self.ledger), page(prior)] if has_today_entry else [page(prior)]
            transport = Mock()
            transport.request.side_effect = [response(rows), response([])]
            result = apply_overrides(history, environ=ENV, transport=transport)
            rec = result['days'][0]['yesterdayReconcile']
            if has_today_entry:
                self.assertEqual(rec['items'][0]['claim'],'新观察项')
                self.assertEqual(rec['items'][0]['actual'],'收盘量能偏低')
            else:
                self.assertFalse(any(it['code'].startswith('ANCHOR 01') for it in rec['items']))
                self.assertIn('ANCHOR 01',rec['summary'])

    def test_echoed_token_never_enters_data(self):
        transport = Mock()
        echoed = page({**self.event, '事件标题': ('rich_text', ENV['NOTION_TOKEN'])})
        transport.request.side_effect = [response([]), response([echoed])]
        self.assertEqual(apply_overrides(self.history, environ=ENV, transport=transport), self.history)
