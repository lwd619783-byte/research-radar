"""OFFLINE TEST DATA ONLY. No new real market observations or network requests."""
import contextlib
import copy
import datetime as dt
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import acceptance_bundle as bundle
import acceptance_probe as probe


def fixture():
    D = json.loads((ROOT / 'audit/offline-page-acceptance-2026-10-19/test-data.json').read_text())
    clock = dt.datetime.fromisoformat(D['meta']['generatedAt'])
    receipt = {'schemaVersion': 1, 'purpose': 'OFFLINE TEST ONLY — NOT NEW MARKET DATA',
               'execution': {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '0', 'GITHUB_RUN_ATTEMPT': '1'},
               'fixedClock': clock.isoformat(), 'requestsMade': 0,
               'publication': {'dataSHA256': bundle.data_digest(D), 'asOf': D['meta']['asOf'],
                               'snapshot': D['meta']['snapshot'], 'blockers': probe.build.release_blockers(D)}}
    return D, receipt, clock


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / 'archive'
        self.D, self.receipt, self.clock = fixture()
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('offline test attempted network')).start()
        self.addCleanup(patch.stopall)

    def save(self):
        return bundle.write_bundle(self.out, self.D, self.receipt, self.clock)

    def test_roundtrip_full_history_evidence_and_blockers_rerender_without_network(self):
        original = copy.deepcopy(self.D)
        saved = self.save()
        self.assertEqual(set(p.name for p in self.out.iterdir()), set(bundle.FILES))
        D = json.loads((self.out / 'DATA.json').read_text())
        html = (self.out / 'index.html').read_bytes()
        self.assertEqual(D, original)
        self.assertEqual(self.D, original)
        self.assertEqual(bundle.embedded_data(html), original)
        self.assertEqual(bundle.render_archive(D, self.receipt['publication']['blockers']), html)
        self.assertIn(b'OFFLINE TEST DATA', html)
        self.assertIn(b'connect-src', html)
        self.assertTrue(self.receipt['publication']['blockers'])
        manifest = json.loads((self.out / 'manifest.json').read_text())
        self.assertEqual(manifest['blockers'], self.receipt['publication']['blockers'])
        self.assertFalse(manifest['publicationAuthorized'])
        self.assertEqual(manifest['execution'], self.receipt['execution'])
        self.assertEqual(manifest['selectedDate'], '2026-10-16')
        self.assertEqual(manifest['fixedClock'], self.clock.isoformat())
        self.assertEqual(manifest['retentionDays'], 7)
        self.assertEqual(saved, bundle.verify_bundle(self.out))
        self.assertLess(saved['totalBytes'], 10_000_000)
        self.network.assert_not_called()

    def test_nonempty_blockers_are_never_removed_or_treated_as_publication(self):
        self.D['meta']['blockers'].append('offline_test_explicit_blocker')
        self.receipt['publication'].update(dataSHA256=bundle.data_digest(self.D), blockers=probe.build.release_blockers(self.D))
        self.save()
        for name in ('receipt.json', 'manifest.json'):
            self.assertIn('offline_test_explicit_blocker', (self.out / name).read_text())

    def test_manifest_binds_independent_price_and_metric_dates(self):
        self.D['meta']['snapshot']['policy']='latest-quote-and-market-completed-daily'
        self.D['meta']['priceDateRange']=['2026-10-16','2026-10-19']
        self.D['meta']['asOfByMarket']={'A股':['2026-10-19'],'美股':['2026-10-16']}
        self.receipt['publication']['dataSHA256']=bundle.data_digest(self.D)
        self.save()
        manifest=json.loads((self.out/'manifest.json').read_text())
        self.assertEqual(manifest['priceDateRange'],['2026-10-16','2026-10-19'])
        self.assertEqual(manifest['metricAsOfByMarket']['美股'],['2026-10-16'])
        manifest['metricAsOfByMarket']['美股']=['2026-10-19']
        (self.out/'manifest.json').write_bytes(bundle.encoded(manifest))
        with self.assertRaises(bundle.BundleError):bundle.verify_bundle(self.out)

    def test_sensitive_fields_in_data_or_receipt_fail_before_render_or_output(self):
        for target in (self.D, self.receipt):
            for key in ('cookie', 'headers', 'Authorization', 'access_token', 'rawBody', 'quoteResponse', 'documents'):
                with self.subTest(key=key):
                    target['nested'] = [{key: 'OFFLINE_TEST_SECRET'}]
                    with patch.object(bundle.build, 'render') as render, self.assertRaises(bundle.BundleError):
                        self.save()
                    render.assert_not_called()
                    self.assertFalse(self.out.exists())
                    del target['nested']

    def test_sensitive_values_reject_credentials_even_under_innocent_keys(self):
        for value in ('Bearer ' + 'synthetic' * 5, 'ghp_' + 'x' * 36,
                      'https://example.test/report?access_token=OFFLINE_TEST',
                      'https://test:fake@example.test/report'):
            with self.subTest(value_type='synthetic credential shape'):
                self.D['meta']['note'] = value
                with self.assertRaises(bundle.BundleError):
                    self.save()
                self.assertFalse(self.out.exists())
        del self.D['meta']['note']

    def test_public_source_proofs_and_boolean_auth_diagnostics_are_retained(self):
        self.receipt['quoteSession'] = {'cookieAvailable': True, 'crumbAvailable': False}
        self.save()
        actual = json.loads((self.out / 'DATA.json').read_text())
        self.assertEqual(actual['companies'][0]['provenance']['financial'], self.D['companies'][0]['provenance']['financial'])
        self.assertEqual(actual['meta']['fxProvenance'], self.D['meta']['fxProvenance'])
        self.assertEqual(actual['indices'], self.D['indices'])

    def test_data_clock_gate_or_identity_drift_is_rejected(self):
        base = copy.deepcopy(self.receipt)
        changes = [('fixedClock', '2026-10-20T00:00:00+00:00'),
                   ('publication', {**base['publication'], 'asOf': '2026-10-15'}),
                   ('publication', {**base['publication'], 'blockers': []}),
                   ('execution', {**base['execution'], 'GITHUB_RUN_ATTEMPT': '2'}),
                   ('execution', {**base['execution'], 'GITHUB_SHA': 'bad'})]
        for key, value in changes:
            self.receipt = {**base, key: value}
            with self.assertRaises(bundle.BundleError):
                self.save()
            self.assertFalse(self.out.exists())
        self.receipt = base
        self.D['companies'][0]['sc'][0] += 1
        with self.assertRaisesRegex(bundle.BundleError, 'same_snapshot'):
            self.save()

    def test_hard_total_limit_includes_manifest_and_is_atomic_not_truncated(self):
        saved = self.save()
        self.out = self.out.parent / 'too-small'
        payload_bytes = saved['totalBytes'] - saved['files']['manifest.json']['bytes']
        with patch.object(bundle, 'MAX_BUNDLE', payload_bytes), self.assertRaisesRegex(bundle.BundleError, 'size_limit'):
            self.save()
        self.assertFalse(self.out.exists())

    def test_real_ten_mb_overflow_and_receipt_cap_fail_without_archive(self):
        self.D['meta']['fixture'] = 'OFFLINE SYNTHETIC OVERFLOW ' + 'x' * 10_000_000
        self.receipt['publication']['dataSHA256'] = bundle.data_digest(self.D)
        with self.assertRaisesRegex(bundle.BundleError, 'bundle_size_limit'):
            self.save()
        self.assertFalse(self.out.exists())
        self.D, self.receipt, self.clock = fixture()
        self.receipt['offlineTestPadding'] = 'x' * (512 * 1024)
        with self.assertRaisesRegex(bundle.BundleError, 'receipt_size_limit'):
            self.save()
        self.assertFalse(self.out.exists())

    def test_html_data_mismatch_fails_without_archive(self):
        with patch.object(bundle, 'render_archive', return_value=b'<script>const DATA={};</script>'), self.assertRaisesRegex(bundle.BundleError, 'html_data'):
            self.save()
        self.assertFalse(self.out.exists())

    def test_allowlist_symlink_tamper_and_existing_directory_fail(self):
        self.save()
        with self.assertRaisesRegex(bundle.BundleError, 'destination_exists'):
            self.save()
        extra = self.out / 'raw-response.json'
        extra.write_text('OFFLINE TEST UNEXPECTED FILE')
        with self.assertRaisesRegex(bundle.BundleError, 'allowlist'):
            bundle.verify_bundle(self.out)
        extra.unlink()
        target = self.out / 'DATA.json'
        target.write_bytes(target.read_bytes() + b' ')
        with self.assertRaisesRegex(bundle.BundleError, 'manifest_mismatch'):
            bundle.verify_bundle(self.out)
        target.unlink()
        target.symlink_to(self.out / 'receipt.json')
        with self.assertRaisesRegex(bundle.BundleError, 'file_type'):
            bundle.verify_bundle(self.out)

    def test_manifest_cannot_change_purpose_or_add_unreviewed_fields(self):
        self.save()
        path = self.out / 'manifest.json'
        original = json.loads(path.read_text())
        for changed in ({**original, 'purpose': 'publish'}, {**original, 'extra': 'OFFLINE TEST'}):
            path.write_bytes(bundle.encoded(changed))
            with self.assertRaisesRegex(bundle.BundleError, 'manifest_schema'):
                bundle.verify_bundle(self.out)

    def test_nonfinite_json_is_rejected_without_output(self):
        self.D['companies'][0]['price'] = float('nan')
        with self.assertRaises(ValueError):
            self.save()
        self.assertFalse(self.out.exists())


