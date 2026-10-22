"""Bounded read-only Notion transport; credentials are never returned or logged."""
import datetime as dt
import json
import math
import re
import time
import urllib.error
import urllib.request


TABLE_ORDER = ('industries', 'chokepoints', 'companies', 'financials', 'daily', 'weekly')
DEFAULTS = dict(api_base='https://api.notion.com', version='2026-03-11',
                timeout_seconds=20, phase_budget_seconds=180, max_body_bytes=8388608,
                max_pages_per_table=50, min_interval_seconds=0.34)
ERROR_CODES = frozenset(('notion_token_missing', 'notion_unauthorized', 'notion_forbidden',
    'notion_not_found', 'notion_rate_limited', 'notion_server_error', 'notion_timeout',
    'notion_bad_json', 'notion_body_too_large', 'notion_cursor_loop',
    'notion_too_many_pages', 'notion_http_error', 'notion_schema_changed'))
NOTION_CODES = frozenset(('invalid_json', 'invalid_request_url', 'invalid_request',
    'validation_error', 'missing_version', 'unauthorized', 'restricted_resource',
    'object_not_found', 'conflict_error', 'rate_limited', 'internal_server_error',
    'bad_gateway', 'service_unavailable', 'database_connection_unavailable',
    'gateway_timeout'))
PROPERTY_TYPES = frozenset(('title', 'rich_text', 'number', 'select', 'multi_select',
    'date', 'people', 'files', 'checkbox', 'url', 'email', 'phone_number', 'formula',
    'relation', 'rollup', 'created_time', 'created_by', 'last_edited_time',
    'last_edited_by', 'status', 'unique_id', 'button'))


class NotionError(Exception):
    """Only allowlisted diagnostic fields may cross the transport boundary."""
    def __init__(self, code, table=None, http_status=None, notion_code=None):
        self.code = code if code in ERROR_CODES else 'notion_http_error'
        self.table = table if table in TABLE_ORDER else None
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        self.notion_code = notion_code if notion_code in NOTION_CODES else None
        super().__init__(self.code)

    def as_dict(self, table=None):
        return dict(code=self.code, table=table if table in TABLE_ORDER else self.table,
                    http_status=self.http_status, notion_code=self.notion_code)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibTransport:
    """Streaming size/deadline limits also apply to HTTP error responses."""
    def __init__(self, token, settings, *, clock=None):
        self._token = token
        self.settings = settings
        self.clock = clock or time.monotonic
        self.deadline = None
        self.opener = urllib.request.build_opener(_NoRedirect())

    def _read(self, response):
        limit = self.settings['max_body_bytes']
        parts, size = [], 0
        while True:
            if self.deadline is not None and self.clock() >= self.deadline:
                raise NotionError('notion_timeout')
            part = response.read(min(65536, limit + 1 - size))
            if not part:
                return b''.join(parts)
            size += len(part)
            if size > limit:
                raise NotionError('notion_body_too_large')
            parts.append(part)

    def request(self, method, path, json_body):
        if method not in ('GET', 'POST') or not re.fullmatch(
                r'/v1/data_sources/[0-9a-fA-F-]{36}(?:/query)?', path):
            raise NotionError('notion_http_error')
        headers = {'Authorization': 'Bearer ' + self._token,
                   'Notion-Version': self.settings['version'],
                   'Content-Type': 'application/json', 'Accept': 'application/json',
                   'User-Agent': 'research-radar/3'}
        raw = None if json_body is None else json.dumps(json_body).encode('utf-8')
        request = urllib.request.Request(self.settings['api_base'] + path,
                                         data=raw, headers=headers, method=method)
        timeout = self.settings['timeout_seconds']
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - self.clock())
            if timeout <= 0:
                raise NotionError('notion_timeout')
        try:
            try:
                response = self.opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                if response.status in (401, 403):
                    return response.status, {}, b''
                # No authorization, cookies, or other response headers leave here.
                return (response.status, {'Retry-After': response.headers.get('Retry-After', '')},
                        self._read(response))
        except NotionError:
            raise
        except Exception:
            raise NotionError('notion_timeout') from None


