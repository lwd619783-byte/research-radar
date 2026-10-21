"""Small factual projections of verified releases, never a new research opinion."""
import datetime as dt
import math


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def project(data, proof):
    rows = []
    for c in data['companies']:
        daily = c.get('provenance', {}).get('daily', {})
        f = c.get('provenance', {}).get('financial', {})
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
                                               'report_status', 'source_urls', 'verified_at')} | {
                                                   k: c.get(k) for k in ('revg', 'earng', 'gm')},
        })
    return {'generatedAt': data['meta']['generatedAt'], 'proof': proof, 'companies': rows,
            'coverage': [{k: x.get(k) for k in ('kind', 'symbol', 'metric', 'status')}
                         for x in data['meta'].get('coverage', [])]}


def history_with(previous, old_history):
    days = {}
    for item in [*old_history, previous]:
        clock = dt.datetime.fromisoformat(item['generatedAt'])
        if clock.tzinfo is None:
            raise ValueError('history_clock_without_timezone')
        day = clock.astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        if day not in days or item['generatedAt'] > days[day]['generatedAt']:
            days[day] = item
    return [days[k] for k in sorted(days)[-8:]]


def summarize(data, history):
    current = project(data, {})
    today = current['generatedAt'][:10]
    eligible = [x for x in history if x['generatedAt'] < current['generatedAt']]
    prior_days = [x for x in eligible if x['generatedAt'][:10] < today]
    baseline = max(prior_days or eligible, key=lambda x: x['generatedAt'], default=None)
    result = {'mode': 'previous_day' if prior_days else 'previous_update',
              'generatedAt': current['generatedAt'], 'baselineAt': None,
              'reports': [], 'calendar': [], 'restored': [], 'lost': [], 'prices': [],
              'excludedPrices': 0, 'sameDatePrices': 0,
              'pendingResearch': sum(review_pending(x, today)
                                     for x in [*data.get('industries', []), *data.get('chokepoints', []),
                                               data['meta'].get('weekly', {})])}
    if not baseline:
        return result | {'mode': 'unavailable'}
    result.update(baselineAt=baseline['generatedAt'], baselineProof=baseline['proof'])
    old = {c['id']: c for c in baseline['companies']}
    for c in current['companies']:
        p = old.get(c['id'])
        if not p:
            result['excludedPrices'] += 1
            continue
        f, pf = c['financial'], p['financial']
        if f.get('status') in ('verified', 'verified_partial') and (
                c['period'] != p['period'] or f != pf):
            result['reports'].append({'id': c['id'], 'name': c['name'], 'before': p['period'],
                                      'after': c['period'], 'status': f['status'],
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
    review = item.get('review') or {}
    if (review.get('status') != 'verified' or not review.get('source_url') or
            not review.get('verified_at') or not review.get('valid_until') or
            not review['verified_at'] <= day <= review['valid_until']):
        return True
    if item.get('week'):
        year, week, _ = dt.date.fromisoformat(day).isocalendar()
        return item['week'] != f'{year}-W{week:02d}'
    return False
