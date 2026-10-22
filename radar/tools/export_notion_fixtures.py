"""Manual, read-only export to a NEW directory; never run by CI.

This exports API-shaped input files only. It never changes contract, cases, or
expected output files. User identity metadata is excluded by an explicit allowlist.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import tomllib

RADAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR / 'scripts'))
from notion_source import TABLE_ORDER, fetch_all


def _property(value):
    kind = value.get('type')
    result = {'type': kind}
    if isinstance(value.get('id'), str):
        result['id'] = value['id']
    content = value.get(kind)
    if kind in ('rich_text', 'title'):
        result[kind] = [{'type': 'text', 'plain_text': fragment.get('plain_text', ''),
                         'text': {'content': fragment.get('plain_text', ''), 'link': None}}
                        for fragment in content if isinstance(fragment, dict)]
    elif kind == 'relation':
        result[kind] = [{'id': row['id']} for row in content if isinstance(row, dict) and 'id' in row]
        if 'has_more' in value:
            result['has_more'] = value['has_more']
    elif kind == 'select':
        result[kind] = None if content is None else {'name': content.get('name')}
    elif kind == 'date':
        result[kind] = None if content is None else {key: content.get(key) for key in ('start', 'end', 'time_zone')}
    elif kind in ('number', 'url', 'checkbox'):
        result[kind] = content
    else:
        raise ValueError('unsupported_export_property')
    return result


def fixture_files(fetched, contract, *, as_of, seed=3):
    """Build only allowlisted JSON bodies; the caller performs atomic disk write."""
    if any(not fetched['tables'][name]['ok'] for name in TABLE_ORDER):
        raise ValueError('incomplete_export')
    index = dict(notion_version=contract['notion_version'], base_url='https://api.notion.com',
                 as_of=as_of, today=as_of[:10], tables={}, routes=[],
                 notes=['Read-only export; results shuffled; identity metadata excluded.',
                        'Review input differences before explicitly updating expected files.'])
    files = {}
    randomizer = random.Random(seed)
    for name in TABLE_ORDER:
        definition = contract['tables'][name]
        allowed = {key: prop for key, prop in definition['properties'].items() if prop['level'] != 'ignore'}
        table = fetched['tables'][name]
        properties = {}
        for key, prop in allowed.items():
            original = table['schema']['properties'][key]
            schema = dict(name=key, type=prop['type'])
            if isinstance(original.get('id'), str):
                schema['id'] = original['id']
            schema[prop['type']] = {}
            if prop['type'] == 'select':
                options = original.get('select', {}).get('options', [])
                schema['select'] = {'options': [{'name': row['name']} for row in options if 'name' in row]}
            properties[key] = schema
        source_id = definition['data_source_id']
        path = '/v1/data_sources/' + source_id
        schema_file = f'ds_{name}.json'
        files[schema_file] = dict(object='data_source', id=source_id, properties=properties)
        index['routes'].append(dict(method='GET', path=path, file=schema_file))
        pages = []
        for page in table['pages']:
            if page.get('in_trash') is True:
                continue
            clean = {key: page[key] for key in ('object', 'id', 'created_time', 'last_edited_time', 'in_trash') if key in page}
            clean['properties'] = {key: _property(value) for key, value in page['properties'].items() if key in allowed}
            pages.append(clean)
        randomizer.shuffle(pages)
        index['tables'][name] = dict(database_id=definition['database_id'],
                                     data_source_id=source_id, rows=len(pages))
        chunks = [pages[start:start + 100] for start in range(0, len(pages), 100)] or [[]]
        for offset, chunk in enumerate(chunks):
            filename = f'query_{name}.json' if len(chunks) == 1 else f'query_{name}_p{offset + 1}.json'
            cursor = None if offset == 0 else f'export-{name}-{offset}'
            next_cursor = f'export-{name}-{offset + 1}' if offset + 1 < len(chunks) else None
            files[filename] = dict(object='list', results=chunk, next_cursor=next_cursor,
                                   has_more=next_cursor is not None, type='page_or_data_source',
                                   page_or_data_source={})
            index['routes'].append(dict(method='POST', path=path + '/query',
                                         start_cursor=cursor, file=filename))
    files['index.json'] = index
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='new output directory for notion/*.json inputs')
    parser.add_argument('--contract', type=Path, default=RADAR / 'data/notion_schema.json')
    parser.add_argument('--config', type=Path, default=RADAR / 'data/config.toml')
    parser.add_argument('--seed', type=int, default=3)
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print('导出工具仅供手动运行，CI 不运行。', file=sys.stderr)
        return 2
    destination = args.out.resolve()
    if destination.exists():
        print('导出目录已存在；请使用新目录，不覆盖现有 fixtures。', file=sys.stderr)
        return 2
    try:
        contract = json.loads(args.contract.read_text(encoding='utf-8'))
        settings = tomllib.loads(args.config.read_text(encoding='utf-8'))
        clock = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
        # Only this explicitly invoked CLI entrypoint reads the runtime secret.
        token = os.environ.get('NOTION_TOKEN', '')
        fetched = fetch_all(contract, settings, token=token, fixed_clock=clock)
        failed = [name + ': ' + table['error']['code'] for name, table in fetched['tables'].items() if not table['ok']]
        if failed:
            print('导出未完成：' + '；'.join(failed), file=sys.stderr)
            return 2
        files = fixture_files(fetched, contract, as_of=clock.isoformat(), seed=args.seed)
        encoded = {name: json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
                   for name, value in files.items()}
        if token and any(token in body for body in encoded.values()):
            raise ValueError('sensitive_export_content')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.notion-export-', dir=destination.parent) as temporary:
            stage = Path(temporary) / 'notion'
            stage.mkdir()
            for name, body in encoded.items():
                (stage / name).write_text(body, encoding='utf-8', newline='\n')
            stage.rename(destination)
        print(f'已导出 {len(TABLE_ORDER)} 张表的输入文件；未修改契约或期望值。')
        return 0
    except Exception:
        # Never interpolate raw exception messages, response bodies, or headers.
        print('导出失败；未写入发布文件，请检查本地配置和输出目录。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
