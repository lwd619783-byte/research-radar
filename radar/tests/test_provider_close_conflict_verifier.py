"""Offline parity between receipt binding and the Python/Node release checks."""

import datetime as dt
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import acceptance_bundle as bundle
from latest import PROVIDER_CLOSE_CONFLICT_METHOD
import release_operations as operations


DAY = '2026-11-09'
SELECTED = '2026-11-06'
CLOCK = dt.datetime.fromisoformat('2026-11-09T06:05:01+00:00')
RECEIVED = '2026-11-09T15:05:00.123456+09:00'
END = dt.datetime.fromisoformat(RECEIVED).timestamp()
SOURCE = 'a' * 40
ERROR = 'provider_close_conflict_binding_mismatch'


def packet():
    marker = {'date': DAY, 'sessionEnd': END, 'receivedAt': RECEIVED}
    selection = {'method': PROVIDER_CLOSE_CONFLICT_METHOD, 'sourceAsOf': DAY,
                 'sourcePhase': 'closed', 'selectedDate': SELECTED}
    row = {'sym': '000660.KS', 'ld': SELECTED, 'metricAsOf': SELECTED, 'providerCloseConflict': marker,
           'marketCalendar': {'expectedCompletedDate': SELECTED, 'quoteDate': SELECTED, 'confidence': 'official'},
           'provenance': {'daily': {'snapshotSelection': selection, 'asOf': SELECTED, 'phase': 'closed',
                                   'receivedAt': RECEIVED}}}
    meta = {'asOf': SELECTED, 'generatedAt': CLOCK.isoformat(timespec='minutes'),
            'today': CLOCK.date().isoformat(), 'snapshot': {}, 'blockers': []}
    return {'meta': meta, 'companies': [row]}


def receipt(data):
    return {'fixedClock': CLOCK.isoformat(),
            'execution': {'GITHUB_SHA': SOURCE, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'},
            'publication': {'dataSHA256': bundle.data_digest(data), 'asOf': SELECTED, 'snapshot': {}, 'blockers': []}}


def write_release(path, data):
    public = path / 'public'
    public.mkdir()
    version = {'sourceSHA': SOURCE, 'dataSHA256': bundle.data_digest(data)}
    html = ('<script>const DATA=' + json.dumps(data) + ';</script>\n'
            '<script id="radar-operations">const OPERATIONS=' + json.dumps(version) + ';</script>')
    (public / 'index.html').write_text(html, encoding='utf-8')
    (public / 'robots.txt').write_text('User-agent: *\nDisallow: /\n', encoding='utf-8')
    (public / 'version.json').write_bytes(bundle.encoded(version))
    history = bundle.encoded({'schemaVersion': 1, 'days': []})
    (path / 'history.json').write_bytes(history)
    (path / 'release.json').write_bytes(bundle.encoded({**version, 'schemaVersion': 2,
        'runId': '123', 'blockers': [], 'files': {}, 'historySHA256': bundle.digest(history)}))
    operations.refresh_hashes(path)


class ProviderCloseConflictVerifierTests(unittest.TestCase):
    def check_release(self, data, valid):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_release(root, data)
            same_run = receipt(data)
            if valid:
                bundle.validate_binding(data, same_run, CLOCK)
                _, readback = operations.verify_files(root)
                self.assertEqual(readback, data)
            else:
                with self.assertRaisesRegex(bundle.BundleError, ERROR):
                    bundle.validate_binding(data, same_run, CLOCK)
                with self.assertRaisesRegex(bundle.BundleError, ERROR):
                    operations.verify_files(root)
            node = subprocess.run(['node', str(SCRIPTS / 'verify-release.cjs'), '--check-only'],
                                  cwd=root, capture_output=True, encoding='utf-8', timeout=10)
            self.assertEqual(node.returncode == 0, valid, node.stderr)
            if not valid:
                self.assertIn(ERROR, node.stderr)

    def test_confirmed_conflict_and_ordinary_release_are_both_valid(self):
        data = packet()
        self.check_release(data, valid=True)
        row = data['companies'][0]
        row['marketCalendar']['confidence'] = 'rule_based'
        row['providerCloseConflict']['receivedAt'] = '2026-11-09T06:05:00.123456Z'
        row['provenance']['daily']['receivedAt'] = row['providerCloseConflict']['receivedAt']
        self.check_release(data, valid=True)
        del row['providerCloseConflict']
        row['provenance']['daily']['snapshotSelection']['method'] = 'latest-completed-per-market'
        self.check_release(data, valid=True)

    def test_marker_and_selection_method_must_both_be_present(self):
        data = packet()
        del data['companies'][0]['providerCloseConflict']
        self.check_release(data, valid=False)
        data = packet()
        data['companies'][0]['provenance']['daily']['snapshotSelection']['method'] = 'latest-completed-per-market'
        self.check_release(data, valid=False)
        data = packet()
        data['companies'][0]['providerCloseConflict'] = None
        self.check_release(data, valid=False)

    def test_all_selected_dates_and_source_provenance_are_bound(self):
        changes = [(('ld',), DAY), (('metricAsOf',), DAY),
                   (('marketCalendar', 'expectedCompletedDate'), DAY), (('marketCalendar', 'quoteDate'), DAY),
                   (('marketCalendar', 'confidence'), 'provisional'), (('provenance', 'daily', 'asOf'), DAY),
                   (('provenance', 'daily', 'phase'), 'intraday'),
                   (('provenance', 'daily', 'snapshotSelection', 'selectedDate'), DAY),
                   (('provenance', 'daily', 'snapshotSelection', 'sourceAsOf'), SELECTED),
                   (('provenance', 'daily', 'snapshotSelection', 'sourcePhase'), 'intraday'),
                   (('provenance', 'daily', 'receivedAt'), CLOCK.isoformat())]
        for path, invalid in changes:
            with self.subTest(path=path):
                data = packet()
                target = data['companies'][0]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = invalid
                self.check_release(data, valid=False)

    def test_conflict_date_must_be_real_and_later_than_selected_close(self):
        for day in (SELECTED, '2026-11-05', '2026-11-31', '20261109'):
            with self.subTest(day=day):
                data = packet()
                row = data['companies'][0]
                row['providerCloseConflict']['date'] = day
                row['provenance']['daily']['snapshotSelection']['sourceAsOf'] = day
                self.check_release(data, valid=False)

    def test_numeric_end_is_safe_and_at_or_before_received_at(self):
        for invalid in ('1794204300.123456', False, 0, -1, 1 << 53, math.nextafter(END, math.inf)):
            with self.subTest(end=invalid):
                data = packet()
                data['companies'][0]['providerCloseConflict']['sessionEnd'] = invalid
                self.check_release(data, valid=False)

    def test_malformed_receipt_and_extra_marker_fields_are_rejected(self):
        for invalid in ('2026-11-09T06:05:00', '2026-11-09T06:05:00+00:60',
                        '2026-11-31T06:05:00+00:00', '2026-11-09T24:00:00Z', RECEIVED + '\n'):
            with self.subTest(received=invalid):
                data = packet()
                row = data['companies'][0]
                row['providerCloseConflict']['receivedAt'] = invalid
                row['provenance']['daily']['receivedAt'] = invalid
                self.check_release(data, valid=False)
        data = packet()
        data['companies'][0]['providerCloseConflict']['extra'] = True
        self.check_release(data, valid=False)
