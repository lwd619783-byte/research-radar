"""行情抓取：Yahoo Finance 为主，腾讯财经为 A 股 / 港股 / 指数的备用源。只用标准库。

所有函数失败时抛异常，由 build.py 统一决定是否回退到缓存。
"""
from __future__ import annotations

import datetime as dt
import http.cookiejar
import json
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
YH = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")


class Http:
    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.op.addheaders = [("User-Agent", UA), ("Accept", "application/json,text/plain,*/*")]
        self._crumb: str | None = None

    def get(self, url: str, tries: int = 3) -> bytes:
        err: Exception | None = None
        for i in range(tries):
            try:
                with self.op.open(url, timeout=self.timeout) as r:
                    return r.read()
            except Exception as e:  # noqa: BLE001
                err = e
                code = getattr(e, "code", None)
                if code in (400, 404):
                    break
                time.sleep(1.5 * (i + 1) + (3 if code == 429 else 0))
        raise RuntimeError(f"{url[:90]} → {err}")

    def json(self, url: str, tries: int = 3):
        return json.loads(self.get(url, tries).decode("utf-8", "replace"))

    def yahoo(self, path: str, tries: int = 2):
        """依次尝试 query1 / query2。"""
        last: Exception | None = None
        for host in YH:
            try:
                return self.json(host + path, tries)
            except Exception as e:  # noqa: BLE001
                last = e
        raise RuntimeError(str(last))

    def crumb(self) -> str:
        if self._crumb is None:
            try:
                self.op.open("https://fc.yahoo.com", timeout=self.timeout)
            except Exception:  # noqa: BLE001  该地址常返回 404，但会种下 cookie
                pass
            self._crumb = self.get(YH[0] + "/v1/test/getcrumb", 2).decode().strip()
            if not self._crumb or "<" in self._crumb:
                raise RuntimeError("拿不到 Yahoo crumb")
        return self._crumb


