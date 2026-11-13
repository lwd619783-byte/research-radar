"""The market-only interface probe archives explicitly synthetic V3 research."""
import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import acceptance_probe as probe
from historical_research import historical_data
from notion_fixtures import TEST_TOKEN


class InterfaceNotionResearchTests(unittest.TestCase):
    def test_no_notion_credentials_and_archive_binds_research_to_market_clock(self):
        clock = dt.datetime(2026, 11, 13, 14, 20, tzinfo=probe.build.BJ)
        historical, report = historical_data(clock.date(), fixed_clock=clock)
        self.assertFalse(report.errors)
        expected_symbols = {company['sym'] for company in historical['companies']}
        original_collect = probe.collect

        def collect(data, budget, **kwargs):
            self.assertEqual({company['sym'] for company in data['companies']}, expected_symbols)
            return original_collect(data, budget, snapshot_clock=clock, **kwargs)

        with TemporaryDirectory() as folder, contextlib.ExitStack() as stack:
            out = Path(folder) / 'archive'
            stack.enter_context(patch.dict(os.environ, {
                'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_RUN_ID': '1', 'GITHUB_SHA': 'a' * 40,
            }, clear=True))
            stack.enter_context(patch.object(sys, 'argv', ['acceptance_probe.py', '--out', str(out / 'receipt.json')]))
            network = stack.enter_context(patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')))
            stack.enter_context(patch.object(probe, 'collect', side_effect=collect))
            stack.enter_context(patch.object(probe.quotes, 'yahoo_daily', side_effect=probe.StopProbe('access_refused_stop_path')))
            for adapter in ('tencent_daily', 'yahoo_quotes', 'index_quote', 'fx', 'monthly'):
                stack.enter_context(patch.object(probe.quotes, adapter, side_effect=RuntimeError('offline test')))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(probe.main(), 0)
            verified = probe.bundle.verify_bundle(out)
            network.assert_not_called()

            self.assertIn('research-snapshot.json', verified['files'])
            for path in out.iterdir():
                self.assertNotIn(TEST_TOKEN.encode(), path.read_bytes())
            data = json.loads((out / 'DATA.json').read_bytes())
            receipt = json.loads((out / 'receipt.json').read_bytes())
            manifest = json.loads((out / 'manifest.json').read_bytes())
            snapshot = json.loads((out / 'research-snapshot.json').read_bytes())
            self.assertEqual(manifest['schemaVersion'], 2)
            self.assertFalse(manifest['publicationAuthorized'])
            self.assertTrue(data['meta']['reviewPreview'])
            self.assertEqual(data['meta']['notion']['source'], 'notion')
            self.assertEqual(receipt['researchInput'], 'notion-fixture')
            self.assertEqual(snapshot['builtAt'], clock.isoformat())
            self.assertEqual(receipt['fixedClock'], clock.isoformat())
            self.assertEqual(receipt['requestsMade'], 0)
            gates = receipt['publication']
            self.assertEqual((gates['financialRequired'], gates['financialVerified'], gates['financialPartial']), (42, 40, 2))
            self.assertIn('local_review_not_publishable', gates['blockers'])
            self.assertEqual(gates['coverage'], data['meta']['coverage'])
            self.assertTrue(any(row['status'] == 'access_blocked' for row in gates['coverage']))
            self.assertEqual({company['sym'] for company in data['companies']}, expected_symbols)


if __name__ == '__main__':
    unittest.main()
