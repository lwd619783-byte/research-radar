"""Validate the local short-term snapshot before writing or embedding it."""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
import json
import logging
import math
from pathlib import Path
import re
import unicodedata

from market_calendar import calendar_data, is_session, known_non_session
from output_scan import PRIVATE_KEYS, TOKEN

_DATA = Path(__file__).resolve().parents[1] / 'data'
_MAX_BYTES = 8 * 1024 * 1024
_ZONE = dt.timezone(dt.timedelta(hours=8))
_LOG = logging.getLogger(__name__)
_HANDLE = re.compile(r'[@＠][^\s，。！？、）)；;,!?]+')
_UI_MASK = {'核验': '检查', '核实': '查证', '核对': '比对', '待复核': '待查', '待核': '待查',
            '原评分': '先前分值', '原标记': '先前标签', '人工评分': '录入分值'}


@lru_cache(maxsize=1)
def contract():
    return json.loads((_DATA / 'short_term_schema.json').read_text('utf-8'))


@lru_cache(maxsize=1)
def _mask_rules():
    replacements = {**contract()['ego_sanitization']['banned_word_mask_map'], **_UI_MASK}
    phrases = sorted(replacements, key=len, reverse=True)
    pattern = re.compile('|'.join(r'\s*'.join(map(re.escape, phrase)) for phrase in phrases))
    return replacements, pattern


def sanitize_short_term_text(text):
    """Apply the same Unicode/whitespace semantics as the immutable output gate."""
    if not isinstance(text, str):
        raise ValueError('expected short-term text')
    if re.search(r'https?://[^\s/<>]+:[^\s/<>]+@', text, re.I):
        raise ValueError('private link')
    clean = _HANDLE.sub('匿名用户', text)
    replacements, pattern = _mask_rules()
    while pattern.search(clean):
        clean = pattern.sub(lambda m: replacements[re.sub(r'\s', '', m[0])], clean)
    clean = TOKEN.sub('已隐去', clean).replace('.mock-note', '已隐去')
    # Preserve punctuation except when a compatibility character masks a match.
    normalized = unicodedata.normalize('NFKC', clean)
    if normalized != clean and (pattern.search(normalized) or TOKEN.search(normalized) or '.mock-note' in normalized):
        return sanitize_short_term_text(normalized)
    return clean


def _require(condition):
    if not condition:
        raise ValueError('invalid short-term field')


