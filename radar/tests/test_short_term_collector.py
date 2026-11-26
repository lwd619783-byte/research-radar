import copy
from contextlib import redirect_stdout
from datetime import date, datetime, time
import io
import json
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

RADAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR / 'tools'))
import collect_short_term as collector
from short_term_collector.http_client import PublicHttp


class ShortTermCollectorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(collector.RAW_FIXTURE.read_bytes())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'review.json'
        self.day = date.fromisoformat(self.fixture['date'])
        self.clock = datetime.combine(self.day, time(20, 30), collector.BJ)

    def snapshot(self, raw=None, previous=None):
        return collector.assemble(raw or self.fixture['market'], self.fixture['radar'], previous,
                                  self.day, self.clock, offline=True)

    def test_receipt_reads_pinned_linked_worktree_when_git_declines(self):
        root = Path(self.tmp.name)
        checkout = root / 'shadow checkout'
        (checkout / 'radar').mkdir(parents=True)
        admin = root / 'main/.git/worktrees/shadow'
        admin.mkdir(parents=True)
        pointer = checkout / '.git'
        (admin / 'gitdir').write_text(str(pointer) + '\n', encoding='utf-8')
        (admin / 'commondir').write_text('../..\n', encoding='ascii')
        commit = '1234567890abcdef' * 2 + '12345678'
        (admin / 'HEAD').write_text(commit + '\n', encoding='ascii')
        denied = collector.subprocess.CalledProcessError(128, ['git', 'rev-parse', 'HEAD'])
        with (patch.object(collector, 'RADAR', checkout / 'radar'),
              patch.object(collector.subprocess, 'check_output', side_effect=denied)):
            for target in (str(admin), '../main/.git/worktrees/shadow'):
                with self.subTest(target=target):
                    pointer.write_text(f'gitdir: {target}\n', encoding='utf-8')
                    self.assertEqual(collector.source_commit(), commit)
            for content in (f'gitdir {admin}\n', f'gitdir: {admin}\nextra\n', 'gitdir: ../absent\n'):
                with self.subTest(pointer=content):
                    pointer.write_text(content, encoding='utf-8')
                    self.assertIsNone(collector.source_commit())
            pointer.write_text(f'gitdir: {admin}\n', encoding='utf-8')
            for head in ('ref: refs/heads/main\n', 'f' * 39 + '\n'):
                with self.subTest(head=head):
                    (admin / 'HEAD').write_text(head, encoding='ascii')
                    self.assertIsNone(collector.source_commit())

    def test_serial_limiter_applies_after_failures_across_all_eastmoney_hosts(self):
        elapsed, calls = [0.0], []
        def nap(delay):
            elapsed[0] += delay
        def request(req, timeout):
            calls.append((req.host, elapsed[0]))
            if len(calls) <= 2:
                raise TimeoutError()
            body = io.BytesIO(b'{}')
            body.headers = {}
            return body
        http = PublicHttp(clock=lambda: elapsed[0], sleep=nap, open_request=request)
        with self.assertRaises(TimeoutError):
            http.get_json('https://push2.eastmoney.com/test')
        http.get_json('https://qt.gtimg.cn/test')
        http.get_json('https://datacenter-web.eastmoney.com/test')
        http.get_json('https://push2his.eastmoney.com/test')
        self.assertEqual([stamp for _, stamp in calls], [0, 1.5, 1.5, 3, 4.5])

    def test_transient_read_retries_but_provider_limits_and_invalid_payloads_do_not(self):
        url = 'https://qt.gtimg.cn/test'
        sleep = []
        results = [URLError(ssl.SSLEOFError(8, 'EOF')), b'{"verified":true}']

        def request(req, timeout):
            response = results.pop(0)
            if isinstance(response, Exception):
                raise response
            body = io.BytesIO(response)
            body.headers = {}
            return body

        http = PublicHttp(sleep=sleep.append, open_request=request)
        self.assertEqual(http.get_json(url), {'verified': True})
        self.assertEqual(sleep, [1])
        for response in (HTTPError(url, 403, '', {}, None), HTTPError(url, 429, '', {}, None),
                         HTTPError(url, 503, '', {'Retry-After': '600'}, None),
                         URLError(ssl.SSLCertVerificationError()), b'not-json'):
            results[:] = [response, b'{}']
            with self.assertRaises((URLError, ValueError)):
                http.get_json(url)
            self.assertEqual(results, [b'{}'])

        http.MAX_RETRIES_PER_ORIGIN = 1
        results[:] = [TimeoutError(), b'{}']
        with self.assertRaises(TimeoutError):
            http.get_json(url)
        self.assertEqual(results, [b'{}'])

    def test_cli_dry_run_and_real_atomic_file_round_trip_are_identical(self):
        command = ['--offline-fixture', '--output', str(self.path), '--date', self.day.isoformat()]
        buffer = io.StringIO()
        with patch('socket.socket', side_effect=AssertionError('Network forbidden')), redirect_stdout(buffer):
            self.assertEqual(collector.main([*command, '--dry-run']), 0)
            self.assertFalse(self.path.exists())
            dry = json.loads(buffer.getvalue())
            self.assertEqual(collector.main(command), 0)
            self.assertEqual(collector.main(command), 0)
        self.assertTrue(dry['meta']['reviewOnly'])
        self.assertEqual(json.loads(self.path.read_bytes()), dry)
        self.assertEqual(dry['days'][0]['stocks']['market']['up'][0]['name'], '样本甲')

    def test_failed_replace_and_concurrent_writer_preserve_exact_last_good(self):
        snapshot = self.snapshot()
        self.path.write_bytes(b'original')
        with patch.object(collector.os, 'replace', side_effect=PermissionError), self.assertRaises(PermissionError):
            collector.atomic_write(self.path, snapshot)
        self.assertEqual(self.path.read_bytes(), b'original')
        self.assertFalse(list(self.path.parent.glob('*.tmp')))
        with collector.writer_lock(self.path), self.assertRaises(collector.CollectionError):
            with collector.writer_lock(self.path):
                self.fail('second writer acquired the same destination')

    def test_offline_sentiment_and_skip_apply_to_the_same_hard_observations(self):
        command = ['--offline-fixture', '--dry-run']
        payloads = []
        with patch('socket.socket', side_effect=AssertionError('Network forbidden')):
            for switches in ([], ['--skip-ego']):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(collector.main(command + switches), 0)
                snapshot = json.loads(output.getvalue())
                payloads.append(snapshot['days'][0])
                self.assertNotIn('@离线样本', output.getvalue())
        full, skipped = payloads
        self.assertEqual(len(full['ego']['platforms']), 5)
        self.assertTrue(0 <= full['sentimentScore'] <= 100)
        self.assertEqual(skipped['ego']['posts'], [])
        self.assertIsNone(skipped['sentimentScore'])
        for key in ('stocks', 'breadth', 'industries', 'concepts', 'anchors'):
            self.assertEqual(full[key], skipped[key])

    def test_cold_start_and_failed_run_preserve_observation_dates(self):
        with self.assertRaises(collector.CollectionError):
            self.snapshot({'date': self.day.isoformat(), 'stocks': []})
        previous = self.snapshot()
        stale = self.snapshot({'date': self.day.isoformat(), 'stocks': []}, previous)
        self.assertEqual(stale['generatedAt'], previous['generatedAt'])
        self.assertEqual(stale['days'], previous['days'])
        self.assertTrue(stale['meta']['isStale'])
        self.path.write_bytes(b'{corrupt')
        self.assertEqual(collector.main(['--offline-fixture', '--output', str(self.path)]), 1)
        self.assertEqual(self.path.read_bytes(), b'{corrupt')

    def test_same_day_partial_rerun_cannot_replace_existing_better_snapshot(self):
        command = ['--offline-fixture', '--output', str(self.path)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(collector.main(command), 0)
        earlier_bytes = self.path.read_bytes()
        degraded = copy.deepcopy(self.fixture)
        degraded['market'].update(marketComplete=False, universeComplete=False, concepts=[])
        source = self.path.with_name('partial.json')
        source.write_text(json.dumps(degraded), 'utf-8')
        receipts = self.path.parent / 'receipts'
        self.assertEqual(collector.main(['--offline-fixture', str(source), '--output', str(self.path),
                                         '--receipt-dir', str(receipts)]), 3)
        self.assertEqual(self.path.read_bytes(), earlier_bytes)
        (receipt_file,) = receipts.rglob('*.json')
        receipt = json.loads(receipt_file.read_bytes())
        self.assertEqual(receipt['outcome'], 'kept_better_same_day')
        self.assertIn('breadth.turnover', receipt['keptEvidence'])

    def test_staged_evening_waits_for_sentiment_refresh_and_final_time(self):
        from short_term_collector.ego_sentiment import collect_sentiment
        when = datetime.combine(self.day, time(18, 15), collector.BJ)
        stages = []
        raw = copy.deepcopy(self.fixture['market'])
        captured = collect_sentiment(self.day, captures=self.fixture['egoCaptures'])

        def wait(day, target):
            nonlocal when
            self.assertEqual(day, self.day)
            stages.append(target)
            when = datetime.combine(day, target, collector.BJ)

        receipts = self.path.parent / 'receipts'
        with (patch.dict(collector.os.environ, {}, clear=True),
              patch.object(collector, 'now_bj', lambda: when),
              patch.object(collector, 'gather_local', return_value=(raw, self.fixture['radar'])),
              patch.object(collector, 'wait_until', side_effect=wait),
              patch.object(collector, 'refresh_disclosures') as refresh,
              patch('short_term_collector.ego_sentiment.collect_sentiment', return_value=captured),
              redirect_stdout(io.StringIO())):
            self.assertEqual(collector.main(['--evening', '--output', str(self.path),
                                             '--receipt-dir', str(receipts)]), 0)
        self.assertEqual(stages, [time(20,15), time(20,28), time(20,30)])
        refresh.assert_called_once()
        snapshot = json.loads(self.path.read_bytes())
        self.assertEqual(snapshot['generatedAt'], self.clock.isoformat(timespec='seconds'))
        (receipt_file,) = receipts.rglob('*.json')
        receipt = json.loads(receipt_file.read_bytes())
        self.assertTrue(receipt['onTime'])
        self.assertEqual(receipt['coverage']['egoCoverage'], 'complete')
        self.assertEqual(receipt['dataSHA256'], collector.data_digest(snapshot))

    def test_late_announcement_fetch_does_not_delay_the_final_slot(self):
        final_clock = datetime.combine(self.day, time(20, 30), collector.BJ)
        mine = {'title': '减持计划窗口', 'detail': '同日已核候选窗口'}
        collected = {'mines': [mine], 'warnings': []}
        with (patch.object(collector, 'now_bj', return_value=final_clock),
              patch.object(collector, 'refresh_disclosures') as refresh):
            self.assertFalse(collector.refresh_before_final(self.day, collected, PublicHttp()))
        refresh.assert_not_called()
        self.assertEqual(collected['mines'], [mine])
        self.assertIn('巨潮晚间复核超时', collected['warnings'])

    def test_dates_preserve_only_latest_ten_and_replace_repeated_session(self):
        history = None
        for stamp in ('2026-11-09','2026-11-10','2026-11-11','2026-11-12','2026-11-13',
                      '2026-11-16','2026-11-17','2026-11-18','2026-11-19','2026-11-20',
                      '2026-11-23','2026-11-24','2026-11-24'):
            self.day = date.fromisoformat(stamp)
            self.clock = datetime.combine(self.day, time(20, 30), collector.BJ)
            raw = copy.deepcopy(self.fixture['market'])
            raw['date'] = stamp
            for key in ('stocks', 'industries', 'concepts', 'intraday'):
                for row in raw[key]:
                    row['date'] = stamp
            history = self.snapshot(raw, history)
        dates = [day['date'] for day in history['days']]
        self.assertEqual(dates, sorted(set(dates), reverse=True))
        self.assertEqual((len(dates), dates[-1]), (10, '2026-11-11'))
        self.assertEqual(history['days'][0]['yesterdayReconcile']['targetDate'], '2026-11-23')
