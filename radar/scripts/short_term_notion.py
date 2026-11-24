"""Optional read-only V4 corrections. The caller validates and sanitizes the result."""
import copy
from datetime import date
import json
import os
from pathlib import Path
import time
from uuid import UUID

from notion_source import DEFAULTS, NotionError, UrllibTransport


CONTRACT = Path(__file__).resolve().parents[1] / 'data' / 'short_term_schema.json'
SOURCES = {
    'short_term_ledger': 'SHORT_TERM_LEDGER_DATA_SOURCE_ID',
    'catalyst_calendar': 'SHORT_TERM_CATALYST_DATA_SOURCE_ID',
}
LABELS = {'pass': '达标', 'partial': '部分达标', 'fail': '未达标'}


def _query(source_id, transport, token):
    """Do not return partial pages if a cursor, credential or transport fails."""
    path = '/v1/data_sources/' + str(UUID(source_id)) + '/query'
    body, seen, pages = {'page_size': 100}, set(), []
    for _ in range(10):
        status, _, raw = transport.request('POST', path, body)
        if status != 200:
            raise ValueError('source unavailable')
        payload = json.loads(raw)
        if (not isinstance(payload, dict) or payload.get('object') != 'list'
                or not isinstance(payload.get('results'), list)
                or type(payload.get('has_more')) is not bool
                or token in json.dumps(payload, ensure_ascii=False)):
            raise ValueError('invalid response')
        pages.extend(page for page in payload['results'] if isinstance(page, dict)
                     and page.get('object') == 'page' and not page.get('in_trash')
                     and not page.get('archived'))
        if not payload['has_more']:
            return sorted(pages, key=lambda page: (str(page.get('last_edited_time', '')),
                                                   str(page.get('id', ''))))
        cursor = payload.get('next_cursor')
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ValueError('invalid cursor')
        seen.add(cursor)
        body['start_cursor'] = cursor
    raise ValueError('page limit exceeded')


def _properties(page, columns):
    props = page['properties']
    if not isinstance(props, dict):
        raise ValueError('invalid properties')
    values = {}
    for spec in columns:
        name, kind = spec['name'], spec['type']
        prop = props.get(name)
        if prop is None and not spec.get('required'):
            continue
        if not isinstance(prop, dict) or prop.get('type') != kind:
            raise ValueError('property type changed')
        value = prop[kind]
        if kind in ('title', 'rich_text'):
            value = ''.join(part['plain_text'] for part in value).strip()
        elif kind == 'select':
            value = value['name'] if value else None
        elif kind == 'date':
            value = value['start'] if value else None
        elif kind == 'checkbox' and type(value) is not bool:
            raise ValueError('invalid checkbox')
        elif kind == 'number':
            if type(value) not in (int, float) or not spec['min'] <= value <= spec['max']:
                raise ValueError('invalid number')
        if value is None or value == '':
            if spec.get('required'):
                raise ValueError('empty required field')
            continue
        if kind not in ('checkbox', 'number'):
            if not isinstance(value, str) or len(value) > spec.get('max_chars', 180):
                raise ValueError('invalid text')
            if 'options' in spec and value not in spec['options']:
                raise ValueError('invalid choice')
            if kind == 'date' or spec.get('format') == 'YYYY-MM-DD':
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError('invalid date')
        values[name] = value
    return values


def _ledger(day, row):
    stage, score = row['短线周期阶段'], row['散户情绪分']
    day['cycle']['activeStep'] = day['cycle']['steps'].index(stage)
    day['headline'] = row['定调结论']
    day['sentimentScore'] = day['ego']['score'] = score
    # A manually supplied third anchor may be the day's only observation.
    # Preserve its numbered slot when the collector and build reapply the row.
    anchors = {}
    for position, anchor in enumerate(day['anchors'], 1):
        slot = next((n for n in range(1, 4) if
                     anchor['code'].startswith(f'ANCHOR {n:02}')), position)
        anchors[slot] = anchor
    for i in range(1, 4):
        title = row.get(f'明日锚点_{i}')
        if title:
            # Numeric thresholds and explanations attached to the old claim
            # cannot be reused for a different human-authored observation.
            anchors[i] = {'code': f'ANCHOR {i:02}', 'title': title, 'desc': '台账观察项'}
    day['anchors'] = [anchors[i] for i in sorted(anchors)]
    reconcile = day['yesterdayReconcile']
    corrected = False
    for i, item in enumerate(reconcile['items'][:3], 1):
        status, actual = row.get(f'对账状态_{i}'), row.get(f'对账实盘_{i}')
        if status and actual:
            item.update(status=status, statusLabel=LABELS[status], actual=actual)
            corrected = True
    if corrected:
        reconcile['summary'] = '台账校正后，' + '、'.join(
            f'{i} 项{label}' for key, label in LABELS.items()
            if (i := sum(item['status'] == key for item in reconcile['items'])))


def _catalyst(row, as_of):
    start = date.fromisoformat(row['开始日期'])
    left = (start - as_of).days
    if not 0 <= left <= 45:
        return None
    macro = row['类别'] == 'macro'
    return dict(id=row['事件ID'], dateLabel=row['日期窗口'], startDate=start.isoformat(),
                daysLeft=f'T-{left}天', stars=int(row['星级']), category=row['类别'],
                categoryLabel='宏观事件' if macro else '产业事件', title=row['事件标题'],
                focus=row['核心看点'], mapping=row['映射方向'], phaseTag=row['阶段标签'],
                phaseTone='ai' if macro else 'auto', expectationNote=row['预期与兑现推演'])


def apply_overrides(history, *, environ=None, transport=None):
    """Apply complete valid rows to a copy. An empty environ forces offline mode."""
    env = os.environ if environ is None else environ
    token = env.get('NOTION_TOKEN', '').strip()
    if not token or not any(env.get(name) for name in SOURCES.values()) or not history.get('days'):
        return history
    schema = json.loads(CONTRACT.read_text(encoding='utf-8'))
    tables = schema['data_planes']['notion_optional_tables']
    if transport is None:
        transport = UrllibTransport(token, {**DEFAULTS, 'timeout_seconds': 4,
                                           'max_body_bytes': 1_048_576})
        transport.deadline = time.monotonic() + 12
    result = copy.deepcopy(history)
    days = {day['date']: day for day in result['days']}
    as_of = date.fromisoformat(max(days))
    events = {event['id']: event for event in result['catalysts']}
    changed_events = False
    for table, env_name in SOURCES.items():
        if not env.get(env_name):
            continue
        try:
            pages = _query(env[env_name], transport, token)
        except (NotionError, OSError, TypeError, ValueError, RecursionError):
            continue
        columns = list(tables[table]['columns'])
        if table == 'short_term_ledger':
            for i in range(1, 4):
                columns.extend((dict(name=f'对账状态_{i}', type='select', options=LABELS),
                                dict(name=f'对账实盘_{i}', type='rich_text', max_chars=180)))
        for page in pages:
            try:
                row = _properties(page, columns)
                if row.get('停用'):
                    continue
                if table == 'short_term_ledger':
                    if row['交易日期'] in days:
                        _ledger(days[row['交易日期']], row)
                else:
                    event = _catalyst(row, as_of)
                    if event:
                        events[event['id']] = event
                        changed_events = True
                    elif row['事件ID'] in events:
                        events.pop(row['事件ID'], None)
                        changed_events = True
            except (KeyError, TypeError, ValueError):
                continue
    if changed_events:
        result['catalysts'] = sorted(events.values(), key=lambda event: (event['startDate'], event['id']))
    return result