def _settings(settings):
    settings = settings or {}
    supplied = settings.get('notion', settings)
    result = {**DEFAULTS, **{k: v for k, v in supplied.items() if k in DEFAULTS}}
    # Tokens must never be sent to a configurable alternative origin.
    if result['api_base'] != DEFAULTS['api_base'] or result['version'] != DEFAULTS['version']:
        raise ValueError('invalid_notion_api_configuration')
    for key in ('timeout_seconds', 'phase_budget_seconds', 'max_body_bytes',
                'max_pages_per_table', 'min_interval_seconds'):
        value = result[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                not math.isfinite(value) or value <= 0 or value > DEFAULTS[key]):
            raise ValueError('invalid_notion_limits')
    for key in ('max_body_bytes', 'max_pages_per_table'):
        if type(result[key]) is not int:
            raise ValueError('invalid_notion_limits')
    return result


def _timestamp(fixed_clock):
    value = fixed_clock
    if value is None:
        value = dt.datetime.now(dt.UTC)
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, dt.datetime) or value.tzinfo is None:
        raise ValueError('invalid_notion_fixed_clock')
    return value.isoformat()


def _decode(raw):
    def reject(value):
        raise ValueError('invalid_json_number')
    try:
        value = json.loads(raw, parse_constant=reject)
    except (ValueError, UnicodeError):
        raise NotionError('notion_bad_json') from None
    if not isinstance(value, dict):
        raise NotionError('notion_bad_json')
    return value


def _schema_detail(schema, definition):
    properties = schema['properties']
    for name, expected in definition['properties'].items():
        if expected['level'] == 'ignore':
            continue
        if name not in properties:
            return dict(prop=name, change='missing', expected=expected['type'], actual=None)
        value = properties[name]
        actual = value.get('type') if isinstance(value, dict) else None
        if actual != expected['type']:
            return dict(prop=name, change='type_changed', expected=expected['type'],
                        actual=actual if isinstance(actual, str) and actual in PROPERTY_TYPES else 'unknown')
    return None


