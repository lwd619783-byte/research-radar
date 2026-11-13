"""Readback validates close proofs even after release files are rehashed."""

import json
from pathlib import Path
import tempfile
import unittest

from test_provider_close_conflict_verifier import write_release
from test_yahoo_meta_close_verifier import ERROR, packet

import acceptance_bundle as bundle
import release_operations as operations


class YahooMetaCloseReleaseOperationsTests(unittest.TestCase):
    def test_release_readback_enforces_proof_binding_and_accepts_legacy_data(self):
        for case in ('valid', 'preclose', 'missing_clock', 'price_source_only', 'legacy'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                item = packet()
                row = item['data']['companies'][0]
                daily = row['provenance']['daily']
                if case == 'preclose':
                    daily['yahooMetaClose']['marketTime'] -= 1
                if case in ('price_source_only', 'legacy'):
                    del daily['yahooMetaClose']
                    daily['src'] = 'yahoo'
                if case == 'legacy':
                    row['priceSource'] = 'yahoo'
                write_release(root, item['data'])
                if case not in ('missing_clock', 'legacy'):
                    path = root / 'release.json'
                    manifest = json.loads(path.read_bytes())
                    manifest['fixedClock'] = item['clock']
                    path.write_bytes(bundle.encoded(manifest))
                if case in ('valid', 'legacy'):
                    _, data = operations.verify_files(root)
                    self.assertEqual(data, item['data'])
                else:
                    with self.assertRaisesRegex(bundle.BundleError, ERROR):
                        operations.verify_files(root)
