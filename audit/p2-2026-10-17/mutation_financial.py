"""Deliberately disable the financial gate in memory; the independent test must fail."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(r'C:\Users\10750\Documents\Codex\2026-10-17\task\radar-local-audit')
sys.path.insert(0, str(ROOT/'radar/tests'))
import test_review_regressions as regression

suite = unittest.TestSuite([regression.CompleteMainTests('test_financial_gate_alone')])
with patch.object(regression.build, 'financial_status', return_value='verified'):
    result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
