"""Run the local collector and V3 release verifier on the same offline snapshot."""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from rehearse_v3_release import rehearse
import build
import collect_short_term
from output_scan import embedded_data, scan_output
from short_term_collector.market import prior_session


def replay(out):
    # The V3 archive has a frozen October clock. Move the synthetic input
    # together as a single session so both planes can use their real date gates.
    fixture = json.loads(collect_short_term.RAW_FIXTURE.read_bytes())
    cases = json.loads((build.RADAR / 'tests/fixtures/notion_v3/cases.json').read_bytes())
    day = prior_session(datetime.fromisoformat(cases['as_of']).date())
    original = date.fromisoformat(fixture['date'])
    delta = day - original
    fixture['date'] = fixture['market']['date'] = fixture['radar']['meta']['today'] = day.isoformat()
    for group in ('stocks', 'industries', 'concepts', 'intraday'):
        for row in fixture['market'][group]:
            row['date'] = day.isoformat()
            if row.get('listed'):
                row['listed'] = (date.fromisoformat(row['listed']) + delta).isoformat()
    for platform in fixture['egoCaptures'].values():
        for comment in platform['comments']:
            comment['date'] = day.isoformat()
    for event in fixture['market']['events']:
        start = date.fromisoformat(event['startDate']) + delta
        event.update(startDate=start.isoformat(), dateLabel=f'{start.month}/{start.day}')
    with tempfile.TemporaryDirectory(prefix='short-term-rehearsal-') as directory:
        raw = Path(directory) / 'raw.json'
        history = Path(directory) / 'history.json'
        raw.write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        with patch('socket.socket', side_effect=AssertionError('offline collector opened a socket')):
            rc = collect_short_term.main(['--offline-fixture', str(raw), '--output', str(history)])
        if rc:
            raise ValueError('offline_collection_failed')
        short = json.loads(history.read_bytes())
        read = build.read_short_term
        def inject_history(clock, *, environ):
            return read(clock, environ=environ, path=history)
        with patch.object(build, 'read_short_term', side_effect=inject_history):
            receipt = rehearse(out)
    html = (out / 'release/public/index.html').read_text('utf-8')
    data = embedded_data(html)
    issues = scan_output(html, data, site_dir=build.RADAR / 'site')
    if (issues or data.get('shortTerm') != short or len(short['days'][0]['ego']['platforms']) != 5
            or not receipt['verified'] or receipt['publicationAuthorized']):
        raise ValueError('short_term_release_rehearsal_failed')
    return {'verified': True, 'offline': True, 'publicationAuthorized': False,
            'date': day.isoformat(), 'platforms': 5, 'siteScanIssues': issues}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    print(json.dumps(replay(parser.parse_args().out.resolve()), ensure_ascii=False))