# ---------------- 日线 ----------------
def yahoo_daily(h: Http, sym: str, rng: str = "2y") -> dict:
    """返回 {"bars": [[date, close, adjclose], ...], "currency", "hi52", "src"}。"""
    j = h.yahoo(f"/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval=1d&includeAdjustedClose=true")
    res = (j.get("chart") or {}).get("result")
    if not res:
        raise RuntimeError(f"Yahoo 无数据：{(j.get('chart') or {}).get('error')}")
    r = res[0]
    m = r.get("meta", {})
    off = m.get("gmtoffset", 0) or 0
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    cl = q.get("close") or []
    adj = ((r.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")) or cl
    bars: dict[str, list] = {}
    for t, c, a in zip(r.get("timestamp") or [], cl, adj):
        if c is None:
            continue
        d = dt.datetime.fromtimestamp(t + off, dt.UTC).date().isoformat()
        bars[d] = [d, float(c), float(a if a is not None else c)]
    if not bars:
        raise RuntimeError("Yahoo 返回空 K 线")
    out = [bars[k] for k in sorted(bars)]
    # 盘中：chart 的最后一根可能滞后于 regularMarketPrice，按实时价覆盖当天
    rp, rt = m.get("regularMarketPrice"), m.get("regularMarketTime")
    if rp and rt:
        d = dt.datetime.fromtimestamp(rt + off, dt.UTC).date().isoformat()
        if d == out[-1][0]:
            ratio = out[-1][2] / out[-1][1] if out[-1][1] else 1
            out[-1] = [d, float(rp), float(rp) * ratio]
        elif d > out[-1][0]:
            out.append([d, float(rp), float(rp)])
    return {"bars": out, "currency": m.get("currency"), "hi52": m.get("fiftyTwoWeekHigh"), "src": "yahoo"}


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


def tencent_daily(h: Http, sym: str, n: int = 520) -> dict:
    code = tencent_code(sym)
    if not code:
        raise RuntimeError("腾讯不支持该代码")
    j = h.json(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},")
    node = (j.get("data") or {}).get(code) or {}
    rows = node.get("day") or node.get("qfqday") or []
    if not rows:
        raise RuntimeError("腾讯返回空 K 线")
    bars = [[x[0], float(x[2]), float(x[2])] for x in rows if len(x) > 2 and x[2] not in ("", None)]
    return {"bars": bars, "currency": None, "hi52": None, "src": "tencent"}


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
    """批量取 marketCap / trailingPE / fiftyTwoWeekHigh / currency。失败返回空 dict（用 toml 兜底）。"""
    out: dict[str, dict] = {}
    try:
        crumb = h.crumb()
    except Exception:  # noqa: BLE001
        return out
    fields = "marketCap,trailingPE,fiftyTwoWeekHigh,currency,regularMarketPrice"
    for i in range(0, len(syms), 40):
        part = ",".join(syms[i:i + 40])
        try:
            j = h.yahoo(f"/v7/finance/quote?symbols={urllib.parse.quote(part)}&fields={fields}"
                        f"&crumb={urllib.parse.quote(crumb)}")
        except Exception:  # noqa: BLE001
            continue
        for q in (j.get("quoteResponse") or {}).get("result") or []:
            out[q.get("symbol")] = {k: q.get(k) for k in ("marketCap", "trailingPE", "fiftyTwoWeekHigh", "currency")}
    return out


# ---------------- 指数 ----------------
def index_quote(h: Http, sym: str, tencent: str = "") -> dict:
    """返回 {"price", "chg", "date"}；chg 为相对前一交易日收盘的涨跌幅（小数）。"""
    bars: list = []
    try:
        bars = yahoo_daily(h, sym, "1mo")["bars"]
    except Exception:  # noqa: BLE001
        pass
    code = tencent or tencent_code(sym)
    if len(bars) < 2 and code:  # Yahoo 对部分中国指数只给 1 根或不给
        j = h.json(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,10,")
        node = (j.get("data") or {}).get(code) or {}
        rows = node.get("day") or node.get("qfqday") or []
        bars = [[x[0], float(x[2]), float(x[2])] for x in rows if len(x) > 2]
    if len(bars) < 2:
        raise RuntimeError("指数数据不足")
    return {"price": bars[-1][1], "chg": bars[-1][1] / bars[-2][1] - 1, "date": bars[-1][0]}


# ---------------- 汇率（每 1 美元兑多少当地货币） ----------------
FX_SYM = {"CNY": "CNY=X", "HKD": "HKD=X", "TWD": "TWD=X", "KRW": "KRW=X", "JPY": "JPY=X", "EUR": "EURUSD=X"}


def fx(h: Http, cur: str) -> float:
    j = h.yahoo(f"/v8/finance/chart/{urllib.parse.quote(FX_SYM[cur])}?range=5d&interval=1d")
    p = j["chart"]["result"][0]["meta"]["regularMarketPrice"]
    return 1 / p if cur == "EUR" else p


# ---------------- 创业板指 ÷ 中证红利 月线 ----------------
def monthly(h: Http, tencent: str, yahoo: str) -> list[list]:
    """返回 [["YYYY-MM", close], ...]。"""
    try:
        j = h.json(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent},month,,,200,")
        node = (j.get("data") or {}).get(tencent) or {}
        rows = node.get("month") or node.get("qfqmonth") or []
        if len(rows) < 24:
            raise RuntimeError("腾讯月线不足")
        return [[x[0][:7], float(x[2])] for x in rows]
    except Exception:  # noqa: BLE001
        j = h.yahoo(f"/v8/finance/chart/{urllib.parse.quote(yahoo)}?range=max&interval=1mo")
        r = j["chart"]["result"][0]
        off = r["meta"].get("gmtoffset", 0) or 0
        m: dict[str, float] = {}
        for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]):
            if c is not None:
                m[dt.datetime.fromtimestamp(t + off, dt.UTC).strftime("%Y-%m")] = float(c)
        return [[k, m[k]] for k in sorted(m)]
