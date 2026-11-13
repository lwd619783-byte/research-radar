"""Read the pinned pre-cleanup inputs for historical regression tests."""
from functools import cache
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    sys.path.insert(0, str(ROOT / 'radar/scripts'))
import build

SOURCE = 'ef223eeb0d63b1db951264c15bad55398cee5876'
INPUTS = ('config.toml', 'industries.toml', 'chokepoints.toml', 'companies.toml')


@cache
def historical_file(path):
    return subprocess.check_output(['git', 'show', f'{SOURCE}:{path}'], cwd=ROOT)


def historical_module(name):
    path = f'radar/scripts/{name}.py'
    module = ModuleType(f'historical_{name}')
    module.__file__ = str(ROOT / path)
    exec(compile(historical_file(path), module.__file__, 'exec'), vars(module))
    return module


schema = historical_module('schema')


@cache
def historical_directory():
    directory = TemporaryDirectory(prefix='radar-historical-research-')
    data = Path(directory.name) / 'data'
    data.mkdir()
    for name in INPUTS:
        (data / name).write_bytes(historical_file('radar/data/' + name))
    return directory


def historical_data(today, *, fixed_clock=None):
    return schema.load_and_validate(Path(historical_directory().name), ROOT, today, fixed_clock=fixed_clock)


def historical_builder():
    with patch.dict(sys.modules, {'schema': schema}):
        module = historical_module('build')
    module.load_and_validate = lambda radar, root, today, *, fixed_clock: historical_data(today, fixed_clock=fixed_clock)
    for name in ('assemble', 'render', 'fingerprint', 'release_blockers'):
        setattr(module, name, getattr(build, name))
    return module


if __name__ == '__main__':
    sys.exit(historical_builder().main())
