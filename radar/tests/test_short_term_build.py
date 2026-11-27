"""The short-term snapshot enters the same object as the V3 market/research data."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_notion_v3 import run_fixture
import build
from output_scan import embedded_data

SAMPLE = build.RADAR / 'tests/fixtures/short_term_v4/sample_short_term_history.json'


class ShortTermBuildTests(unittest.TestCase):
    def test_injection_and_missing_input_preserve_every_v3_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            read = build.read_short_term

            def read_fixture(clock, *, environ):
                self.assertEqual(environ, {})
                return read(clock, path=path, environ=environ)

            with patch.object(build, 'read_short_term', side_effect=read_fixture):
                legacy = run_fixture()
                self.assertEqual(legacy['exit'], 0)
                self.assertNotIn('shortTerm', legacy['DATA'])
                history = json.loads(SAMPLE.read_bytes())
                # Use the previous closed session at the V3 fixture's frozen clock.
                day = history['days'][0]
                day.update(date='2026-10-20', shortDate='10/20', weekday='周二')
                history.update(days=[day], catalysts=[], generatedAt='2026-10-20T20:30:00+08:00')
                path.write_text(json.dumps(history, ensure_ascii=False), 'utf-8')
                combined = run_fixture()
        self.assertEqual(combined['exit'], 0)
        data = embedded_data(combined['html'].decode('utf-8'))
        self.assertEqual(data, combined['DATA'])
        self.assertEqual(data.pop('shortTerm')['days'][0]['date'], '2026-10-20')
        self.assertEqual(data, legacy['DATA'])
