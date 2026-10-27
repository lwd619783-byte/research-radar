"""Synthetic, offline proof/output binding. Never authorizes a publication."""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import acceptance_bundle as bundle
import equity_close_proof as proof_module

ROOT = Path(__file__).resolve().parents[2]
CLOCK = dt.datetime.fromisoformat('2026-10-27T20:00:04+08:00')
EXECUTION = {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}


def packet():
    record = {'schemaVersion': 2, 'src': 'yahoo', 'priceBasis': 'raw',
        'returnBasis': 'yahoo-adjclose', 'currency': 'TWD', 'timezone': 'Asia/Taipei',
        'phase': 'unknown', 'asOf': '2026-10-27', 'receivedAt': '2026-10-27T12:00:01+00:00',
        'bars': [['2026-10-22', 5070., 5070., 5485.], ['2026-10-27', 4750., 4750., 5200.]],
        'barTimestamps': {'2026-10-22': 1792630800, '2026-10-27': 1793079015},
        'finality': {'method': 'provider-session-boundary', 'start': 1793062800, 'end': 1793079000}}
    document = {'stat': 'OK', 'date': '20261027', 'title': '115年10月 2383 台光電 各日成交資訊',
        'fields': list(proof_module.FIELDS),
        'data': [['115/10/27', '1', '1', '5,200.00', '5,200.00', '4,685.00', '4,750.00', '-320.00', '1', '']]}
    official = {'sourceUrl': proof_module.official_url('2026-10-27'), 'httpStatus': 200,
        'sha256': 'b' * 64, 'receivedAt': '2026-10-27T12:00:02+00:00'}
    yahoo = {'sourceUrl': proof_module.YAHOO_URL, 'httpStatus': 200,
        'sha256': 'c' * 64, 'receivedAt': '2026-10-27T12:00:00+00:00'}
    proof = proof_module.make_proof(record, document, official_event=official, yahoo_event=yahoo,
        expected_day='2026-10-27', now=CLOCK, execution=EXECUTION)
    assert proof is not None
    daily = {key: record[key] for key in ('src', 'asOf', 'receivedAt', 'returnBasis', 'timezone')}
    daily.update(phase='closed', independentCloseProof=proof,
        snapshotSelection={'sourcePhase': 'unknown', 'sourceAsOf': '2026-10-27',
                           'selectedDate': '2026-10-27'})
    row = {'sym': '2383.TW', 'cur': 'TWD', 'ld': '2026-10-27', 'metricAsOf': '2026-10-27',
        'priceAsOf': '2026-10-27', 'price': 4750., 'pricePhase': 'closed', 'priceSource': 'yahoo',
        'priceObservedAt': None, 'priceSelection': {'useQuote': False},
        'marketCalendar': {'exchange': 'XTAI', 'confidence': 'official',
                          'expectedCompletedDate': '2026-10-27', 'quoteDate': '2026-10-27'},
        'provenance': {'daily': daily}}
    data = {'meta': {'fixture': True}, 'companies': [row]}
    proofs = {'2383.TW': copy.deepcopy(proof)}
    manifest = {'sourceSHA': EXECUTION['GITHUB_SHA'], 'runId': EXECUTION['GITHUB_RUN_ID'],
                'fixedClock': CLOCK.isoformat(), 'independentCloseProofs': proofs}
    return data, proofs, manifest


