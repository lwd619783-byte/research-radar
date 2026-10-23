"""Offline CI failures reveal identifiers without publishing captured output."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from acceptance_probe import offline_failure_summary


class PreflightDiagnosticsTests(unittest.TestCase):
    def test_failure_and_error_identifiers_are_preserved_without_tracebacks(self):
        output = ('FAIL: test_alpha (test_alpha.Tests.test_alpha)\n'
                  'AssertionError: do-not-publish-response-content\n'
                  'ERROR: test_beta (test_beta.Tests.test_beta)\n')
        self.assertEqual(offline_failure_summary(output, 592), {
            'fatal': 'offline_tests_failed', 'tests': 592,
            'failedTests': ['test_alpha.Tests.test_alpha', 'test_beta.Tests.test_beta'],
            'rawOutputOmitted': True})

    def test_subtest_values_and_arbitrary_messages_are_not_exported(self):
        output = ('ERROR: test_alpha (test_alpha.Tests.test_alpha) (value="private response")\n'
                  'Traceback: private response\nFAIL: not-an-identifier (arbitrary response)\n')
        self.assertEqual(offline_failure_summary(output, 0)['failedTests'], [])
        self.assertNotIn('private', str(offline_failure_summary(output, 0)))

    def test_identifiers_are_deduplicated_and_bounded(self):
        output = '\n'.join(f'FAIL: test_{i} (test_example.Tests.test_{i})' for i in range(100))
        result = offline_failure_summary(output + '\n' + output, 100)
        self.assertEqual(len(result['failedTests']), 50)
        self.assertEqual(result['failedTests'][0], 'test_example.Tests.test_0')
        self.assertEqual(result['failedTests'][-1], 'test_example.Tests.test_49')
