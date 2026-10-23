"""行情抓取：Yahoo Finance 为主，腾讯财经为 A 股 / 港股 / 指数的备用源。只用标准库。

所有函数失败时抛异常，由 build.py 统一决定是否回退到缓存。
"""
from __future__ import annotations

import datetime as dt
import http.cookiejar
import json
import math
import time
import urllib.parse
import urllib.request
import urllib.error
from zoneinfo import ZoneInfo

from integrity import observation_time, fx_bar_final
from snapshot import equity_bar_final, equity_bar_preopen

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
YH = ("https://query1.finance.yahoo.com",)


def positive(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def stamp(**values):
    return {**values, "schemaVersion": 2, "receivedAt": dt.datetime.now(dt.UTC).isoformat()}


def exchange_date(timestamp, meta):
    zone = meta.get("exchangeTimezoneName")
    tz = ZoneInfo(zone) if zone else dt.timezone(dt.timedelta(seconds=meta.get("gmtoffset", 0) or 0))
    return dt.datetime.fromtimestamp(timestamp, tz).date().isoformat()


class AccessRefused(RuntimeError):
    """Fixed code; never route an explicit refusal to a mirror."""


class Http:
    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.op.addheaders = [("User-Agent", UA), ("Accept", "application/json,text/plain,*/*")]
        self._crumb: str | None = None
        self._denied_paths = set()

    def get(self, url: str, tries: int = 3) -> bytes:
        parsed = urllib.parse.urlsplit(url)
        path = (parsed.netloc, parsed.path)
        if path in self._denied_paths:
            raise AccessRefused("source_access_refused")
        err: Exception | None = None
        for i in range(tries):
            try:
                with self.op.open(url, timeout=self.timeout) as r:
                    return r.read()
            except Exception as e:  # noqa: BLE001
                err = e
                code = getattr(e, "code", None)
                if code in (401, 403, 451):
                    self._denied_paths.add(path)
                    raise AccessRefused("source_access_refused") from None
                if code in (400, 404):
                    break
                time.sleep(1.5 * (i + 1) + (3 if code == 429 else 0))
        raise RuntimeError("source_transport_failed")

    def json(self, url: str, tries: int = 3):
        return json.loads(self.get(url, tries).decode("utf-8", "replace"))

    def yahoo(self, path: str, tries: int = 2):
        """Primary endpoint only: no mirror retry after an explicit refusal."""
        return self.json(YH[0] + path, tries)

    def crumb(self) -> str:
        if self._crumb is None:
            try:
                self.op.open("https://fc.yahoo.com", timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                if exc.code in (401,403,451): raise AccessRefused("source_access_refused") from None
                if exc.code != 404: raise RuntimeError("cookie_seed_failed") from None
            self._crumb = self.get(YH[0] + "/v1/test/getcrumb", 2).decode().strip()
            if not self._crumb or "<" in self._crumb:
                raise RuntimeError("拿不到 Yahoo crumb")
        return self._crumb


# ---------------- 日线 ----------------
def yahoo_daily(h: Http, sym: str, rng: str = "5y") -> dict:
    """返回 {"bars": [[date, close, adjclose], ...], "currency", "hi52", "src"}。"""
    j = h.yahoo(f"/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval=1d&includeAdjustedClose=true")
    res = (j.get("chart") or {}).get("result")
    if not res:
        raise SourceDataError('yahoo_chart_no_result')
    r = res[0]
    m = r.get("meta", {})
    off = m.get("gmtoffset", 0) or 0
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    cl = q.get("close") or []
    adj = ((r.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")) or []
    highs = q.get("high") or []
    bars: dict[str, list] = {}
    timestamps = {}
    for i, (t, c) in enumerate(zip(r.get("timestamp") or [], cl)):
        if not positive(c):
            continue
        a = adj[i] if i < len(adj) else None
        high = highs[i] if i < len(highs) else None
        d = exchange_date(t, m)
        bars[d] = [d, float(c), float(a) if positive(a) else None,
                   float(high) if positive(high) and high >= c else None]
        timestamps[d] = t
    if not bars:
        raise SourceDataError('yahoo_chart_empty_daily_bars')
    out = [bars[k] for k in sorted(bars)]
    # Do not splice realtime raw prices into an adjusted daily series.
    regular = (m.get("currentTradingPeriod") or {}).get("regular") or {}
    value = stamp(bars=out, currency=m.get("currency"), src="yahoo", asOf=out[-1][0],
                  priceBasis="raw", returnBasis="yahoo-adjclose", phase="unknown",
                  timezone=m.get('exchangeTimezoneName'), barTimestamps=timestamps,
                  finality={'method': 'provider-session-boundary',
                            'start': regular.get('start'), 'end': regular.get('end')})
    if equity_bar_final(out[-1][0], timestamps[out[-1][0]], value['timezone'], value['finality'], value['receivedAt']):
        value['phase'] = 'closed'
    elif equity_bar_preopen(out[-1][0], timestamps[out[-1][0]], value['timezone'], value['finality'], value['receivedAt']):
        value['phase'] = 'preopen'
    else:
        # Intraday classification requires valid provider boundaries too; missing
        # metadata stays unknown and cannot authorize historical trimming.
        try:
            start, end = regular['start'], regular['end']
            received = dt.datetime.fromisoformat(value['receivedAt']).timestamp()
            if (positive(start) and positive(end) and 0 < end-start <= 26*3600
                    and value['timezone'] and start <= timestamps[out[-1][0]] <= received < end):
                ZoneInfo(value['timezone'])
                value['phase'] = 'intraday'
        except (KeyError, TypeError, ValueError):
            pass
    return value


def tencent_code(sym: str) -> str | None:
    """688498.SS → sh688498；300308.SZ → sz300308；0522.HK → hk00522；^HSI → hkHSI。"""
    s = sym.upper()
    if s.endswith(".SS"):
        return "sh" + s[:-3]
    if s.endswith(".SZ"):
        return "sz" + s[:-3]
    if s.endswith(".BJ"):
        return "bj" + s[:-3]
    if s.endswith(".HK"):
        base = s[:-3]
        return "hk" + (base.zfill(5) if base.isdigit() else base)
    return {"^HSI": "hkHSI"}.get(s)


def tencent_metadata(node, code):
    qt=(node.get('qt') or {}).get(code)
    qt=qt if isinstance(qt,list) else []
    currency=qt[75] if len(qt)>75 and qt[75] in ('HKD','CNY','USD') else None
    return {'currency':currency, 'phase':'unknown', 'timezone':None,
            'providerLocalTime':qt[30] if len(qt)>30 else None,
            'metadataEvidence':{'currency':'payload.qt[75]' if currency else 'not_proven',
                                'timezone':'not_proven','phase':'not_proven'}}


def tencent_daily(h: Http, sym: str, n: int = 520) -> dict:
    code = tencent_code(sym)
    if not code:
        raise RuntimeError("腾讯不支持该代码")
    j = h.json(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},")
    node = (j.get("data") or {}).get(code) or {}
    rows = node.get("day") or []
    if not rows:
        raise RuntimeError("腾讯返回空 K 线")
    adjusted = {}
    try:
        qj = h.json(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq")
        qnode = (qj.get("data") or {}).get(code) or {}
        adjusted = {x[0]: float(x[2]) for x in qnode.get("qfqday", []) if len(x) > 2 and x[2] not in ("", None)}
    except Exception:
        pass
    bars = []
    for x in rows:
        if len(x) < 3 or x[2] in ("", None):
            continue
        close = float(x[2])
        if not positive(close):
            continue
        high = float(x[3]) if len(x) > 3 and x[3] not in ("", None) else None
        adj = adjusted.get(x[0])
        bars.append([x[0], close, adj if positive(adj) else None,
                     high if positive(high) and high >= close else None])
    bars.sort(key=lambda x: x[0])
    if not bars:
        raise RuntimeError("腾讯返回空 K 线")
    return stamp(bars=bars, src="tencent", asOf=bars[-1][0],
                 priceBasis="raw", returnBasis="tencent-qfq" if adjusted else None, **tencent_metadata(node,code))


def daily(h: Http, sym: str) -> dict:
    """Yahoo 优先；A 股 / 港股失败时用腾讯。"""
    try:
        return yahoo_daily(h, sym)
    except Exception as e1:  # noqa: BLE001
        if tencent_code(sym):
            try:
                return tencent_daily(h, sym)
            except Exception as e2:  # noqa: BLE001
                raise RuntimeError(f"Yahoo: {e1}; 腾讯: {e2}") from None
        raise


# ---------------- 估值字段（市值、PE） ----------------
def yahoo_quotes(h: Http, syms: list[str]) -> dict[str, dict]:
    """Fetch dated valuation fields; undated values cannot replace cache."""
    out: dict[str, dict] = {}
    try:
        crumb = h.crumb()
    except Exception:  # noqa: BLE001
        return out
    fields = "marketCap,trailingPE,epsTrailingTwelveMonths,regularMarketPrice,currency,regularMarketTime,marketState"
    for i in range(0, len(syms), 40):
        part = ",".join(syms[i:i + 40])
        try:
            j = h.yahoo(f"/v7/finance/quote?symbols={urllib.parse.quote(part)}&fields={fields}"
                        f"&crumb={urllib.parse.quote(crumb)}")
        except Exception:  # noqa: BLE001
            continue
        for q in (j.get("quoteResponse") or {}).get("result") or []:
            value = stamp(**{k: q.get(k) for k in ("marketCap", "trailingPE", "epsTrailingTwelveMonths", "regularMarketPrice", "currency", "regularMarketTime", "marketState")}, src="yahoo")
            if q.get('symbol') and observation_time('quote', value) is not None:
                out[q['symbol']] = value
    return out


# ---------------- 指数 ----------------
class SourceDataError(RuntimeError):
    """Fixed safe code plus numeric diagnostics, never a remote error body."""
    def __init__(self, code, count=0):
        self.code, self.count = code, count
        super().__init__(code)


def index_quote(h: Http, sym: str, tencent: str = "", source: str | None = None) -> dict:
    """Independent source mode preserves Yahoo semantic failures before fallback."""
    bars, diagnostics = [], []
    history = None
    provenance = {'src': 'yahoo', 'phase': 'unknown'}
    if source != 'tencent':
        try:
            d = yahoo_daily(h, sym, "1mo")
            history = d
            bars = d['bars']
            provenance = {k: d.get(k) for k in ('src', 'phase','timezone','currency')}
            # Pre-open proof only preserves older completed daily history. The
            # current index level keeps its existing unknown/partial status.
            if provenance['phase'] == 'preopen':
                provenance['phase'] = 'unknown'
            provenance['observedAt'] = d.get('barTimestamps',{}).get(d.get('asOf'))
            if len(bars) < 2:
                raise SourceDataError('yahoo_index_insufficient_daily_bars', len(bars))
        except Exception as exc:
            if source == 'yahoo': raise
            diagnostics.append({'source': 'yahoo', 'code': getattr(exc, 'code', type(exc).__name__)})
    code = tencent or tencent_code(sym)
    if source == 'tencent' or len(bars) < 2:
        if not code: raise SourceDataError('index_no_backup')
        provenance = {'src': 'tencent', 'phase': 'unknown'}
        history = None
        j = h.json(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,10,")
        node = (j.get('data') or {}).get(code) or {}
        provenance.update(tencent_metadata(node,code))
        rows = node.get('day') or node.get('qfqday') or []
        bars = [[x[0], float(x[2]), None, None] for x in rows if len(x) > 2]
    if len(bars) < 2:
        raise SourceDataError('index_insufficient_daily_bars', len(bars))
    if not valid_index_bars(bars):
        raise SourceDataError('index_invalid_prices_or_dates', len(bars))
    return stamp(price=bars[-1][1], chg=bars[-1][1] / bars[-2][1] - 1, date=bars[-1][0],
                 sourceDiagnostics=diagnostics, dailyHistory=history, **provenance)


def valid_index_bars(bars):
    from integrity import valid_bars
    return valid_bars(bars)


# ---------------- 汇率（每 1 美元兑多少当地货币） ----------------
FX_SYM = {"CNY": "CNY=X", "HKD": "HKD=X", "TWD": "TWD=X", "KRW": "KRW=X", "JPY": "JPY=X", "EUR": "EURUSD=X"}


def fx(h: Http, cur: str) -> dict:
    # Preserve actual dated daily closes. Realtime metadata may already be on
    # tomorrow's FX session while equities still refer to yesterday's close.
    j = h.yahoo(f"/v8/finance/chart/{urllib.parse.quote(FX_SYM[cur])}?range=1mo&interval=1d")
    r = j["chart"]["result"][0]
    meta = r.get('meta') or {}
    if not meta.get('exchangeTimezoneName'):
        raise ValueError('fx_timezone_missing')
    if meta.get('dataGranularity') != '1d':
        raise ValueError('fx_daily_interval_unconfirmed')
    period = (meta.get('currentTradingPeriod') or {}).get('regular') or {}
    finality = {'method': 'provider-session-boundary', 'start': period.get('start'), 'end': period.get('end')}
    received_at = dt.datetime.now(dt.UTC).isoformat()
    rates, timestamps = {}, {}
    for timestamp, price in zip(r.get('timestamp') or [], r['indicators']['quote'][0].get('close') or []):
        if positive(timestamp) and positive(price):
            day = exchange_date(timestamp, meta)
            if fx_bar_final(day, timestamp, meta['exchangeTimezoneName'], finality, received_at):
                rates[day] = [day, 1 / price if cur == 'EUR' else price, price]
                timestamps[day] = timestamp
    if not rates:
        raise ValueError('fx_final_daily_history_missing')
    history = [rates[day] for day in sorted(rates)]
    return stamp(value=history[-1][1], src='yahoo', asOf=history[-1][0], rates=history,
                 currency=cur, direction='USD-to-local', priceBasis='daily-close',
                 timezone=meta['exchangeTimezoneName'], rateTimestamps=timestamps, finality=finality)


# ---------------- 创业板指 ÷ 中证红利 月线 ----------------
def monthly(h: Http, tencent: str, yahoo: str) -> dict:
    """Return monthly history and a separately proven current daily observation."""
    try:
        j = h.json(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent},month,,,200,")
        node = (j.get("data") or {}).get(tencent) or {}
        rows = node.get("month") or node.get("qfqmonth") or []
        if len(rows) < 24:
            raise RuntimeError("腾讯月线不足")
        # Month labels do not date the closing value, even if formatted YYYY-MM-DD.
        result = stamp(bars=[[x[0][:7], float(x[2])] for x in rows], src="tencent",
                       periodDates=[x[0] for x in rows], asOf=None, current=None)
    except Exception:  # noqa: BLE001
        j = h.yahoo(f"/v8/finance/chart/{urllib.parse.quote(yahoo)}?range=max&interval=1mo")
        r = j["chart"]["result"][0]
        off = r["meta"].get("gmtoffset", 0) or 0
        m: dict[str, float] = {}
        for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]):
            if c is not None:
                m[dt.datetime.fromtimestamp(t + off, dt.UTC).strftime("%Y-%m")] = float(c)
        # Yahoo interval timestamps also label buckets, not observation dates.
        return stamp(bars=[[k, m[k]] for k in sorted(m)], src="yahoo",
                     periodTimestamps=r['timestamp'], asOf=None, current=None)
    try:
        j = h.json(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent},day,,,5,")
        days = (j.get('data') or {}).get(tencent, {}).get('day') or []
        daily = []
        for row in days:
            date = dt.date.fromisoformat(row[0]).isoformat()
            close = float(row[2])
            if date != row[0] or not positive(close):
                raise ValueError('Invalid current daily observation')
            daily.append((date, close))
        date, close = max(daily)
        current = {'date': date, 'close': close, 'src': 'tencent'}
        result['dailyObservations'] = [[d,v] for d,v in daily]
        # Never backfill a later month with an earlier daily observation.
        if result['bars'][-1][0] <= date[:7]:
            result['bars'] = [b for b in result['bars'] if b[0] < date[:7]] + [[date[:7], close]]
            result.update(asOf=date, current=current)
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError):
        pass
    return result
