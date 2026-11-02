"""Offline CI failures reveal identifiers without publishing captured output."""
import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import acceptance_probe as probe
from acceptance_probe import offline_failure_summary


class PreflightDiagnosticsTests(unittest.TestCase):
    def test_failure_and_error_identifiers_are_preserved_without_tracebacks(self):
        output = ('FAIL: test_alpha (test_alpha.Tests.test_alpha)\n'
                  'AssertionError: do-not-publish-response-content\n'
                  'ERROR: test_beta (test_beta.Tests.test_beta)\n')
        allowed = {'test_alpha.Tests.test_alpha', 'test_beta.Tests.test_beta'}
        self.assertEqual(offline_failure_summary(output, 592, allowed), {
            'fatal': 'offline_tests_failed', 'tests': 592,
            'failedTests': ['test_alpha.Tests.test_alpha', 'test_beta.Tests.test_beta'],
            'rawOutputOmitted': True})

    def test_subtest_values_and_arbitrary_messages_are_not_exported(self):
        output = ('ERROR: test_alpha (test_alpha.Tests.test_alpha) (value="private response")\n'
                  'Traceback: private response\nFAIL: not-an-identifier (arbitrary response)\n')
        allowed = {'test_alpha.Tests.test_alpha'}
        self.assertEqual(offline_failure_summary(output, 0, allowed)['failedTests'], [])
        self.assertNotIn('private', str(offline_failure_summary(output, 0, allowed)))

    def test_identifiers_are_deduplicated_and_bounded(self):
        output = '\n'.join(f'FAIL: test_{i} (test_example.Tests.test_{i})' for i in range(100))
        allowed = {f'test_example.Tests.test_{i}' for i in range(100)}
        result = offline_failure_summary(output + '\n' + output, 100, allowed)
        self.assertEqual(len(result['failedTests']), 50)
        self.assertEqual(result['failedTests'][0], 'test_example.Tests.test_0')
        self.assertEqual(result['failedTests'][-1], 'test_example.Tests.test_49')

    def test_real_unittest_traceback_cannot_forge_an_undiscovered_identifier(self):
        class SyntheticFailure(unittest.TestCase):
            def test_failure(self):
                self.fail('synthetic private response\n'
                          'FAIL: test_shadow (test_response.PrivateValueABC123.test_shadow)')
        SyntheticFailure.__qualname__ = 'SyntheticFailure'
        victim = SyntheticFailure('test_failure')
        output = io.StringIO()
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(victim)
        self.assertEqual(len(result.failures), 1)
        with patch.object(unittest.TestLoader, 'discover', return_value=unittest.TestSuite([victim])):
            allowed = probe.offline_test_ids()
        summary = offline_failure_summary(output.getvalue(), result.testsRun, allowed)
        self.assertEqual(summary['failedTests'], [victim.id()])
        self.assertNotIn('PrivateValueABC123', json.dumps(summary))
        self.assertEqual(offline_failure_summary(output.getvalue(), 1, frozenset())['failedTests'], [])

    def test_discovery_unwraps_nested_suites_once_without_running_test_methods(self):
        calls = []
        class DiscoverOnly(unittest.TestCase):
            def test_do_not_execute(self):
                calls.append('executed')
        case = DiscoverOnly('test_do_not_execute')
        suite = unittest.TestSuite([unittest.TestSuite([case])])
        with patch.object(unittest.TestLoader, 'discover', return_value=suite) as discover:
            self.assertEqual(probe.offline_test_ids(), frozenset({case.id()}))
            discover.assert_called_once_with(str(probe.ROOT / 'radar/tests'))
        self.assertEqual(calls, [])

    def test_discovery_exception_or_loader_errors_return_an_empty_allowlist(self):
        with patch.object(unittest.TestLoader, 'discover', side_effect=RuntimeError('private detail')) as discover:
            self.assertEqual(probe.offline_test_ids(), frozenset())
            discover.assert_called_once()
        loader = unittest.TestLoader()
        loader.errors.append('private import failure')
        with patch.object(unittest, 'TestLoader', return_value=loader), \
                patch.object(loader, 'discover', return_value=unittest.TestSuite()) as discover:
            self.assertEqual(probe.offline_test_ids(), frozenset())
            discover.assert_called_once()

    def test_preflight_failure_still_blocks_and_discovers_once_for_diagnostics(self):
        identifier = 'test_alpha.Tests.test_alpha'
        report = SimpleNamespace(errors=[], warnings=[])
        for code, count in ((1, 60), (0, 54)):
            output = f'FAIL: test_alpha ({identifier})\nRan {count} tests\n'.encode()
            process = SimpleNamespace(returncode=code, stdout=b'', stderr=output)
            log = io.StringIO()
            with self.subTest(code=code, count=count), \
                    patch.object(probe.build, 'load_and_validate', return_value=({}, report)), \
                    patch.object(probe.subprocess, 'run', return_value=process), \
                    patch.object(probe, 'offline_test_ids', return_value={identifier}) as discover, \
                    contextlib.redirect_stderr(log):
                with self.assertRaisesRegex(probe.StopProbe, 'offline_tests_failed'):
                    probe.preflight()
                discover.assert_called_once_with()
            self.assertEqual(json.loads(log.getvalue()), {
                'fatal': 'offline_tests_failed', 'tests': count,
                'failedTests': [identifier], 'rawOutputOmitted': True})

    def test_successful_preflight_never_discovers_diagnostics(self):
        report = SimpleNamespace(errors=[], warnings=[])
        process = SimpleNamespace(returncode=0, stdout=b'', stderr=b'Ran 60 tests\nOK\n')
        with patch.object(probe.build, 'load_and_validate', return_value=({}, report)), \
                patch.object(probe.subprocess, 'run', return_value=process), \
                patch.object(probe, 'offline_test_ids', side_effect=AssertionError('unexpected discovery')) as discover:
            self.assertEqual(probe.preflight(), {'tests': 60, 'schemaWarnings': 0, 'schemaErrors': 0})
            discover.assert_not_called()
