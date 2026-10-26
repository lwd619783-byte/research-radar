"""Small factual projections of verified releases, never a new research opinion."""
import datetime as dt
import copy
import math


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


BEIJING = dt.timezone(dt.timedelta(hours=8))


def clock(value):
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('history_clock_without_timezone')
    return parsed


def local_day(value):
    return clock(value).astimezone(BEIJING).date().isoformat()


def project(data, proof, changes_today=None):
    rows = []
    for c in data['companies']:
        provenance = c.get('provenance') or {}
        daily = provenance.get('daily') or {}
        f = provenance.get('financial') or {}
        # Displayed price may be intraday. Only the admitted, completed daily close
        # and its own date/basis enter comparisons.
        close = (c.get('sc') or [None])[-1]
        earnings = c.get('earnings') or {}
        rows.append({k: c.get(k) for k in ('id', 'sym', 'name', 'cur', 'next', 'period')} | {
            'earnings': {'status': earnings.get('status') or 'unverified',
                         **{k: earnings.get(k) or '' for k in ('source_url', 'published_at', 'verified_at', 'timezone', 'time_note')}},
            'close': close if daily.get('phase') == 'closed' and numeric(close) else None,
            'date': c.get('metricAsOf') or c.get('ld'), 'source': daily.get('src'),
            'basis': daily.get('returnBasis'),
            'r1d': c.get('r1d'),
            'financial': {k: f.get(k) for k in ('status', 'basis', 'currency', 'published_at',
                                               'report_status', 'source_urls', 'verified_at',
                                               'evidence', 'entered_at', 'period_end')} | {
                                                   k: c.get(k) for k in ('revg', 'earng', 'gm')},
        })
    return {'generatedAt': data['meta']['generatedAt'], 'proof': proof, 'companies': rows,
            'industries': [{'name': row['name'], 's': copy.deepcopy(row.get('s'))}
                           for row in data.get('industries', [])],
            'changesToday': copy.deepcopy(changes_today),
            'coverage': [{k: x.get(k) for k in ('kind', 'symbol', 'metric', 'status')}
                         for x in data['meta'].get('coverage', [])]}


def history_with(previous, old_history):
    days = {}
    for item in [*old_history, previous]:
        day = local_day(item['generatedAt'])
        if day not in days or clock(item['generatedAt']) >= clock(days[day]['generatedAt']):
            days[day] = item
    return [days[k] for k in sorted(days)[-8:]]


def score_changes(current, previous):
    old = {row['name']: row.get('s') for row in previous.get('industries', [])}
    return [{'name': row['name'], 'before': old[row['name']], 'after': row['s']}
            for row in current.get('industries', [])
            if row['name'] in old and isinstance(old[row['name']], list)
            and len(old[row['name']]) == 4 and isinstance(row.get('s'), list)
            and len(row['s']) == 4 and row['s'] != old[row['name']]]


def changes_today(current, previous):
    """Accumulate observed transitions since Beijing midnight, by stable key.

    Unlike the older daily summary, this compares the immediately preceding
    successful publication. A reversion later the same day remains one observed
    change; missing prior identities are not treated as known previous values.
    """
    day = local_day(current['generatedAt'])
    sets = {key: set() for key in ('reports', 'confirmed', 'scores')}
    if previous is None:
        return {'date': day, **{key: [] for key in sets}}
    carry = previous.get('changesToday') or {}
    if local_day(previous['generatedAt']) == day and carry.get('date') == day:
        for key in sets:
            sets[key].update(value for value in carry.get(key, []) if isinstance(value, str))
    old = {row['id']: row for row in previous['companies']}
    for row in current['companies']:
        prior = old.get(row['id'])
        if prior is None:
            continue
        if row.get('period') != prior.get('period'):
            sets['reports'].add(row['id'])
        if ((row.get('earnings') or {}).get('status') == 'confirmed'
                and (prior.get('earnings') or {}).get('status') != 'confirmed'):
            sets['confirmed'].add(row['id'])
    sets['scores'].update(row['name'] for row in score_changes(current, previous))
    return {'date': day, **{key: sorted(values) for key, values in sets.items()}}


