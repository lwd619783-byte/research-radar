"""Collect one dated, local 20:30 Asia/Shanghai review. Dry runs print JSON."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, time
import json
import os
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

RADAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR / 'scripts'))
from acceptance_bundle import data_digest
from market_calendar import calendar_data, is_session
from output_scan import embedded_data
from short_term_merge import load_short_term, normalize_history
from short_term_notion import apply_overrides
from short_term_collector.http_client import PublicHttp

BJ = ZoneInfo('Asia/Shanghai')
HISTORY = RADAR / 'data/short_term_history.json'
RAW_FIXTURE = RADAR / 'tests/fixtures/short_term_v4/raw_session.json'
PUBLIC_RELEASE = 'https://raw.githubusercontent.com/lwd619783-byte/research-radar/production/'


class CollectionError(ValueError):
    """A fixed, credential-free operator diagnostic."""


@contextmanager
def writer_lock(path):
    """Hold an OS lock over the complete read/collect/replace transaction."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name('.' + path.name + '.lock').open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if not stream.tell():
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
            acquire = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            acquire()
        except OSError:
            raise CollectionError('collector_already_running') from None
        yield  # closing the handle releases the lock, including on process exit


def atomic_write(path, value):
    with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.short-term-',
                                     suffix='.tmp', delete=False, encoding='utf-8') as stream:
        temp = Path(stream.name)
        try:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        # Verify the actual serialized bytes before replacing the existing history.
        verified = load_short_term(temp, environ={})
        if verified != value:
            raise CollectionError('snapshot_round_trip_failed')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_radar(path, day, http):
    if path:
        text = path.read_text('utf-8-sig')
        data = embedded_data(text) if path.suffix.lower() == '.html' else json.loads(text)
    else:
        manifest = http.get_json(PUBLIC_RELEASE + 'release.json')
        data = embedded_data(http.get_text(PUBLIC_RELEASE + 'public/index.html'))
        if data_digest(data) != manifest['dataSHA256']:
            raise CollectionError('radar_release_digest_mismatch')
    if (not all(isinstance(data.get(k), list) for k in ('companies', 'industries', 'chokepoints'))
            or data['meta'].get('reviewPreview') or data['meta']['today'] > day.isoformat()):
        raise CollectionError('radar_context_unavailable')
    return data


def latest_before(history, day):
    return next((row for row in (history or {}).get('days', []) if row['date'] < day.isoformat()), None)


def assemble(raw, radar, history, day, clock, *, offline=False, environ=None):
    from short_term_collector.analytics import build_day, dated_stock_quotes
    if raw.get('date') != day.isoformat():
        raise CollectionError('market_date_mismatch')
    usable, _ = dated_stock_quotes(raw, day)
    if not usable or (not offline and raw.get('closeConfirmed') is not True):
        if not history:
            raise CollectionError('no_dated_market_snapshot')
        stale = {**history, 'meta': {**history['meta'], 'isStale': True}}
        return normalize_history(stale)
    record = build_day(day, raw, radar, latest_before(history, day))
    record['pulse']['finalTime'] = clock.astimezone(BJ).strftime('%m/%d %H:%M 汇总')
    older = [row for row in (history or {}).get('days', []) if row['date'] != day.isoformat()]
    warnings = sorted(set(raw.get('warnings') or []))
    meta = {'sourceLabel': '离线采集样本' if offline else '本机收盘采集',
            'isStale': False, 'coverageWarnings': warnings}
    if offline:
        meta['reviewOnly'] = True
    if radar.get('meta', {}).get('today'):
        meta['radarAsOf'] = radar['meta']['today']
    draft = {'schemaVersion': '4.0-short-term', 'generatedAt': clock.astimezone(BJ).isoformat(timespec='seconds'),
             'meta': meta, 'days': [record, *older], 'catalysts': raw.get('events', [])}
    result = normalize_history(draft)
    if result['days'][0]['date'] != day.isoformat():
        raise CollectionError('new_day_failed_contract')
    try:
        adjusted = apply_overrides(result, environ={} if offline else environ)
        if adjusted is not result:
            normalized = normalize_history(adjusted)
            if normalized['days'][0]['date'] == day.isoformat():
                return normalized
    except Exception:
        print('可选台账不可用，保留本机采集结果', file=sys.stderr)
    return result


def run(args):
    http = PublicHttp()
    now = datetime.now(BJ)
    offline = args.offline_fixture is not None
    if not offline and (os.getenv('GITHUB_ACTIONS') == 'true' or os.getenv('CI') == 'true'):
        raise CollectionError('live_collection_is_local_only')
    fixture = json.loads(args.offline_fixture.read_bytes()) if offline else None
    day = args.date or (date.fromisoformat(fixture['date']) if offline else now.date())
    if not is_session(calendar_data()['exchanges']['XSHG'], day):
        print(f'{day} 休市，跳过采集', file=sys.stderr)
        return 0
    if not offline and (day > now.date() or (day == now.date() and now.time() < time(20,30))):
        raise CollectionError('evening_final_not_due')
    path = (args.output or HISTORY).resolve()
    preview = args.dry_run or (offline and args.output is None)
    if offline and not preview and path == HISTORY.resolve():
        raise CollectionError('offline_fixture_requires_separate_output')
    with nullcontext() if preview else writer_lock(path):
        history = None
        if path.is_file() and not (offline and args.output is None):
            history = load_short_term(path, environ={} if offline else None)
            if history is None or history['days'][0]['date'] > day.isoformat():
                raise CollectionError('existing_history_corrupt_or_newer')
            if bool(history['meta'].get('reviewOnly')) != offline:
                raise CollectionError('live_and_fixture_history_must_be_separate')
        if offline:
            raw, radar = fixture['market'], fixture['radar']
            clock = datetime.combine(day, time(20,30), BJ)
        else:
            from short_term_collector.events import collect_events
            from short_term_collector.market import collect_market
            try:
                radar = read_radar(args.radar_data, day, http)
            except Exception:
                radar = {}
            try:
                raw = collect_market(day, radar, http)
            except Exception:
                raw = {'date': day.isoformat(), 'stocks': [], 'warnings': ['market_unavailable']}
            warnings = list(raw.get('warnings') or [])
            if not radar:
                warnings.append('radar_context_unavailable')
            try:
                extras = collect_events(day, raw, http)
                raw.update(extras)
                warnings.extend(extras.get('warnings', []))
            except Exception:
                warnings.append('events_unavailable')
            raw['warnings'] = warnings
            clock = datetime.now(BJ)
        result = assemble(raw, radar, history, day, clock, offline=offline)
        if preview:
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        else:
            atomic_write(path, result)
            print(f'{result["days"][0]["date"]} · {len(result["days"])} 个交易日 · {path}')
        if result['days'][0]['date'] != day.isoformat() or result['meta']['isStale']:
            print('数据降级，沿用可用快照', file=sys.stderr)
            return 2
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', type=date.fromisoformat)
    parser.add_argument('--dry-run', action='store_true', help='Print sanitized JSON without writing files')
    parser.add_argument('--offline-fixture', nargs='?', type=Path, const=RAW_FIXTURE, metavar='RAW_JSON')
    parser.add_argument('--radar-data', type=Path, help='Published V3 DATA.json or single-file HTML')
    parser.add_argument('--output', type=Path)
    try:
        return run(parser.parse_args(argv))
    except CollectionError as error:
        print(str(error), file=sys.stderr)
    except Exception as error:
        # Provider exception text can contain request headers or unsanitized posts.
        print(f'采集未完成（{type(error).__name__}），已保留原快照', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
