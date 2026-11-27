"""Build both offline UI test pages from the V3 and V4 review fixtures."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from unittest.mock import patch

RADAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR / 'tests'))
from test_notion_v3 import run_fixture
import build

SAMPLE = RADAR / 'tests/fixtures/short_term_v4/sample_short_term_history.json'


def build_pages(history, destination):
    # Local production snapshots must never influence a deterministic replay.
    with patch.object(build, 'read_short_term', return_value=None):
        result = run_fixture()
    if result['exit'] or not result['DATA']['meta']['reviewPreview']:
        raise ValueError('V3 review fixture failed')
    data = result['DATA']
    clock = datetime.fromisoformat(json.loads(history.read_bytes())['generatedAt'])
    short = build.read_short_term(clock, path=history, environ={})
    if not short or not short['days']:
        raise ValueError('V4 fixture contains no usable sessions')
    for name, page_data in [('legacy', data), ('short', {**data, 'shortTerm': short})]:
        directory = destination / name
        build.render(page_data, directory)
        (directory / 'DATA.json').write_text(json.dumps(page_data, ensure_ascii=False), 'utf-8')
    print(f'Offline review: {len(short["days"])} sessions, {len(short["catalysts"])} catalysts')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', type=Path, default=SAMPLE)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build_pages(args.history, args.out)
