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

    def test_echoed_token_never_enters_data(self):
        transport = Mock()
        echoed = page({**self.event, '事件标题': ('rich_text', ENV['NOTION_TOKEN'])})
        transport.request.side_effect = [response([]), response([echoed])]
        self.assertEqual(apply_overrides(self.history, environ=ENV, transport=transport), self.history)