def _clean(value, depth=0):
    _require(depth <= 12)
    if isinstance(value, dict):
        _require(len(value) <= 120)
        result = {}
        for key, item in value.items():
            # Public snapshot keys are stable identifiers, never accounts or prose.
            _require(isinstance(key, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,79}', key))
            _require(not TOKEN.search(key))
            if key.lower() in PRIVATE_KEYS | {'token', 'cookie', 'cookies', 'headers', 'password'}:
                continue
            result[key] = _clean(item, depth + 1)
        return result
    if isinstance(value, list):
        _require(len(value) <= 512)
        return [_clean(item, depth + 1) for item in value]
    if isinstance(value, str):
        _require(len(value) <= 2048 and not re.search(r'[\x00\ud800-\udfff]', value))
        return sanitize_short_term_text(value)
    if value is not None and not isinstance(value, bool):
        _require(type(value) in (int, float) and abs(value) <= 2**53 and math.isfinite(value))
    return value


def _iso_date(text):
    _require(isinstance(text, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', text))
    return dt.date.fromisoformat(text)


def _rows(value, limit=128):
    _require(isinstance(value, list) and len(value) <= limit and all(isinstance(row, dict) for row in value))
    return value


def _strings(row, fields):
    _require(isinstance(row, dict) and all(isinstance(row.get(k), str) for k in fields.split()))


def _percent(value):
    return type(value) in (int, float) and 0 <= value <= 100


def _validate_day(day):
    rules = contract()['day_entry_contract']
    _require(isinstance(day, dict) and set(rules['required_keys']) <= day.keys())
    session_date = _iso_date(day['date'])
    _require(session_date.weekday() < 5 and not known_non_session('000001.SS', day['date']))
    _strings(day, 'shortDate weekday headline subHeadline sentimentState')
    _require(day['themeColor'] in rules['themeColor_enum'])
    _require(day['sentimentScore'] is None or _percent(day['sentimentScore']))
    _require(isinstance(day['pulse'], dict) and isinstance(day['breadth'], dict))
    for k in ('up', 'flat', 'down', 'limitUp', 'limitDown'):
        n = day['breadth'].get(k)
        _require(n is None or n in ('—', 'X') or (type(n) is int and n >= 0))
    rec = day['yesterdayReconcile']
    _strings(rec, 'summary')
    for item in _rows(rec['items'], 3):
        _strings(item, 'code claim actual statusLabel')
        _require(item['status'] in rules['reconcile_status_enum'])
    for board in (day['industries'], day['concepts'], day['stocks']['market'], day['stocks']['radar']):
        for side in ('up', 'down'):
            for row in _rows(board[side], 5):
                _strings(row, 'name code')
                _require(type(row['pct']) in (int, float) and type(row['rank']) is int and 1 <= row['rank'] <= 5)
                spark = row.get('spark', [])
                _require(isinstance(spark, list) and len(spark) <= 5 and all(type(v) in (int, float) for v in spark))
    for node in _rows(day['timeline']):
        _strings(node, 'time phase title detail tag')
    cycle = day['cycle']
    _require(cycle['steps'] == rules['cycle_steps_fixed'])
    _require(cycle['activeStep'] is None or (type(cycle['activeStep']) is int and 0 <= cycle['activeStep'] < 5))
    for tier in _rows(cycle['tiers']):
        _rows(tier['stocks'])
    matrix = _rows(day['matrix'], 4)
    _require(sorted(q['key'] for q in matrix) == sorted(rules['matrix_keys_fixed']))
    for quad in matrix:
        _rows(quad['items'])
    ego = day['ego']
    _require(ego['score'] is None or _percent(ego['score']))
    platforms = contract()['ego_sanitization']['platforms']
    for platform in _rows(ego['platforms'], 5):
        _require(platform['id'] in platforms and all(_percent(platform[k]) for k in ('bull', 'flat', 'bear')))
    for post in _rows(ego['posts']):
        _require(post['platform'] in platforms)
        _strings(post, 'quote')
        # Source display names may be bare handles without an @ prefix.
        post['author'] = '匿名用户'
    for anchor in _rows(day['anchors'], 3):
        _strings(anchor, 'code title')
    _rows(day['dragonTiger']['items'])
    _rows(day['strategyPlan']['mines'])


def _validate_event(event):
    rules = contract()['catalyst_entry_contract']
    _strings(event, ' '.join(k for k in rules['required_keys'] if k != 'stars'))
    _require(event['id'] and type(event['stars']) is int and event['stars'] in rules['stars_enum'])
    _require(event['category'] in rules['category_enum'] and event['phaseTone'] in rules['phaseTone_enum'])
    _iso_date(event['startDate'])


def _bounds(as_of):
    if isinstance(as_of, str):
        as_of = dt.date.fromisoformat(as_of) if len(as_of) == 10 else dt.datetime.fromisoformat(as_of)
    if isinstance(as_of, dt.datetime):
        _require(as_of.utcoffset() is not None)
        local = as_of.astimezone(_ZONE)
        expected = local.date() if local.time() >= dt.time(20, 30) else local.date() - dt.timedelta(days=1)
    else:
        _require(isinstance(as_of, dt.date))
        local = dt.datetime.combine(as_of, dt.time.max, _ZONE)
        expected = as_of
    spec = calendar_data()['exchanges']['XSHG']
    while not is_session(spec, expected):
        expected -= dt.timedelta(days=1)
    return local, expected


_BAD = (KeyError, TypeError, ValueError, IndexError, OverflowError, RecursionError)


def normalize_history(data, *, as_of=None):
    """Return a fresh public snapshot, or raise ValueError if no usable day remains.

    Invalid rows cannot poison older valid observations. A date is a finalized
    trading-day cutoff; a timezone-aware clock also accounts for the 20:30 run.
    """
    from acceptance_bundle import check_sensitive

    rules = contract()
    _require(isinstance(data, dict) and data.get('schemaVersion') == rules['schema_version'])
    raw_days = data.get('days')
    _require(isinstance(raw_days, list) and 0 < len(raw_days) <= 512)
    meta = _clean(data.get('meta', {}))
    _require(isinstance(meta, dict) and type(meta.get('isStale', False)) is bool)
    generated = data.get('generatedAt')
    # Historical projections intentionally omit a snapshot timestamp that would
    # be in the future at the fixed clock. Such projections can be rescanned.
    projected = bool(meta.get('historicalCutoff'))
    _require(not projected or (meta.get('isStale') is True and not data.get('catalysts')))
    if not projected or generated is not None:
        _require(isinstance(generated, str) and re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})', generated, re.ASCII))
        assembled_at = dt.datetime.fromisoformat(generated.replace('Z', '+00:00')).astimezone(_ZONE)
    else:
        assembled_at = None
    clock, expected = _bounds(as_of) if as_of is not None else (None, None)
    later_assembly = bool(clock and assembled_at and assembled_at > clock)
    dated = {}
    degraded = False
    future = False
    for raw in raw_days:
        try:
            day = _clean(raw)
            _validate_day(day)
            key = day['date']
            check_sensitive(day)
            if ((expected and key > expected.isoformat()) or
                    (later_assembly and key >= assembled_at.date().isoformat())):
                future = True
                continue
            if key not in dated:
                dated[key] = day
        except _BAD:
            degraded = True
    _require(dated)
    dates = sorted(dated, reverse=True)[:rules['publish_cadence']['rolling_trading_days']]
    events = {}
    raw_events = data.get('catalysts')
    if isinstance(raw_events, list) and len(raw_events) <= 512 and not (future or later_assembly or projected):
        for raw in raw_events:
            try:
                event = _clean(raw)
                _validate_event(event)
                check_sensitive(event)
                events.setdefault(event['id'], event)
            except _BAD:
                degraded = True
    else:
        degraded = True
    meta['isStale'] = bool(meta.get('isStale') or degraded or (expected and dates[0] < expected.isoformat()))
    if future or later_assembly:
        meta['historicalCutoff'] = True
        # A later source label can describe observations unavailable at cutoff.
        meta['sourceLabel'] = '历史快照'
        if later_assembly:
            generated = None
    check_sensitive(meta)
    return {'schemaVersion': rules['schema_version'], 'generatedAt': generated, 'meta': meta,
            'days': [dated[key] for key in dates], 'catalysts': sorted(events.values(), key=lambda e: (e['startDate'], e['id']))}


def load_short_term(path, *, as_of=None, environ=None):
    """Read, validate, optionally overlay both read-only Notion tables and rescan."""
    try:
        with Path(path).open('rb') as source:
            payload = source.read(_MAX_BYTES + 1)
        _require(len(payload) <= _MAX_BYTES)
        history = normalize_history(json.loads(payload.decode('utf-8-sig')), as_of=as_of)
    except (OSError, *_BAD):
        _LOG.warning('Short-term snapshot unavailable or invalid; continuing with V3')
        return None
    if history['meta'].get('historicalCutoff'):
        return history
    try:
        from short_term_notion import apply_overrides
        adjusted = apply_overrides(history, environ=environ)
        if adjusted is not history:
            return normalize_history(adjusted, as_of=as_of)
    except Exception:
        # Optional provider failure must not block the independent V3 release.
        _LOG.warning('Short-term overrides unavailable; using local snapshot')
    return history