def fetch_all(contract, settings, *, token, transport=None, sleep=None, pace=None,
              clock=None, fixed_clock=None):
    """Fetch schema/pages serially; failures are safe statuses, not raw exceptions.

    Inject ``clock`` for monotonic phase budgeting and ``fixed_clock`` for stable
    fetchedAt values. ``pace()`` is separate from retry ``sleep(seconds)``.
    """
    options = _settings(settings)
    fetched_at = _timestamp(fixed_clock)
    for name in TABLE_ORDER:
        definition = contract['tables'][name]
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', definition['data_source_id']):
            raise ValueError('invalid_notion_data_source_id')
    result = dict(tables={}, stopped_all=False, requests=0,
                  request_stats={'total': 0, 'GET': 0, 'POST': 0, 'retries': 0})

    def failure(name, error, detail=None):
        safe = error.as_dict(name)
        if detail is not None:
            safe['detail'] = detail
        return dict(ok=False, schema={}, pages=[], fetchedAt=fetched_at, error=safe)

    def stop_all(error):
        result.update(stopped_all=True, error=error.as_dict())
        result['tables'] = {name: failure(name, error) for name in TABLE_ORDER}
        return result

    if not isinstance(token, str) or not token.strip():
        return stop_all(NotionError('notion_token_missing'))
    timer = clock or time.monotonic
    retry_sleep = sleep or time.sleep
    deadline = timer() + options['phase_budget_seconds']
    transport = transport if transport is not None else UrllibTransport(token, options, clock=timer)
    if isinstance(transport, UrllibTransport):
        transport.deadline = deadline
    last_request = None

    def check_budget():
        if timer() >= deadline:
            raise NotionError('notion_timeout')

    def request(method, path, body, table):
        nonlocal last_request
        for attempt in range(4):
            check_budget()
            if pace is not None:
                pace()
            elif last_request is not None:
                delay = options['min_interval_seconds'] - (timer() - last_request)
                if delay > 0:
                    time.sleep(min(delay, max(0, deadline - timer())))
            check_budget()
            last_request = timer()
            result['requests'] += 1
            result['request_stats']['total'] += 1
            result['request_stats'][method] += 1
            result['request_stats']['retries'] += int(attempt > 0)
            try:
                status, headers, raw = transport.request(method, path, body)
            except AssertionError:
                # FakeTransport uses this to expose unexpected request routes.
                raise
            except NotionError as error:
                if error.code != 'notion_timeout':
                    raise NotionError(error.code, table, error.http_status, error.notion_code) from None
                status, headers, raw = None, {}, b''
            except Exception:
                status, headers, raw = None, {}, b''
            if not isinstance(raw, (bytes, bytearray)) or not isinstance(headers, dict):
                raise NotionError('notion_bad_json', table)
            notion_code = None
            if status != 200 and raw and len(raw) <= options['max_body_bytes']:
                try:
                    candidate = _decode(raw).get('code')
                    if candidate in NOTION_CODES:
                        notion_code = candidate
                except (NotionError, TypeError):
                    pass
            if status in (401, 403):
                raise NotionError('notion_unauthorized' if status == 401 else 'notion_forbidden',
                                  table, status, notion_code)
            check_budget()
            if len(raw) > options['max_body_bytes']:
                raise NotionError('notion_body_too_large', table)
            retry = status is None or status == 429 or (type(status) is int and 500 <= status <= 599)
            if retry:
                code = ('notion_timeout' if status is None else
                        'notion_rate_limited' if status == 429 else 'notion_server_error')
                if attempt == 3:
                    raise NotionError(code, table, status, notion_code)
                delay = 2 ** attempt
                if status == 429:
                    header = next((v for k, v in headers.items() if str(k).lower() == 'retry-after'), '')
                    try:
                        seconds = float(header)
                        if math.isfinite(seconds) and seconds >= 0:
                            delay = min(seconds, 60)
                    except (TypeError, ValueError):
                        pass
                remaining = deadline - timer()
                if delay >= remaining:
                    raise NotionError('notion_timeout', table)
                retry_sleep(delay)
                continue
            if status != 200:
                raise NotionError('notion_not_found' if status == 404 else 'notion_http_error',
                                  table, status, notion_code)
            # Reject echoed credentials rather than allowing them into snapshots.
            if token.encode('utf-8') in raw:
                raise NotionError('notion_bad_json', table)
            decoded = _decode(raw)
            if token in json.dumps(decoded, ensure_ascii=False):
                raise NotionError('notion_bad_json', table)
            return decoded
        raise AssertionError('unreachable')

    for name in TABLE_ORDER:
        definition = contract['tables'][name]
        base = '/v1/data_sources/' + definition['data_source_id']
        try:
            schema = request('GET', base, None, name)
            if schema.get('object') != 'data_source' or not isinstance(schema.get('properties'), dict):
                raise NotionError('notion_bad_json', name)
            detail = _schema_detail(schema, definition)
            if detail:
                result['tables'][name] = failure(name, NotionError('notion_schema_changed', name), detail)
                continue
            pages, cursors, cursor = [], set(), None
            for page_number in range(options['max_pages_per_table']):
                body = {'page_size': 100}
                if cursor is not None:
                    body['start_cursor'] = cursor
                payload = request('POST', base + '/query', body, name)
                if (payload.get('object') != 'list' or not isinstance(payload.get('results'), list)
                        or type(payload.get('has_more')) is not bool):
                    raise NotionError('notion_bad_json', name)
                for page in payload['results']:
                    if not isinstance(page, dict) or page.get('object') != 'page':
                        continue
                    if not isinstance(page.get('properties'), dict) or not isinstance(page.get('id'), str):
                        raise NotionError('notion_bad_json', name)
                    # Keep in_trash/disabled rows for normalize's exclusion cascade.
                    pages.append(page)
                if not payload['has_more']:
                    break
                cursor = payload.get('next_cursor')
                if not isinstance(cursor, str) or not cursor:
                    raise NotionError('notion_bad_json', name)
                if cursor in cursors:
                    raise NotionError('notion_cursor_loop', name)
                cursors.add(cursor)
            else:
                raise NotionError('notion_too_many_pages', name)
            result['tables'][name] = dict(ok=True, schema=schema, pages=pages, fetchedAt=fetched_at)
        except NotionError as error:
            if error.code in ('notion_unauthorized', 'notion_forbidden'):
                return stop_all(error)
            result['tables'][name] = failure(name, error)
    return result
