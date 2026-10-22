"""Offline Notion transport and export boundaries; only synthetic credentials."""
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
sys.path.insert(0, str(ROOT / 'radar/tools'))
import notion_source as source
import export_notion_fixtures as exporter

FIXTURES = ROOT / 'radar/tests/fixtures/notion_v3/notion'
CONTRACT = json.loads((ROOT / 'radar/data/notion_schema.json').read_text(encoding='utf-8'))
STAMP = '2026-10-21T18:15:00+08:00'
SYNTHETIC_TOKEN = 'ntn_SYNTHETIC_SOURCE_TEST_ONLY'


class FixtureTransport:
    def __init__(self, change=None):
        self.index = json.loads((FIXTURES / 'index.json').read_text(encoding='utf-8'))
        self.change = change
        self.calls, self.sleeps, self.paces = [], [], 0

    def pace(self):
        self.paces += 1

    def request(self, method, path, json_body):
        self.calls.append((method, path, copy.deepcopy(json_body)))
        route = next((row for row in self.index['routes']
                      if row['method'] == method and row['path'] == path and
                      (method == 'GET' or row['start_cursor'] == json_body.get('start_cursor'))), None)
        if route is None:
            raise AssertionError('unexpected offline route')
        raw = (FIXTURES / route['file']).read_bytes()
        response = (200, {}, raw)
        return self.change(route, response) if self.change else response