def summarize(data, history):
    current = project(data, {})
    today = local_day(current['generatedAt'])
    # DATA timestamps may be minute-precision. The verified previous release
    # can have the same displayed clock as a second run in that minute.
    eligible = [x for x in history if clock(x['generatedAt']) <= clock(current['generatedAt'])]
    prior_days = [x for x in eligible if local_day(x['generatedAt']) < today]
    baseline = max(prior_days or eligible, key=lambda x: clock(x['generatedAt']), default=None)
    latest = max(eligible, key=lambda x: clock(x['generatedAt']), default=None)
    result = {'mode': 'previous_day' if prior_days else 'previous_update',
              'generatedAt': current['generatedAt'], 'baselineAt': None,
              'reports': [], 'calendar': [], 'restored': [], 'lost': [], 'prices': [], 'scores': [],
              'today': changes_today(current, latest),
              'excludedPrices': 0, 'sameDatePrices': 0,
              'pendingResearch': sum(review_pending(x, today)
                                     for x in [*data.get('industries', []), *data.get('chokepoints', []),
                                               data['meta'].get('weekly', {})])}
    if not baseline:
        return result | {'mode': 'unavailable'}
    result.update(baselineAt=baseline['generatedAt'], baselineProof=baseline['proof'])
    result['scores'] = score_changes(current, baseline)
    old = {c['id']: c for c in baseline['companies']}
    for c in current['companies']:
        p = old.get(c['id'])
        if not p:
            result['excludedPrices'] += 1
            continue
        f, pf = c['financial'], p['financial']
        if (f.get('evidence') in ('source', 'partial') or f.get('status') in ('verified', 'verified_partial')) and (
                c['period'] != p['period'] or f != pf):
            result['reports'].append({'id': c['id'], 'name': c['name'], 'before': p['period'],
                                      'after': c['period'], 'status': f.get('evidence') or f.get('status'),
                                      'label': '财报期别变更' if c['period'] != p['period'] else '同一财报证据、数值或状态更新'})
        if c['next'] != p['next'] or c['earnings'] != p['earnings']:
            result['calendar'].append({'id': c['id'], 'name': c['name'], 'before': p['next'],
                                       'after': c['next'], 'status': (c['earnings'] or {}).get('status', 'unverified')})
        compatible = (numeric(c['close']) and numeric(p['close']) and p['close'] > 0 and numeric(c['r1d'])
                      and c['date'] and p['date'] and c['date'] >= p['date']
                      and all(c[k] and c[k] == p[k] for k in ('sym', 'cur', 'source', 'basis')))
        if not compatible:
            result['excludedPrices'] += 1
        elif c['date'] == p['date']:
            # Corrections to the same session are not a new day's price return.
            result['sameDatePrices'] += 1
        else:
            result['prices'].append({'id': c['id'], 'name': c['name'], 'beforeDate': p['date'],
                                     'afterDate': c['date'], 'before': p['close'], 'after': c['close'],
                                     'currency': c['cur'], 'change': c['r1d']})
    previous_coverage = {(r['kind'], r['symbol'], r['metric']): r for r in baseline['coverage']}
    for r in current['coverage']:
        p = previous_coverage.get((r['kind'], r['symbol'], r['metric']))
        if not p:
            continue
        if p['status'] not in ('complete', 'not_applicable') and r['status'] == 'complete':
            result['restored'].append(r)
        if p['status'] == 'complete' and r['status'] not in ('complete', 'not_applicable'):
            result['lost'].append(r)
    result['prices'].sort(key=lambda c: abs(c['change']), reverse=True)
    return result


def review_pending(item, day):
    if 'judgment' in item:
        return (item.get('judgment') or {}).get('label') != 'ai'
    review = item.get('review') or {}
    if (review.get('status') != 'verified' or not review.get('source_url') or
            not review.get('verified_at') or not review.get('valid_until') or
            not review['verified_at'] <= day <= review['valid_until']):
        return True
    if item.get('week'):
        year, week, _ = dt.date.fromisoformat(day).isocalendar()
        return item['week'] != f'{year}-W{week:02d}'
    return False
