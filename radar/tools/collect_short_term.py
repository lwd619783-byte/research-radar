"""Collect one dated, local 20:30 Asia/Shanghai review. Dry runs print JSON."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
import sys
import tempfile
from threading import Thread
import time as sleeper
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
PREPARE_TIME = time(17, 30)
BOARD_RETRY_TIME = time(19, 25)
BOARD_RETRY_CUTOFF = time(20, 10)
SENTIMENT_TIME = time(20, 15)
REFRESH_TIME = time(20, 28)
FINAL_TIME = time(20, 30)


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


def atomic_write(path, value, *, verify_snapshot=True):
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
        if verify_snapshot and load_short_term(temp, environ={}) != value:
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


def evidence(snapshot):
    """Compare evidenced fields; totals of unrelated modules cannot cancel losses."""
    row = snapshot['days'][0]
    result = {}
    present = lambda value: value is not None and value not in ('—', 'X', '')
    for key, value in row['breadth'].items():
        result[f'breadth.{key}'] = int(present(value))
    for panel, board in [('industries', row['industries']), ('concepts', row['concepts']),
                         *row['stocks'].items()]:
        for side in ('up', 'down'):
            entries = board[side]
            result[f'{panel}.{side}.positions'] = len(entries)
            for key in ('spark', 'netFlow', 'px'):
                result[f'{panel}.{side}.{key}'] = sum(bool(r.get(key)) and present(r[key]) for r in entries)
    result['dragonTiger'] = len(row['dragonTiger']['items'])
    result['dragonSeats'] = sum(present(item.get('seats')) and '暂缺' not in item['seats']
                               for item in row['dragonTiger']['items'])
    result['yesterdayReconcile'] = len(row['yesterdayReconcile']['items'])
    result['risks'] = len(row.get('strategyPlan', {}).get('mines') or [])
    cycle = row.get('cycle', {})
    for key in ('maxHeight', 'activeStep'):
        result[f'cycle.{key}'] = int(present(cycle.get(key)))
    result['cycle.tiers'] = len(cycle.get('tiers') or [])
    result['ego.score'] = int(present(row.get('sentimentScore')))
    result['ego.posts'] = len(row['ego'].get('posts') or [])
    warnings = snapshot['meta'].get('coverageWarnings', [])
    # A source-supported empty result can be replaced by another verified empty result.
    # Losing the source altogether is a regression even when it had no rows.
    for name, code in [('dragon', '龙虎榜暂缺'), ('unlock', '解禁暂缺'), ('reduce', '巨潮减持暂缺'),
                       ('volatility', '巨潮异常波动暂缺'), ('jin10', '金十日历暂缺'),
                       ('emEvents', '东财会议暂缺'), ('thsEvents', '同花顺日历暂缺')]:
        result[f'source.{name}'] = int(snapshot['meta'].get('eventsCollected') is True and code not in warnings)
    for name, value in snapshot['meta'].get('observations', {}).items():
        if type(value) is int and value >= 0:
            result[f'observed.{name}'] = value
    for node in row['timeline']:
        detail = node.get('detail')
        if node['time'] in ('09:25', '10:30', '13:30', '15:00') and isinstance(detail, str) and '暂缺' not in detail:
            result[f"timeline.{node['time']}"] = 1
    for platform in row['ego'].get('platforms', []):
        if type(platform.get('sampleCount')) is int:
            result[f"ego.{platform['id']}.samples"] = platform['sampleCount']
        for track in platform.get('tracks', []):
            result[f"ego.{platform['id']}.{track}"] = 1
    for event in snapshot['catalysts']:
        key = f"catalyst.{event.get('source')}"
        result[key] = result.get(key, 0) + 1
    return result


def weaker_same_day(candidate, previous):
    if not previous or candidate['days'][0]['date'] != previous['days'][0]['date']:
        return []
    if candidate['meta']['isStale'] and not previous['meta']['isStale']:
        return ['dated_market_unavailable']
    observed = evidence(candidate)
    return sorted(key for key, value in evidence(previous).items() if observed.get(key, 0) < value)


def now_bj():
    return datetime.now(BJ)


def wait_until(day, target):
    deadline = datetime.combine(day, target, BJ)
    while (left := (deadline - now_bj()).total_seconds()) > 0:
        sleeper.sleep(min(left, 30))


def gather_local(day, radar_path, http):
    from short_term_collector.events import collect_events
    from short_term_collector.market import collect_market
    try:
        radar = read_radar(radar_path, day, http)
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
        raw['eventsCollected'] = True
        warnings.extend(extras.get('warnings', []))
    except Exception:
        warnings.append('events_unavailable')
    raw['warnings'] = warnings
    return raw, radar


def refresh_disclosures(day, raw, http):
    existing = raw.get('mines', [])
    warnings = raw.setdefault('warnings', [])
    try:
        from short_term_collector.events import collect_disclosure_risks
        revised, source_warnings = collect_disclosure_risks(day, http, recent_only=True)
    except Exception:
        warnings.append('巨潮晚间复核暂缺')
        return False
    window_types = {'减持计划变更公告': '减持计划窗口', '停复牌计划变更公告': '停复牌窗口'}
    changed = {(window_types[item['title']], m[1]) for item in revised if item['title'] in window_types
               if (m := re.search(r'（(\d{6})）', item['detail']))}
    retained = [item for item in existing if not any(
        item['title'] == kind and f'（{code}）' in item['detail'] for kind, code in changed)]
    if source_warnings:
        warnings.extend(source_warnings)
        combined = [*retained, *revised]
    else:
        warnings[:] = [item for item in warnings if item not in ('巨潮减持暂缺','巨潮异常波动暂缺')]
        late_types = ('减持公告','减持计划变更公告','异常波动公告')
        combined = [*(item for item in retained if item.get('title') not in late_types), *revised]
    unique = {(item['title'], item['detail']): item for item in combined}
    raw['mines'] = list(unique.values())[:128]
    return not source_warnings


def before_deadline(deadline, work):
    remaining = (deadline - now_bj()).total_seconds()
    if remaining <= 0:
        return None
    pending = Queue(maxsize=1)

    def read():
        try:
            pending.put(work())
        except Exception:
            pending.put(None)

    Thread(target=read, daemon=True).start()
    try:
        return pending.get(timeout=remaining)
    except Empty:
        return None


def refresh_before_final(day, raw, http):
    revised = {**raw, 'warnings': list(raw.get('warnings', [])), 'mines': list(raw.get('mines', []))}
    completed = before_deadline(datetime.combine(day, FINAL_TIME, BJ),
                                lambda: refresh_disclosures(day, revised, http))
    if completed is None:
        raw.setdefault('warnings', []).append('巨潮晚间复核超时')
        return False
    raw['mines'], raw['warnings'] = revised['mines'], revised['warnings']
    return completed


def assemble(raw, radar, history, day, clock, *, offline=False, environ=None):
    from short_term_collector.analytics import build_day, dated_stock_quotes
    if raw.get('date') != day.isoformat():
        raise CollectionError('market_date_mismatch')
    usable, market_complete = dated_stock_quotes(raw, day)
    if not usable or (not offline and raw.get('closeConfirmed') is not True):
        if not history:
            raise CollectionError('no_dated_market_snapshot')
        stale = {**history, 'meta': {**history['meta'], 'isStale': True}}
        return normalize_history(stale)
    sentiment = raw.get('ego') or {}
    if 'platformDiagnostics' in sentiment:
        raw = {**raw, 'ego': {key: value for key, value in sentiment.items() if key != 'platformDiagnostics'}}
    record = build_day(day, raw, radar, latest_before(history, day))
    record['pulse']['finalTime'] = clock.astimezone(BJ).strftime('%m/%d %H:%M 汇总')
    older = [row for row in (history or {}).get('days', []) if row['date'] != day.isoformat()]
    warnings = sorted(set(raw.get('warnings') or []))
    meta = {'sourceLabel': '离线采集样本' if offline else '本机收盘采集',
            'isStale': False, 'coverageWarnings': warnings}
    if raw.get('eventsCollected') is True:
        meta['eventsCollected'] = True
    meta['observations'] = dict(marketComplete=int(market_complete), intraday=len(raw.get('intraday') or []))
    if type(raw.get('coreQuotes')) is int:
        meta['observations']['coreQuotes'] = raw['coreQuotes']
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


def write_receipt(path, receipt):
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, receipt, verify_snapshot=False)


def source_commit():
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=RADAR, stderr=subprocess.DEVNULL,
                                         text=True, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        # A desktop task may read a pinned checkout owned by its installer
        # even when Git declines to run there. Read only a detached HEAD.
        git_dir = RADAR.parent / '.git'
        try:
            if git_dir.is_file():
                pointer = re.fullmatch(r'gitdir: ([^\r\n\x00]+)\n?', git_dir.read_text(encoding='utf-8'))
                if not pointer:
                    return None
                git_dir = git_dir.parent / pointer[1]
            commit = (git_dir / 'HEAD').read_text(encoding='ascii').rstrip('\n')
        except (OSError, UnicodeError):
            return None
    return commit if re.fullmatch(r'[0-9a-f]{40}', commit) else None


def observe(raw, result=None):
    row = result['days'][0] if result else {}
    sentiment = raw.get('ego') or {}
    return {
        'asOf': row.get('date'), 'sessions': len(result['days']) if result else 0,
        'marketComplete': bool(result and result['meta'].get('observations', {}).get('marketComplete') == 1
                               and not result['meta']['isStale']),
        'stockRows': len(raw.get('stocks') or []), 'coreExpected': raw.get('coreExpected'), 'coreQuotes': raw.get('coreQuotes'),
        'industryRows': len(raw.get('industries') or []), 'conceptRows': len(raw.get('concepts') or []),
        'limitUpRows': len(raw['limitPool']) if isinstance(raw.get('limitPool'), list) else None,
        'timelinePoints': sorted({p['time'] for p in raw.get('intraday', [])}),
        'dragonTigerRows': len(raw.get('dragonTiger', {}).get('items') or []),
        'riskRows': len(raw.get('mines') or []), 'catalystRows': len(result['catalysts'] if result else raw.get('events') or []),
        'anchorsCompared': len(row.get('yesterdayReconcile', {}).get('items', [])), 'egoCoverage': sentiment.get('coverage', 'missing'),
        'egoSamples': sentiment.get('sampleCount', 0), 'egoPlatforms': sentiment.get('platformStatus', {}),
        'egoTrackDiagnostics': sentiment.get('platformDiagnostics', {}),
        'warnings': sorted(set(raw.get('warnings', []))),
    }


def render_local_preview(folder, radar, snapshot, day):
    from build import render
    if not radar:
        return 'v3_context_unavailable'
    try:
        render({**radar, 'shortTerm': snapshot}, folder / day.isoformat())
    except Exception:
        return 'scan_or_render_failed'
    return 'scan_passed'


def run(args):
    http = PublicHttp()
    start = now_bj()
    offline = args.offline_fixture is not None
    if not offline and (os.getenv('GITHUB_ACTIONS') == 'true' or os.getenv('CI') == 'true'):
        raise CollectionError('live_collection_is_local_only')
    fixture = json.loads(args.offline_fixture.read_bytes()) if offline else None
    day = args.date or (date.fromisoformat(fixture['date']) if offline else start.date())
    if args.evening and (offline or day != start.date()):
        raise CollectionError('staged_evening_requires_current_live_session')
    if not offline and (day > start.date() or (day == start.date() and
            start.time() < (PREPARE_TIME if args.evening else FINAL_TIME))):
        raise CollectionError('evening_final_not_due')
    path = (args.output or HISTORY).resolve()
    preview = args.dry_run or (offline and args.output is None)
    if offline and not preview and path == HISTORY.resolve():
        raise CollectionError('offline_fixture_requires_separate_output')
    file = (args.receipt_dir / day.isoformat() / f'{start:%H%M%S-%f}-{os.getpid()}.json') if args.receipt_dir else None
    receipt = {'date': day.isoformat(), 'startedAt': start.isoformat(), 'staged': args.evening,
               'offline': offline, 'outcome': 'running'}
    if file:
        receipt['sourceSHA'] = source_commit()

    def phase(name):
        receipt[name] = now_bj().isoformat()
        write_receipt(file, receipt)

    def finish(outcome, code):
        finished = now_bj()
        target = datetime.combine(day, FINAL_TIME, BJ)
        written = datetime.fromisoformat(receipt['snapshotWrittenAt']) if 'snapshotWrittenAt' in receipt else finished
        receipt.update(outcome=outcome, finishedAt=finished.isoformat(), exitCode=code,
                       onTime=bool(outcome == 'written' and target <= written < target + timedelta(minutes=1)))
        write_receipt(file, receipt)
        return code

    if not is_session(calendar_data()['exchanges']['XSHG'], day):
        print(f'{day} 休市，跳过采集', file=sys.stderr)
        return finish('closed', 0)
    try:
        return run_session(args, day, offline, fixture, http, path, preview, receipt, phase, finish)
    except Exception as error:
        receipt['failure'] = str(error) if isinstance(error, CollectionError) else type(error).__name__
        finish('failed', 1)
        raise


def run_session(args, day, offline, fixture, http, path, preview, receipt, phase, finish):
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
            clock = datetime.combine(day, FINAL_TIME, BJ)
        else:
            from short_term_collector.analytics import dated_stock_quotes
            phase('hardStartedAt')
            raw, radar = gather_local(day, args.radar_data, http)
            quoted, complete = dated_stock_quotes(raw, day)
            receipt['hardInitialCoverage'] = {'datedStocks': len(quoted), 'marketComplete': complete,
                                               'warnings': raw.get('warnings', [])}
            phase('hardFinishedAt')
            if args.evening and not quoted and now_bj().time() < time(19,40):
                sleeper.sleep(60)
                phase('hardRetryStartedAt')
                retried, revision = gather_local(day, args.radar_data, http)
                quoted, complete = dated_stock_quotes(retried, day)
                receipt['hardRetryCoverage'] = {'datedStocks': len(quoted), 'marketComplete': complete,
                                                 'warnings': retried.get('warnings', [])}
                if quoted:
                    raw, radar = retried, revision
                phase('hardRetryFinishedAt')
        if args.evening:
            board_cutoff = datetime.combine(day, BOARD_RETRY_CUTOFF, BJ)
            if (not raw.get('industries') or not raw.get('concepts')) and now_bj() < board_cutoff:
                from short_term_collector.market import retry_missing_boards
                wait_until(day, BOARD_RETRY_TIME)
                phase('boardRetryStartedAt')
                recovered = before_deadline(board_cutoff, lambda source=raw: retry_missing_boards(day, source, http))
                if recovered is None:
                    raw = {**raw, 'warnings': [*raw.get('warnings', []), '板块晚间补采未完成']}
                else:
                    raw = recovered
                receipt['boardRetryCoverage'] = {'industryRows': len(raw.get('industries', [])),
                                                 'conceptRows': len(raw.get('concepts', []))}
                phase('boardRetryFinishedAt')
            wait_until(day, SENTIMENT_TIME)
        if raw.get('closeConfirmed') or args.evening:
            phase('egoStartedAt')
            from short_term_collector.ego_sentiment import collect_sentiment
            try:
                raw['ego'] = collect_sentiment(day, skip=args.skip_ego, previous=latest_before(history, day),
                                               captures=fixture.get('egoCaptures', {}) if offline else None,
                                               breadth=raw.get('breadth') if raw.get('marketComplete') is True else None)
            except Exception:
                raw.setdefault('warnings', []).append('ego_unavailable')
            phase('egoFinishedAt')
        if args.evening:
            wait_until(day, REFRESH_TIME)
            phase('announcementCheckStartedAt')
            if refresh_before_final(day, raw, http):
                phase('announcementObservedAt')
            phase('announcementCheckFinishedAt')
        if not offline:
            clock = now_bj()
        if args.evening:
            clock = max(clock, datetime.combine(day, FINAL_TIME, BJ))
        receipt['coverage'] = observe(raw)
        result = assemble(raw, radar, history, day, clock, offline=offline)
        if args.evening:
            wait_until(day, FINAL_TIME)
            now = now_bj()
            if now.date() != day:
                raise CollectionError('staged_evening_crossed_midnight')
            if result['days'][0]['date'] == day.isoformat() and not result['meta']['isStale']:
                result['generatedAt'] = now.isoformat(timespec='seconds')
                result['days'][0]['pulse']['finalTime'] = now.strftime('%m/%d %H:%M 汇总')
        receipt['coverage'] = observe(raw, result)
        lost = weaker_same_day(result, history)
        if lost:
            receipt['keptEvidence'] = lost
            print('本次覆盖低于已验同日快照，保留现有版本。', file=sys.stderr)
            if preview:
                print(json.dumps(result, ensure_ascii=False, allow_nan=False))
            return finish('kept_better_same_day', 3)
        if preview:
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        else:
            atomic_write(path, result)
            phase('snapshotWrittenAt')
            print(f'{result["days"][0]["date"]} · {len(result["days"])} 个交易日 · {path}')
        if result['days'][0]['date'] != day.isoformat() or result['meta']['isStale']:
            print('数据降级，沿用可用快照', file=sys.stderr)
            return finish('stale', 2)
        receipt['dataSHA256'] = data_digest(result)
        if args.preview_dir and not preview:
            receipt['localPreview'] = render_local_preview(args.preview_dir, radar, result, day)
            phase('previewCheckedAt')
        return finish('dry_run' if preview else 'written', 0)


@contextmanager
def quiet_output():
    with open(os.devnull, 'w', encoding='utf-8') as sink, redirect_stdout(sink), redirect_stderr(sink):
        yield


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', type=date.fromisoformat)
    output_mode = parser.add_mutually_exclusive_group()
    output_mode.add_argument('--dry-run', action='store_true', help='Print sanitized JSON without writing files')
    output_mode.add_argument('--quiet', action='store_true', help='Suppress console output when writing a snapshot')
    parser.add_argument('--offline-fixture', nargs='?', type=Path, const=RAW_FIXTURE, metavar='RAW_JSON')
    parser.add_argument('--radar-data', type=Path, help='Published V3 DATA.json or single-file HTML')
    parser.add_argument('--skip-ego', action='store_true', help='Collect the hard-data review without opening Ego')
    parser.add_argument('--evening', action='store_true', help='Prepare today after 17:30, sample at 20:15 and finalize at 20:30 Beijing time')
    parser.add_argument('--receipt-dir', type=Path, help='Local directory for per-attempt timing, coverage and diagnostic receipts')
    parser.add_argument('--preview-dir', type=Path, help='Build and scan one local review page per written session')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.quiet and args.offline_fixture is not None and args.output is None:
        parser.error('--quiet with --offline-fixture requires --output')
    with quiet_output() if args.quiet else nullcontext():
        try:
            return run(args)
        except CollectionError as error:
            print(str(error), file=sys.stderr)
        except Exception as error:
            # Provider exception text can contain request headers or unsanitized posts.
            print(f'采集未完成（{type(error).__name__}），已保留原快照', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
