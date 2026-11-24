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