class SameExecutionTests(unittest.TestCase):
    def test_real_main_collects_once_gates_same_object_and_archives_without_reassembly(self):
        # Actual entry/collect/assemble/save path, with ALL source adapters failing
        # synthetically. No sockets, new source observations or Action dispatches.
        clock = dt.datetime(2026, 10, 19, 12, tzinfo=probe.build.BJ)
        original_assemble = probe.build.assemble
        assembled = []
        def assemble(data, mk, fresh, now):
            self.assertIs(mk, fresh)
            D, stale, missing = original_assemble(data, mk, fresh, now)
            D['meta']['fixture'] = 'OFFLINE PIPELINE TEST — ALL ADAPTERS SYNTHETICALLY FAILED'
            assembled.append((D, now))
            return D, stale, missing
        original_collect = probe.collect
        def collect(data, budget, **kwargs):
            return original_collect(data, budget, snapshot_clock=clock, **kwargs)
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            network = stack.enter_context(patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')))
            for name in ('yahoo_daily', 'tencent_daily', 'yahoo_quotes', 'index_quote', 'fx', 'monthly'):
                stack.enter_context(patch.object(probe.quotes, name, side_effect=RuntimeError('OFFLINE TEST ONLY')))
            assembly = stack.enter_context(patch.object(probe.build, 'assemble', side_effect=assemble))
            collection = stack.enter_context(patch.object(probe, 'collect', side_effect=collect))
            gates = stack.enter_context(patch.object(probe.build, 'release_blockers', wraps=probe.build.release_blockers))
            stack.enter_context(patch.dict('os.environ', {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_RUN_ID': '0', 'GITHUB_SHA': 'a' * 40}))
            out = Path(tmp) / 'archive'
            stack.enter_context(patch.object(sys, 'argv', ['acceptance_probe.py', '--out', str(out / 'receipt.json')]))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(probe.main(), 0)
            self.assertEqual(collection.call_count, 1)
            self.assertEqual(assembly.call_count, 1)
            self.assertIs(assembled[0][1], clock)
            self.assertIs(gates.call_args_list[0].args[0], assembled[0][0])
            D = json.loads((out / 'DATA.json').read_text())
            self.assertEqual(D, assembled[0][0])
            receipt = json.loads((out / 'receipt.json').read_text())
            self.assertEqual(receipt['fixedClock'], clock.isoformat())
            self.assertEqual(receipt['requestsMade'], 0)
            self.assertTrue(receipt['publication']['blockers'])
            self.assertEqual(len(receipt['results']), 131)
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
