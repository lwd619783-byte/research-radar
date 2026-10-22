"""Offline Notion fixture transport, mutations, and assertion paths.

This module never reads a token from the process environment.  Its fake token is
an explicit test input; no request can escape the supplied fixture routes.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random
import re
import shutil

FIXTURES = Path(__file__).resolve().parent / 'fixtures/notion_v3'
CONTRACT = FIXTURES.parents[2] / 'data/notion_schema.json'
TEST_TOKEN = 'ntn_OFFLINE_FIXTURE_SENTINEL'
MISSING = object()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


class FixtureSet:
    """Each run has a private copy, including every response modified in-place."""
    def __init__(self, directory):
        self.directory = Path(directory)
        shutil.copytree(FIXTURES / 'notion', self.directory / 'notion')
        self.index = read_json(self.directory / 'notion/index.json')
        self.contract = read_json(CONTRACT)
        self.documents = {route['file']: read_json(self.directory / 'notion' / route['file'])
                          for route in self.index['routes']}
        self.http_rules = []
        self.env = {'NOTION_TOKEN': TEST_TOKEN}
        self.clock = self.index['as_of']

    def query_documents(self, table):
        path = '/v1/data_sources/' + self.index['tables'][table]['data_source_id'] + '/query'
        return [self.documents[route['file']] for route in self.index['routes']
                if route['method'] == 'POST' and route['path'] == path]

    def rows(self, table):
        return [row for document in self.query_documents(table) for row in document['results']
                if row.get('object') == 'page']

    def row(self, table, key):
        prop = {'financials': '记录', 'daily': '标题'}.get(table, self.contract['tables'][table]['key'])
        matches = [row for row in self.rows(table) if self.plain(row['properties'][prop]) == key]
        if len(matches) != 1:
            raise AssertionError(f'Fixture row must be unique: {table}/{key}: {len(matches)}')
        return matches[0]

    @staticmethod
    def plain(prop):
        kind = prop['type']
        if kind in ('title', 'rich_text'):
            return ''.join(part.get('plain_text', '') for part in prop[kind])
        return prop.get(kind)

    def property(self, table, name, value, kind=None):
        spec = self.contract['tables'][table]['properties'].get(name, {})
        kind = kind or spec['type']
        result = {'id': spec.get('api_id_hint', 'fixture'), 'type': kind}
        if kind in ('title', 'rich_text'):
            result[kind] = [] if value in ('', None) else [{
                'type': 'text', 'text': {'content': str(value), 'link': None},
                'plain_text': str(value), 'href': None, 'annotations': {}}]
        elif kind == 'relation':
            result[kind] = [{'id': self.row(spec['target'], key)['id']} for key in (value or [])]
        elif kind == 'select':
            result[kind] = None if value is None else {'id': 'fixture', 'name': value, 'color': 'default'}
        elif kind == 'date':
            result[kind] = None if value is None else {'start': value, 'end': None, 'time_zone': None}
        elif kind == 'checkbox':
            result[kind] = bool(value)
        elif kind == 'formula':
            result[kind] = {'type': 'string', 'string': value or ''}
        else:
            result[kind] = value
        return result

    def add_row(self, mutation):
        table = mutation['table']
        if mutation.get('copy_of'):
            row = copy.deepcopy(self.row(table, mutation['copy_of']))
        else:
            row = {'object': 'page', 'archived': False, 'in_trash': False,
                   'properties': {name: self.property(table, name, None)
                                  for name in self.contract['tables'][table]['properties']}}
        row.update(id=mutation['id'], created_time=mutation['created_time'],
                   last_edited_time=mutation['last_edited_time'])
        row['url'] = 'https://www.notion.so/' + row['id'].replace('-', '')
        for name, value in mutation.get('set', {}).items():
            row['properties'][name] = self.property(table, name, value)
        self.query_documents(table)[-1]['results'].append(row)

    def mutate(self, mutations):
        for mutation in mutations:
            op = mutation['op']
            table = mutation.get('table')
            if op in ('set', 'set_raw'):
                row = self.row(table, mutation['row'])
                row['properties'][mutation['prop']] = (copy.deepcopy(mutation['raw']) if op == 'set_raw'
                    else self.property(table, mutation['prop'], mutation['value']))
            elif op == 'add_row':
                self.add_row(mutation)
            elif op == 'add_many':
                def expand(value, n):
                    if isinstance(value, str):
                        return value.format(n=n)
                    if isinstance(value, list):
                        return [expand(part, n) for part in value]
                    return value
                for n in range(1, mutation['count'] + 1):
                    self.add_row({**mutation, 'id': f"00000000-0000-4000-8000-{mutation['id_start'] + n:012d}",
                                  'set': {k: expand(v, n) for k, v in mutation['pattern'].items()}})
            elif op == 'remove_row':
                row = self.row(table, mutation['row'])
                for document in self.query_documents(table):
                    document['results'] = [item for item in document['results'] if item is not row]
            elif op == 'page_attr':
                self.row(table, mutation['row'])[mutation['attr']] = mutation['value']
            elif op.startswith('schema_'):
                self.mutate_schema(mutation)
            elif op == 'http':
                self.http_rules.append({**copy.deepcopy(mutation), 'position': 0})
            elif op == 'inject_result':
                self.query_documents(table)[0]['results'].append({'object': mutation['object'], 'id': 'fixture-non-page'})
            elif op == 'cursor_loop':
                documents = self.query_documents(table)
                if len(documents) < 2:
                    raise AssertionError('cursor_loop requires a paginated fixture')
                documents[1]['has_more'] = True
                documents[1]['next_cursor'] = documents[0]['next_cursor']
            elif op == 'shuffle':
                rng = random.Random(mutation['seed'])
                for name in self.index['tables']:
                    for document in self.query_documents(name):
                        rng.shuffle(document['results'])
            elif op == 'env':
                for key in mutation.get('unset', []):
                    self.env.pop(key, None)
                self.env.update(mutation.get('set', {}))
            elif op == 'clock':
                self.clock = mutation['as_of']
            else:
                raise AssertionError(f'Unsupported mutation: {op}')
        for name, document in self.documents.items():
            (self.directory / 'notion' / name).write_bytes(canonical_bytes(document))

    def mutate_schema(self, mutation):
        table, name, op = mutation['table'], mutation['prop'], mutation['op']
        schema = self.documents['ds_' + table + '.json']['properties']
        rows = self.rows(table)
        if op == 'schema_rename':
            new = mutation['to']
            schema[new] = schema.pop(name)
            schema[new]['name'] = new
            for row in rows:
                row['properties'][new] = row['properties'].pop(name)
        elif op == 'schema_type':
            kind = mutation['to']
            old = schema[name]
            schema[name] = {'id': old['id'], 'name': name, 'type': kind, kind: {}}
            for row in rows:
                value = self.plain(row['properties'][name])
                row['properties'][name] = self.property(table, name, value, kind=kind)
        elif op == 'schema_remove_prop':
            schema.pop(name)
            for row in rows:
                row['properties'].pop(name, None)
        elif op == 'schema_add_prop':
            kind = mutation['type']
            schema[name] = {'id': 'fixture-extra', 'name': name, 'type': kind, kind: {}}
            for row in rows:
                row['properties'][name] = self.property(table, name, None, kind=kind)
        elif op == 'schema_add_option':
            kind = schema[name]['type']
            schema[name][kind]['options'].append({'id': 'fixture-extra', 'name': mutation['option'], 'color': 'default'})
        else:
            raise AssertionError(f'Unsupported schema mutation: {op}')


class FakeTransport:
    def __init__(self, fixtures):
        self.fixtures = fixtures
        self.requests = 0
        self.calls = []
        self.sleeps = []
        self.paces = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def pace(self, seconds=None):
        self.paces.append(seconds)

    def request(self, method, path, json_body=None):
        self.requests += 1
        body = json_body or {}
        routes = [route for route in self.fixtures.index['routes']
                  if route['method'] == method and route['path'] == path
                  and (method != 'POST' or route.get('start_cursor') == body.get('start_cursor'))]
        if len(routes) != 1:
            raise AssertionError(f'Unexpected offline request: {method} {path} {body}')
        if method == 'POST':
            expected = {'page_size': 100}
            if body.get('start_cursor') is not None:
                expected['start_cursor'] = body['start_cursor']
            if body != expected:
                raise AssertionError(f'Unexpected query fields: {body}')
        elif body:
            raise AssertionError('GET schema must not send a JSON request body')
        route = routes[0]
        table = next(name for name, spec in self.fixtures.index['tables'].items()
                     if spec['data_source_id'] in path)
        kind = 'schema' if method == 'GET' else 'query'
        self.calls.append({'method': method, 'path': path, 'body': copy.deepcopy(body), 'table': table, 'kind': kind})
        for rule in self.fixtures.http_rules:
            match = rule['match']
            if match.get('kind', 'any') not in ('any', kind):
                continue
            if 'table' in match and match['table'] != table:
                continue
            if 'start_cursor' in match and match['start_cursor'] != body.get('start_cursor'):
                continue
            position = rule['position']
            if position >= len(rule['responses']) and rule.get('then') == 'normal':
                continue
            response = rule['responses'][min(position, len(rule['responses']) - 1)]
            rule['position'] += 1
            if response.get('timeout'):
                raise TimeoutError('Offline fixture timeout')
            if 'body_bytes' in response:
                raw = b'x' * response['body_bytes']
            elif 'body_text' in response:
                raw = response['body_text'].encode('utf-8')
            else:
                raw = canonical_bytes(response.get('body', {}))
            return response.get('status', 200), response.get('headers', {}), raw
        return 200, {}, canonical_bytes(self.fixtures.documents[route['file']])


def path_value(root, path):
    """The fixture DSL, including singleton filters and wildcard projection."""
    if path == 'snapshot.sha256':
        return hashlib.sha256(root['snapshot'].encode('utf-8')).hexdigest()
    tokens = re.findall(r'([^.[\]]+)|\[([^\]]+)\]', path)
    def visit(value, position):
        if position == len(tokens):
            return value
        if value is MISSING:
            return MISSING
        name, bracket = tokens[position]
        if name:
            if not isinstance(value, dict):
                return MISSING
            return visit(value.get(name, MISSING), position + 1)
        if not isinstance(value, list):
            return MISSING
        if bracket == '*':
            return [visit(item, position + 1) for item in value]
        if '=' in bracket:
            key, expected = bracket.split('=', 1)
            selected = [item for item in value if isinstance(item, dict) and str(item.get(key, MISSING)) == expected]
            return visit(selected[0] if len(selected) == 1 else selected, position + 1)
        try:
            return visit(value[int(bracket)], position + 1)
        except IndexError:
            return MISSING
    return visit(root, 0)


FIN_KEYS = ('source_name', 'source_url', 'source_urls', 'period_end', 'published_at', 'entered_at', 'basis', 'currency',
            'accounting_basis', 'fiscal_year', 'fiscal_period', 'profit_metric', 'revenue_scope', 'profit_scope',
            'margin_scope', 'report_status', 'profit_comparison', 'derivation', 'calculation_note', 'review_note',
            'disclosure_state', 'conditions', 'evidence')


def project(data):
    industries = [{key: row[key] for key in ('name', 's', 'total', 'logic', 'signal', 'risk', 'reps', 'kb')}
                  for row in data['industries']]
    chokepoints = [{key: row[key] for key in ('name', 'ind', 'tight', 'seg', 'why', 'track')}
                   for row in data['chokepoints']]
    companies = []
    for company in data['companies']:
        row = {key: company[key] for key in ('id', 'name', 'code', 'sym', 'mkt', 'cur', 'role', 'ind', 'cp', 'view',
                    'flash', 'next', 'url', 'revg', 'earng', 'gm', 'period', 'financialPartial',
                    'financialRevenueComparable', 'financialSignalEligible')}
        row['earnings'] = {key: company['earnings'][key] for key in ('status', 'source_url', 'timezone', 'time_note')}
        financial = company['provenance']['financial']
        if financial is not None:
            row['financial'] = {key: financial[key] for key in FIN_KEYS}
        companies.append(row)
    weekly = data['meta']['weekly']
    return {'industries': sorted(industries, key=lambda x: x['name']),
            'chokepoints': sorted(chokepoints, key=lambda x: (x['ind'], x['name'])),
            'companies': sorted(companies, key=lambda x: x['id']),
            'weekly': {**{key: weekly[key] for key in ('focus', 'lead', 'calHint')}, 'week': weekly['sourceWeek']}}
