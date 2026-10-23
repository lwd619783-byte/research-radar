"""Explicitly synthetic quote adapter for offline production-pipeline rehearsals."""
import copy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from notion_fixtures import FIXTURES, read_json


def fixture_market(data, budget, *, snapshot_sink, market_sink=None, snapshot_clock=None):
    """Replay the provided quote snapshot; never claim transport was performed."""
    quotes = copy.deepcopy(read_json(FIXTURES / 'quotes/data-2026-10-21.json'))
    requested = {company['sym'] for company in data['companies']}
    quotes['companies'] = [company for company in quotes['companies'] if company['sym'] in requested]
    quotes['meta']['reviewPreview'] = True
    snapshot_sink.update(data=quotes, clock=snapshot_clock)
    if market_sink is not None:
        market_sink.clear()
    session = {'failure': None, 'requests': [], 'batches': [], 'returned': len(quotes['companies']),
               'expectedBatchSizes': [len(data['companies'][offset:offset + 40]) for offset in range(0, len(data['companies']), 40)],
               'cookieAvailable': False, 'crumbAvailable': False}
    return [], {}, session, {'blockers': [], 'missingDailyCount': 0, 'staleDailyCount': 0}
