"""A real Git checkout must preserve the pinned rollback patch on Windows."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATCH_PATH = Path('radar/tools/v2_rollback/v2-rollback-compatibility.patch')
spec = importlib.util.spec_from_file_location('rollback_checkout_tool', ROOT / 'radar/tools/v2_rollback/prepare.py')
rollback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollback)


class RollbackCheckoutTests(unittest.TestCase):
    def git(self, *args, cwd):
        completed = subprocess.run(['git', *args], cwd=cwd, capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors='replace'))
        return completed.stdout

    def test_autocrlf_checkout_preserves_exact_patch_bytes_and_hash(self):
        expected = (ROOT / PATCH_PATH).read_bytes()
        self.assertEqual(hashlib.sha256(expected).hexdigest(), rollback.PATCH_SHA256)
        with tempfile.TemporaryDirectory(prefix='rollback-git-checkout-') as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            self.git('init', '-q', '-b', 'test', cwd=source)
            self.git('config', 'core.autocrlf', 'true', cwd=source)
            self.git('config', 'user.name', 'Offline checkout regression', cwd=source)
            self.git('config', 'user.email', 'offline-test@example.invalid', cwd=source)
            (source / '.gitattributes').write_bytes((ROOT / '.gitattributes').read_bytes())
            target = source / PATCH_PATH
            target.parent.mkdir(parents=True)
            target.write_bytes(expected)
            self.git('add', '--', '.gitattributes', PATCH_PATH.as_posix(), cwd=source)
            self.git('-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'Local checkout fixture', cwd=source)
            checkout = root / 'checkout'
            self.git('clone', '-q', '--no-hardlinks', '-c', 'core.autocrlf=true',
                     str(source), str(checkout), cwd=root)
            self.assertEqual(self.git('config', 'core.autocrlf', cwd=checkout).strip(), b'true')
            self.assertEqual(self.git('check-attr', 'eol', '--', PATCH_PATH.as_posix(), cwd=checkout).decode().strip(),
                             PATCH_PATH.as_posix() + ': eol: lf')
            actual = (checkout / PATCH_PATH).read_bytes()
            self.assertEqual(actual, expected)
            self.assertNotIn(b'\r\n', actual)
            self.assertEqual(hashlib.sha256(actual).hexdigest(), rollback.PATCH_SHA256)
            self.assertEqual(self.git('status', '--porcelain', cwd=checkout), b'')


if __name__ == '__main__':
    unittest.main()