class NotionSourceTests(unittest.TestCase):
    def fetch(self, transport=None, **kwargs):
        transport = transport or FixtureTransport()
        self.transport = transport
        return source.fetch_all(CONTRACT, kwargs.pop('settings', {}),
            token=kwargs.pop('token', SYNTHETIC_TOKEN), transport=transport,
            sleep=transport.sleeps.append, pace=transport.pace, fixed_clock=STAMP, **kwargs)

    def test_complete_serial_read_has_thirteen_exact_requests(self):
        result = self.fetch()
        self.assertEqual(result['requests'], 13)
        self.assertEqual(result['request_stats'], {'total': 13, 'GET': 6, 'POST': 7, 'retries': 0})
        self.assertEqual(self.transport.paces, 13)
        self.assertEqual(self.transport.sleeps, [])
        self.assertEqual(list(result['tables']), list(source.TABLE_ORDER))
        self.assertEqual([len(t['pages']) for t in result['tables'].values()], [15, 16, 42, 42, 2, 1])
        self.assertTrue(all(t['ok'] and t['fetchedAt'] == STAMP for t in result['tables'].values()))
        for method, _, body in self.transport.calls:
            if method == 'POST':
                self.assertEqual(body['page_size'], 100)
                self.assertLessEqual(set(body), {'page_size', 'start_cursor'})

    def test_missing_token_never_invokes_transport(self):
        result = self.fetch(token='')
        self.assertEqual(result['requests'], 0)
        self.assertEqual(result['request_stats'], {'total': 0, 'GET': 0, 'POST': 0, 'retries': 0})
        self.assertEqual(self.transport.calls, [])
        self.assertTrue(result['stopped_all'])
        self.assertEqual({t['error']['code'] for t in result['tables'].values()}, {'notion_token_missing'})

    def test_auth_failure_discards_all_previously_fetched_tables(self):
        for status, code in ((401, 'notion_unauthorized'), (403, 'notion_forbidden')):
            with self.subTest(status=status):
                def change(route, response):
                    if route['file'] == 'query_weekly.json':
                        return status, {'Authorization': SYNTHETIC_TOKEN}, json.dumps(
                            {'code': SYNTHETIC_TOKEN, 'message': SYNTHETIC_TOKEN}).encode()
                    return response
                result = self.fetch(FixtureTransport(change))
                self.assertTrue(result['stopped_all'])
                self.assertEqual({t['error']['code'] for t in result['tables'].values()}, {code})
                self.assertTrue(all(not t['pages'] and not t['schema'] for t in result['tables'].values()))
                self.assertNotIn(SYNTHETIC_TOKEN, json.dumps(result))
                self.assertEqual(self.transport.sleeps, [])

    def test_http_failure_stays_local_and_error_text_is_discarded(self):
        def change(route, response):
            return (404, {}, b'{"code":"object_not_found","message":"private"}') if route['file'] == 'ds_weekly.json' else response
        result = self.fetch(FixtureTransport(change))
        self.assertEqual(result['requests'], 12)
        self.assertEqual(sum(t['ok'] for t in result['tables'].values()), 5)
        self.assertEqual(result['tables']['weekly']['error']['code'], 'notion_not_found')
        self.assertNotIn('private', json.dumps(result))

    def test_retry_counts_and_delays_are_bounded(self):
        for sequence, expected in (([429], [2]), ([502, 503], [1, 2]),
                                   ([429] * 4, [60, 60, 60]), ([None] * 4, [1, 2, 4])):
            with self.subTest(sequence=sequence):
                statuses = list(sequence)
                def change(route, response):
                    if route['file'] != 'query_weekly.json' or not statuses:
                        return response
                    status = statuses.pop(0)
                    if status is None:
                        raise TimeoutError(SYNTHETIC_TOKEN)
                    return status, {'Retry-After': '120' if len(sequence) == 4 else '2'}, b'not JSON'
                result = self.fetch(FixtureTransport(change))
                self.assertEqual(self.transport.sleeps, expected)
                self.assertEqual(result['requests'], 13 + min(3, len(sequence)))
                self.assertEqual(result['request_stats'], {
                    'total': result['requests'], 'GET': 6,
                    'POST': 7 + min(3, len(sequence)), 'retries': min(3, len(sequence))})
                self.assertNotIn(SYNTHETIC_TOKEN, json.dumps(result))

    def test_schema_check_skips_queries_and_ignores_extra_or_formula_columns(self):
        for operation in ('missing', 'type_changed', 'ignore_missing', 'extra'):
            with self.subTest(operation=operation):
                def change(route, response):
                    if route['file'] != 'ds_industries.json':
                        return response
                    schema = json.loads(response[2])
                    if operation == 'missing':
                        del schema['properties']['一句话逻辑']
                    elif operation == 'type_changed':
                        schema['properties']['一句话逻辑']['type'] = 'number'
                    elif operation == 'ignore_missing':
                        del schema['properties']['研判状态']
                    else:
                        schema['properties']['额外'] = {'type': 'rich_text'}
                    return 200, {}, json.dumps(schema).encode()
                result = self.fetch(FixtureTransport(change))
                if operation in ('missing', 'type_changed'):
                    error = result['tables']['industries']['error']
                    self.assertEqual(error['code'], 'notion_schema_changed')
                    self.assertEqual(error['detail']['change'], operation)
                    self.assertEqual(result['requests'], 12)
                else:
                    self.assertEqual(result['requests'], 13)
                    self.assertTrue(result['tables']['industries']['ok'])

    def test_bad_body_oversize_and_cursor_loop_fail_without_retry(self):
        for failure in ('json', 'oversize', 'cursor', 'shape'):
            with self.subTest(failure=failure):
                def change(route, response):
                    if failure == 'cursor' and route['file'] == 'query_companies_p2.json':
                        payload = json.loads(response[2])
                        payload.update(has_more=True, next_cursor=route['start_cursor'])
                        return 200, {}, json.dumps(payload).encode()
                    if route['file'] == 'query_weekly.json':
                        if failure == 'json': return 200, {}, b'<html>bad</html>'
                        if failure == 'oversize': return 200, {}, b' ' * 8388609
                        if failure == 'shape': return 200, {}, b'{"results":[],"has_more":false}'
                    return response
                result = self.fetch(FixtureTransport(change))
                table = 'companies' if failure == 'cursor' else 'weekly'
                expected = {'json': 'notion_bad_json', 'shape': 'notion_bad_json',
                            'cursor': 'notion_cursor_loop', 'oversize': 'notion_body_too_large'}[failure]
                self.assertEqual(result['tables'][table]['error']['code'], expected)
                self.assertEqual(self.transport.sleeps, [])

    def test_phase_deadline_prevents_subsequent_requests(self):
        elapsed = [0]
        def change(route, response):
            elapsed[0] = 180
            return response
        result = self.fetch(FixtureTransport(change), clock=lambda: elapsed[0])
        self.assertEqual(result['requests'], 1)
        self.assertEqual({t['error']['code'] for t in result['tables'].values()}, {'notion_timeout'})

    def test_page_cap_prevents_unbounded_pagination(self):
        result = self.fetch(settings={'max_pages_per_table': 1})
        self.assertEqual(result['tables']['companies']['error']['code'], 'notion_too_many_pages')
        self.assertEqual(result['requests'], 12)

    def test_response_cannot_echo_token_through_json_escapes(self):
        def change(route, response):
            if route['file'] == 'ds_industries.json':
                raw = response[2].replace(b'"object": "data_source"',
                    b'"echo": "' + ''.join('\\u%04x' % ord(c) for c in SYNTHETIC_TOKEN).encode() + b'", "object": "data_source"')
                return 200, {}, raw
            return response
        result = self.fetch(FixtureTransport(change))
        self.assertEqual(result['tables']['industries']['error']['code'], 'notion_bad_json')
        self.assertNotIn(SYNTHETIC_TOKEN, json.dumps(result))

    def test_urllib_streaming_aborts_after_limit_plus_one_and_rejects_other_origin(self):
        transport = source.UrllibTransport(SYNTHETIC_TOKEN, {**source.DEFAULTS, 'max_body_bytes': 16})
        stream = io.BytesIO(b'x' * 100)
        with self.assertRaises(source.NotionError) as raised:
            transport._read(stream)
        self.assertEqual(raised.exception.code, 'notion_body_too_large')
        self.assertEqual(stream.tell(), 17)
        with self.assertRaisesRegex(ValueError, 'invalid_notion_api_configuration'):
            self.fetch(settings={'api_base': 'https://example.invalid'})

    def test_export_allowlist_removes_user_identity_and_is_fixture_compatible(self):
        files = exporter.fixture_files(self.fetch(), CONTRACT, as_of=STAMP)
        serialized = json.dumps(files)
        for field in ('created_by', 'last_edited_by', 'request_id', 'public_url', 'annotations', 'email'):
            self.assertNotIn('"' + field + '"', serialized)
        self.assertEqual(set(files['index.json']['tables']), set(source.TABLE_ORDER))
        self.assertEqual(len(files['query_companies.json']['results']), 42)
        self.assertNotIn('expected', files)
        self.assertEqual(files, exporter.fixture_files(self.fetch(), CONTRACT, as_of=STAMP))


if __name__ == '__main__':
    unittest.main()
