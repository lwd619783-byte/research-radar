"""Synthetic safe evidence export; no source payload or publication."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import acceptance_bundle as bundle
import live_notion_dry_run as live
from test_twse_close_proof import create


class TwseLiveProofEvidenceTests(unittest.TestCase):
    def test_result_retains_exact_safe_proof_with_no_new_artifact_file(self):
        proof = create()
        data = {'companies': [{'sym': '2383.TW', 'provenance': {'daily': {
            'independentCloseProof': proof}}}], 'meta': {}}
        state = {'ready': True, 'verified': True, 'publicationAuthorized': False,
                 'purpose': 'live-notion-dry-run'}
        before = copy.deepcopy((data, state))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'evidence'
            live.export_artifact(target, data=data, summary='synthetic test; not publication', result=state)
            actual = json.loads((target / 'result.json').read_text('utf-8'))
            self.assertEqual(actual, {**state, 'independentCloseProofs': {'2383.TW': proof}})
            self.assertEqual({p.name for p in target.iterdir()}, {
                'result.json', 'meta.notion.json', 'meta.weekly.json', 'meta.daily.json', 'step-summary.md'})
            bundle.check_sensitive(actual)
        self.assertEqual((data, state), before)

    def test_absent_proof_keeps_existing_result_shape(self):
        state = {'ready': False, 'publicationAuthorized': False}
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'evidence'
            live.export_artifact(target, data={'companies': [], 'meta': {}}, summary='synthetic', result=state)
            self.assertEqual(json.loads((target / 'result.json').read_text('utf-8')), state)

    def test_proof_does_not_open_raw_or_secret_export(self):
        for forbidden in ('rawBody', 'headers', 'notion_token'):
            with self.subTest(field=forbidden), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'evidence'
                data = {'companies': [{'sym': '2383.TW', 'provenance': {'daily': {
                    'independentCloseProof': {**create(), forbidden: 'synthetic'}}}}], 'meta': {}}
                with self.assertRaises(bundle.BundleError):
                    live.export_artifact(target, data=data, summary='synthetic', result={'ready': False})
                self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