class TwseProofBindingTests(unittest.TestCase):
    def node(self, data, manifest):
        script = ('const fs=require("node:fs");'
            'const {checkIndependentCloseProofs}=require(' + json.dumps(str(ROOT / 'radar/scripts/verify-release.cjs')) + ');'
            'const x=JSON.parse(fs.readFileSync(0,"utf8"));checkIndependentCloseProofs(x.manifest,x.data);')
        return subprocess.run(['node', '-e', script], input=json.dumps({'data': data, 'manifest': manifest}),
                              text=True, capture_output=True, encoding='utf-8')

    def assert_rejected(self, data, proofs, manifest):
        with self.assertRaisesRegex(bundle.BundleError, 'independent_close_proof_binding'):
            bundle.validate_close_proofs(data, proofs, EXECUTION, CLOCK)
        self.assertNotEqual(self.node(data, manifest).returncode, 0)

    def test_same_run_safe_summary_binds_in_python_and_node_without_mutation(self):
        data, proofs, manifest = packet()
        before = copy.deepcopy((data, proofs, manifest))
        bundle.validate_close_proofs(data, proofs, EXECUTION, CLOCK)
        checked = self.node(data, manifest)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual((data, proofs, manifest), before)
        bundle.check_sensitive(data)
        bundle.check_sensitive(proofs)

    def test_existing_provider_only_path_needs_no_new_fields(self):
        data = {'companies': [{'sym': '2383.TW', 'provenance': {'daily': {'phase': 'closed'}}}]}
        bundle.validate_close_proofs(data, None, EXECUTION, CLOCK)
        checked = self.node(data, {'sourceSHA': 'a' * 40, 'runId': '123', 'fixedClock': CLOCK.isoformat()})
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_absent_receipt_proof_and_absent_data_proof_reject(self):
        data, proofs, manifest = packet()
        missing = copy.deepcopy(manifest)
        del missing['independentCloseProofs']
        self.assert_rejected(data, None, missing)
        del data['companies'][0]['provenance']['daily']['independentCloseProof']
        self.assert_rejected(data, proofs, manifest)

    def test_checksum_tampering_and_cross_run_proofs_reject(self):
        for field, value in [('checksum', 'd' * 64), ('officialResponseSHA256', 'e' * 64),
                             ('execution', EXECUTION | {'GITHUB_RUN_ID': '456'})]:
            with self.subTest(field=field):
                data, proofs, manifest = packet()
                data['companies'][0]['provenance']['daily']['independentCloseProof'][field] = value
                proofs['2383.TW'][field] = copy.deepcopy(value)
                self.assert_rejected(data, proofs, manifest)

    def test_price_day_symbol_quote_and_source_phase_binding_reject(self):
        changes = [('price', 4751.), ('price', '4750'), ('price', True),
                   ('metricAsOf', '2026-10-22'), ('priceAsOf', '2026-10-22'),
                   ('sym', '2330.TW'), ('cur', 'USD'), ('pricePhase', 'unknown'),
                   ('priceObservedAt', '2026-10-27T05:30:15Z'), ('priceSelection', {'useQuote': True})]
        for field, value in changes:
            with self.subTest(field=field):
                data, proofs, manifest = packet()
                data['companies'][0][field] = value
                self.assert_rejected(data, proofs, manifest)
        data, proofs, manifest = packet()
        data['companies'][0]['provenance']['daily']['snapshotSelection']['sourcePhase'] = 'closed'
        self.assert_rejected(data, proofs, manifest)

    def test_duplicate_company_and_other_symbol_proof_reject(self):
        data, proofs, manifest = packet()
        data['companies'].append(copy.deepcopy(data['companies'][0]))
        self.assert_rejected(data, proofs, manifest)
        data, proofs, manifest = packet()
        proofs['2330.TW'] = proofs.pop('2383.TW')
        self.assert_rejected(data, proofs, manifest)

    def test_manifest_identity_is_checked_by_node(self):
        for field, value in [('sourceSHA', 'f' * 40), ('runId', '456'),
                             ('fixedClock', '2026-10-27T12:00:03.999999+00:00')]:
            with self.subTest(field=field):
                data, _, manifest = packet()
                manifest[field] = value
                self.assertNotEqual(self.node(data, manifest).returncode, 0)

    def test_recomputed_checksum_cannot_authorize_invalid_evidence_fields(self):
        changes = [('officialSourceUrl', 'https://example.test/official'),
                   ('officialTitle', '115年10月 2330 台積電 各日成交資訊'),
                   ('officialReceivedAt', '2026-10-27T05:29:59+00:00'),
                   ('yahooReceivedAt', '2026-10-27T12:00:01.000001+00:00'),
                   ('barTimestamp', 1793079000), ('verified', True)]
        for field, value in changes:
            with self.subTest(field=field):
                data, proofs, manifest = packet()
                proof = proofs['2383.TW']
                proof[field] = value
                content = {key: child for key, child in proof.items() if key != 'checksum'}
                proof['checksum'] = hashlib.sha256(json.dumps(content, ensure_ascii=False,
                    sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
                data['companies'][0]['provenance']['daily']['independentCloseProof'] = copy.deepcopy(proof)
                self.assert_rejected(data, proofs, manifest)

    def test_coherently_rewritten_old_day_and_calendar_cannot_reuse_fresh_receipts(self):
        data, proofs, manifest = packet()
        proof = proofs['2383.TW']
        old_day = '2026-10-22'
        proof.update(day=old_day, officialSourceUrl=proof_module.official_url(old_day),
                     officialResponseDate='20261022')
        proof['officialRow']['date'] = '115/10/22'
        # All provider epoch dates move together; no inconsistent summary field
        # or stale receipt is relied on to reject this rewritten certificate.
        for key in ('sessionStart', 'sessionEnd', 'barTimestamp'):
            proof[key] -= 5 * 86400
        content = {key: child for key, child in proof.items() if key != 'checksum'}
        proof['checksum'] = hashlib.sha256(json.dumps(content, ensure_ascii=False,
            sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
        row = data['companies'][0]
        for key in ('ld', 'metricAsOf', 'priceAsOf'):
            row[key] = old_day
        row['marketCalendar'].update(expectedCompletedDate=old_day, quoteDate=old_day)
        daily = row['provenance']['daily']
        daily['asOf'] = old_day
        daily['snapshotSelection'].update(sourceAsOf=old_day, selectedDate=old_day)
        daily['independentCloseProof'] = copy.deepcopy(proof)
        self.assertEqual(proof['day'], daily['asOf'])
        self.assertEqual(proof, manifest['independentCloseProofs']['2383.TW'])
        self.assertEqual(proof['officialReceivedAt'], '2026-10-27T12:00:02+00:00')
        self.assert_rejected(data, proofs, manifest)


if __name__ == '__main__':
    unittest.main()
