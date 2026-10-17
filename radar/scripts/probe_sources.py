"""Opt-in read-only smoke probe. No fallback host, credentials, or retries."""
import datetime as dt
import json
from pathlib import Path
import quotes


class SingleAttempt(quotes.Http):
    def __init__(self):
        super().__init__(timeout=12)
    def get(self, url, tries=1):
        with self.op.open(url, timeout=self.timeout) as response:
            return response.read()
    def yahoo(self, path, tries=1):
        return self.json(quotes.YH[0] + path, 1)


def main():
    report = {'checkedAt': dt.datetime.now(dt.UTC).isoformat(), 'readOnly': True, 'results': []}
    for source, symbol, fn in [('yahoo', 'NVDA', quotes.yahoo_daily), ('tencent', '688498.SS', quotes.tencent_daily)]:
        try:
            result = fn(SingleAttempt(), symbol)
            bars = result['bars']
            report['results'].append({'source': source, 'symbol': symbol, 'status': 'ok',
                'firstDate': bars[0][0], 'lastDate': bars[-1][0], 'count': len(bars),
                'adjustedCount': sum(b[2] is not None for b in bars), 'highCount': sum(b[3] is not None for b in bars),
                'returnBasis': result.get('returnBasis'), 'phase': result.get('phase')})
        except Exception as exc:
            report['results'].append({'source': source, 'symbol': symbol, 'status': 'failed',
                                      'errorType': type(exc).__name__, 'error': str(exc)[:200]})
            # A network/access refusal is not a prompt to change hosts or proxies.
            break
    out = Path(__file__).resolve().parents[2] / 'audit' / 'source-probe.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
