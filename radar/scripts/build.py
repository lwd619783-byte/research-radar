#!/usr/bin/env python3
"""投研雷达构建脚本：读取 radar/data/*.toml → 抓行情 → 生成单文件 index.html。

用法（在仓库根目录运行）：
  python radar/scripts/build.py --check      只校验数据，不联网（改完 toml 先跑这个）
  python radar/scripts/build.py              抓行情并生成 radar/dist/investment-radar/
  python radar/scripts/build.py --offline    不联网，只用缓存行情（调样式时用）
  python radar/scripts/build.py --force      即使行情没变也标记为需要部署

退出码：0 成功；1 数据校验失败；2 行情缺失过多（为避免发布残缺页面而中止）。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quotes  # noqa: E402
from schema import load_and_validate  # noqa: E402
from integrity import fresh_record, valid_bars, financial_status, release_blockers, number, observation_time, dated_fx, pe_status

RADAR = Path(__file__).resolve().parents[1]
REPO = RADAR.parent
BJ = ZoneInfo("Asia/Shanghai")
MAX_MISSING = 0.30


def log(*a) -> None:
    print(*a, flush=True)


def sig4(v):
    """保留 4 位有效数字，压缩体积。"""
    if v is None or v == 0:
        return v
    d = max(0, 3 - int(math.floor(math.log10(abs(v)))))
    return round(v, d) if d > 0 else int(round(v))


def r4(v, n=4):
    return None if v is None else round(v, n)


# ---------------- 指标计算 ----------------
def metrics(bars: list[list]) -> dict:
    """bars = [[date, close, adjclose], ...]（升序）。收益率用复权价，价格/走势图用原始收盘价。"""
    if not valid_bars(bars):
        return {}
    a = [b[2] for b in bars]
    last, ld = a[-1], bars[-1][0]

    def ret(n):
        return last / a[-1 - n] - 1 if len(a) > n and last is not None and a[-1 - n] else None

    base = [b[2] for b in bars if b[0][:4] < ld[:4]]
    cutoff = dt.date.fromisoformat(ld) - dt.timedelta(weeks=52)
    win = [b for b in bars if b[0] > cutoff.isoformat()]
    high = max(b[3] for b in win) if bars[0][0] <= cutoff.isoformat() and all(b[3] is not None for b in win) else None
    d0 = dt.date.fromisoformat(bars[0][0])
    sd, prev = [], d0
    for b in bars:
        cur = dt.date.fromisoformat(b[0])
        sd.append((cur - prev).days)
        prev = cur
    return {
        "price": round(bars[-1][1], 3 if bars[-1][1] < 10 else 2), "r1d": r4(ret(1), 5), "r5": r4(ret(5)), "r20": r4(ret(20)), "r60": r4(ret(60)),
        "ytd": r4(last / base[-1] - 1) if base and base[-1] and last is not None else None,
        "dd52": r4(bars[-1][1] / high - 1) if high else None,
        "hi52": high, "ld": ld,
        "s0": d0.isoformat(), "sd": sd, "sc": [sig4(b[1]) for b in bars],
        "history": {"count": len(bars), "firstDate": bars[0][0], "lastDate": ld,
                    "days": (dt.date.fromisoformat(ld) - d0).days,
                    "high52Available": high is not None},
    }


def ratio_block(cyb: list[list], hl: list[list], today: dt.date | None = None) -> dict | None:
    """创业板指 ÷ 中证红利 月度比值。分位只和「已走完的月份」比较（当月未走完）。"""
    today = today or dt.datetime.now(BJ).date()
    current_month = today.strftime('%Y-%m')
    c, h = dict(cyb), dict(hl)
    months = sorted(m for m in set(c) & set(h) if m <= current_month and number(c[m]) and number(h[m]) and c[m] > 0 and h[m] > 0)
    if not months:
        return None
    series = [[m, round(c[m] / h[m], 4)] for m in months]
    cur = series[-1][1]
    full = [c[m] / h[m] for m in months if m < current_month]
    expected = [f'{(today.year * 12 + today.month - 1 - i) // 12:04}-{(today.year * 12 + today.month - 1 - i) % 12 + 1:02}' for i in range(1, 121)]
    if not set(expected).issubset(months):
        return None
    m60, m120 = full[-60:], full[-120:]
    current_value = c[months[-1]] / h[months[-1]]
    n60, n120 = sum(v < current_value for v in m60), sum(v < current_value for v in m120)
    return {"series": series, "cur": cur, "cyb": round(c[months[-1]], 2), "hl": round(h[months[-1]], 2),
            "p60": n60 / len(m60), "p120": n120 / len(m120), "n60": n60, "n120": n120,
            "asOfMonth": months[-1], "completedMonths": len(full),
            "uiCompatible": months[-1] == current_month and max(m120) > min(m120)}


def asof_label(asof: str, now: dt.datetime) -> str:
    d = dt.date.fromisoformat(asof)
    md = f"{d.month}/{d.day}"
    # Release gate requires a confirmed common closing date; never use build time.
    return f"{md} 收盘"


# ---------------- 抓取 ----------------
def fetch_all(data: dict, cache: dict, offline: bool) -> tuple[dict, list[str]]:
    cfg = data["config"]
    syms = [c["sym"] for c in data["companies"]]
    notes: list[str] = []
    fresh = {"daily": {}, "quote": {}, "index": {}, "fx": {}, "ratio": {}}
    if offline:
        fresh["offline"] = True
        return fresh, ["--offline：全部使用缓存"]
    ratio_cfg = cfg["ratio"] or {}
    jobs = {}
    def request(fn, *args):
        return fn(quotes.Http(), *args)
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for s in syms:
            jobs[ex.submit(request, quotes.daily, s)] = ("daily", s)
        for x in cfg["indices"]:
            jobs[ex.submit(request, quotes.index_quote, x["symbol"], x.get("tencent", ""))] = ("index", x["symbol"])
        curs = sorted({c["cur"] for c in data["companies"]} - {"USD"})
        for cur in curs:
            jobs[ex.submit(request, quotes.fx, cur)] = ("fx", cur)
        for key, tx, yh in (("cyb", ratio_cfg.get("growth_tencent", "sz399006"), ratio_cfg.get("growth_yahoo", "399006.SZ")),
                            ("hl", ratio_cfg.get("dividend_tencent", "sh000922"), ratio_cfg.get("dividend_yahoo", "000922.SS"))):
            jobs[ex.submit(request, quotes.monthly, tx, yh)] = ("ratio", key)
        for f in cf.as_completed(jobs):
            kind, key = jobs[f]
            try:
                fresh[kind][key] = f.result()
            except Exception as e:  # noqa: BLE001
                notes.append(f"{kind} {key} 抓取失败：{str(e)[:160]}")
    fresh["quote"] = quotes.yahoo_quotes(quotes.Http(), syms)
    if not fresh["quote"]:
        notes.append("Yahoo 市值/PE 接口不可用；仅接受有时效凭证的缓存，禁用无日期 fallback")
    return fresh, notes


def merge(fresh: dict, cache: dict) -> dict:
    """新数据覆盖缓存；没抓到的保留缓存（之后标记为 stale）。"""
    out = {}
    for k in ("daily", "quote", "index", "fx", "ratio"):
        out[k] = dict(cache.get(k, {}))
        for key, value in fresh.get(k, {}).items():
            old = out[k].get(key)
            observed, previous = observation_time(k, value), observation_time(k, old)
            if observed is None or (previous is not None and observed < previous):
                continue
            out[k][key] = value
    return out


# ---------------- 组装 DATA ----------------
def assemble(data: dict, mk: dict, fresh: dict, now: dt.datetime) -> tuple[dict, list[str], list[str]]:
    cfg = data["config"]
    fx = {"USD": 1.0}
    fx_meta = {}

    stale, missing, cos = [], [], []
    blockers, market_dates, issues = [], {}, []
    for c in data["companies"]:
        s = c["sym"]
        d = mk["daily"].get(s)
        usable = (isinstance(d, dict) and d.get('schemaVersion') == 2 and d.get('priceBasis') == 'raw'
                  and valid_bars(d.get('bars')) and d.get('asOf') == d['bars'][-1][0])
        m = metrics(d['bars']) if usable else {}
        if not usable:
            missing.append(c["name"])
            issues.append({'symbol': s, 'kind': 'daily', 'status': 'missing_or_legacy'})
        elif d is not fresh['daily'].get(s) or not fresh_record(d, now, m['ld'], c['mkt']):
            stale.append(c["name"])
            m["stale"] = True
            issues.append({'symbol': s, 'kind': 'daily', 'status': 'stale'})
        if usable:
            market_dates.setdefault(c['mkt'], set()).add(m['ld'])
            if d.get('phase') != 'closed':
                blockers.append('unconfirmed_close_or_intraday_needs_label_approval')
            if m.get('stale'):
                # Ticker/aggregates have no per-row stale marker in frozen frontend.
                blockers.append('stale_quotes_not_safe_in_all_frozen_views')
            if len(d['bars']) < 120 or (dt.date.fromisoformat(m['ld']) - dt.date.fromisoformat(d['bars'][0][0])).days < 731:
                issues.append({'symbol': s, 'kind': 'history', 'status': 'short_history'})
        q = mk["quote"].get(s) or {}
        quote_date = None
        try:
            from integrity import ZONES
            observed = observation_time('quote', q)
            if observed is not None:
                quote_date = observed.astimezone(ZoneInfo(ZONES[c['mkt']])).date().isoformat()
        except (KeyError, TypeError, ValueError, OSError):
            pass
        if not quote_date or not fresh_record(q, now, quote_date, c['mkt']) or quote_date != m.get('ld'):
            q = {}
        # Quote/price currency is independent of the financial reporting currency.
        cur = (d or {}).get('currency') or c['cur']
        valuation_currency_ok = q.get('currency') == cur
        mcap = q.get("marketCap")
        selected_fx = ({'value': 1., 'asOf': quote_date, 'src': 'USD-identity', 'direction': 'USD-to-local'}
                       if cur == 'USD' and quote_date else dated_fx(mk['fx'].get(cur), cur, quote_date, now))
        mcap_usd = round(mcap / selected_fx['value'] / 1e8, 1) if quotes.positive(mcap) and valuation_currency_ok and selected_fx else None
        pe = q.get("trailingPE")
        pe_state = pe_status(pe)
        pe = round(pe, 1) if quotes.positive(pe) else None
        hi52 = m.get("hi52")
        row = {k: c[k] for k in ("id", "name", "code", "sym", "mkt", "role", "ind", "cp", "revg", "earng", "gm",
                                 "period", "flash", "view", "next", "url")}
        row.update({"cur": cur, "pe": pe, "mcapUSD": mcap_usd,
                    "price": None, "r1d": None, "r5": None, "r20": None, "r60": None, "ytd": None, "dd52": None,
                    "s0": None, "sd": [], "sc": [], "ld": None, "history": {"count": 0}})
        row.update(m)
        row["hi52"] = round(hi52, 3 if hi52 < 10 else 2) if hi52 else None
        status = financial_status(c.get('financial'), now.date())
        row['provenance'] = {'daily': {k: (d or {}).get(k) for k in ('src', 'asOf', 'receivedAt', 'returnBasis', 'phase')},
                             'valuation': {'source': q.get('src'), 'asOf': quote_date if q else None,
                                           'receivedAt': q.get('receivedAt'), 'observedAt': q.get('regularMarketTime'),
                                           'status': 'available' if q else 'missing', 'peStatus': pe_state,
                                           'currency': q.get('currency'), 'currencyMatches': valuation_currency_ok,
                                           'fx': selected_fx,
                                           'marketCapStatus': 'available' if mcap_usd is not None else 'missing_or_incompatible'},
                             'financial': {**c.get('financial', {}), 'status': status}}
        if status != 'verified':
            for key in ('revg', 'earng', 'gm'):
                row[key] = None
            issues.append({'symbol': s, 'kind': 'financial', 'status': status})
            blockers.append('financial_evidence_incomplete')
        fin = row['provenance']['financial']
        if fin.get('profit_comparison') in ('turnaround', 'loss_base', 'not_disclosed'):
            row['earng'] = None
        row['financialSignalEligible'] = (status == 'verified' and fin.get('basis') == 'single_quarter'
            and fin.get('report_status') == 'final' and fin.get('profit_comparison') == 'comparable'
            and all(number(row[k]) for k in ('revg', 'earng', 'gm')))
        row['financialRevenueComparable'] = (status == 'verified' and fin.get('basis') == 'single_quarter'
            and fin.get('report_status') == 'final')
        # Original free-text flash has no independent source/date contract.
        row['flashStatus'] = 'unverified'
        if mcap_usd is None:
            issues.append({'symbol': s, 'kind': 'valuation', 'status': 'market_cap_unavailable'})
        if pe_state != 'available':
            issues.append({'symbol': s, 'kind': 'valuation', 'status': 'pe_' + pe_state})
        cos.append(row)

    a_dates = [c["ld"] for c in cos if c["mkt"] == "A股" and c["ld"]]
    all_dates = [c["ld"] for c in cos if c["ld"]]
    asof = min(all_dates) if all_dates else None
    for cur, record in mk['fx'].items():
        selected = dated_fx(record, cur, asof, now)
        if selected:
            fx[cur] = selected['value']
            fx_meta[cur] = {k: selected.get(k) for k in ('src', 'asOf', 'receivedAt', 'direction')}
    if len(set(all_dates)) != 1:
        blockers.append('mixed_or_missing_market_dates_need_label_approval')

    idx = []
    for x in cfg["indices"]:
        v = mk["index"].get(x["symbol"])
        if (isinstance(v, dict) and v.get('date') and fresh_record(v, now, v['date'])
                and number(v.get('price')) and v['price'] > 0 and number(v.get('chg'))):
            idx.append({"name": x["name"], "price": round(v["price"], 2),
                        "chg": round(v["chg"], 5), 'asOf': v['date'], 'receivedAt': v['receivedAt'], 'source': v.get('src')})
            if v['date'] != asof or v.get('phase') != 'closed':
                blockers.append('index_date_or_phase_needs_label_approval')
        else:
            issues.append({'symbol': x['symbol'], 'kind': 'index', 'status': 'missing_or_stale'})
    ratio = None
    rc, rh = mk['ratio'].get('cyb'), mk['ratio'].get('hl')
    tc, th = observation_time('ratio', rc), observation_time('ratio', rh)
    if (tc is not None and th is not None and tc == th and tc.date().isoformat() == asof
            and fresh_record(rc, now, asof) and fresh_record(rh, now, asof)):
        ratio = ratio_block(rc.get('bars', []), rh.get('bars', []), now.date())
        if ratio and (not ratio['uiCompatible'] or rc.get('src') != 'tencent' or rh.get('src') != 'tencent'):
            issues.append({'kind': 'ratio', 'status': 'frozen_text_or_range_incompatible'})
            ratio = None
        if ratio:
            ratio['asOf'] = asof
            ratio['provenance'] = {key: {k: rec.get(k) for k in ('src', 'asOf', 'receivedAt', 'current')}
                                   for key, rec in (('cyb', rc), ('hl', rh))}
        if ratio and (ratio['p60'] < .2 or ratio['p60'] > .8):
            # Frozen sentence says "not in extreme zone" unconditionally.
            blockers.append('ratio_extreme_conflicts_with_frozen_sentence')
    if ratio is None:
        issues.append({'kind': 'ratio', 'status': 'unavailable_or_short_history'})

    wk = cfg["weekly"] or {}
    meta = {
        "asOf": asof, "asOfLabel": asof_label(asof, now) if asof else None, "today": now.date().isoformat(),
        "generatedAt": now.isoformat(timespec="minutes"), "repoUrl": cfg["repo_url"], "title": cfg["title"],
        "weekly": {"week": wk.get("week", ""), "focus": wk.get("focus", ""), "lead": wk.get("lead", ""),
                   "calHint": wk.get("calendar_hint", ""), "thermoAction": wk.get("thermo_action", "")},
        "stale": stale, "fx": {k: round(v, 4) for k, v in fx.items()},
        'asOfByMarket': {k: sorted(v) for k, v in market_dates.items()}, 'fxProvenance': fx_meta,
        'blockers': sorted(set(blockers)), 'issues': issues, 'offline': bool(fresh.get('offline')),
    }
    out = {"meta": meta, "industries": data["industries"], "chokepoints": data["chokepoints"],
           "companies": cos, "indices": idx, "ratio": ratio}
    return out, stale, missing


def render(D: dict, out_dir: Path) -> Path:
    site = RADAR / "site"
    h = (site / "index.html").read_text("utf-8")
    css = (site / "style.css").read_text("utf-8")
    js = (site / "app.js").read_text("utf-8")
    data = json.dumps(D, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("</", "<\\/")
    title = D["meta"].get("title") or "投研雷达"
    h = h.replace("<title>投研雷达 · Alpha Radar</title>", f"<title>{title} · Alpha Radar</title>")
    h = h.replace("/*__CSS__*/", css).replace("/*__DATA__*/", data).replace("/*__JS__*/", js)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "index.html"
    p.write_text(h, "utf-8")
    (out_dir / "vercel.json").write_text(json.dumps({
        "cleanUrls": True,
        "headers": [{"source": "/(.*)", "headers": [
            {"key": "X-Robots-Tag", "value": "noindex, nofollow"},
            {"key": "Cache-Control", "value": "private, no-store"}]}],
    }, indent=2), "utf-8")
    (out_dir / "robots.txt").write_text("User-agent: *\nDisallow: /\n", "utf-8")
    return p


def fingerprint(D: dict) -> str:
    # Receipt timestamps stay in DATA/cache/audit, but are not a market change.
    def substantive(value):
        if isinstance(value, dict):
            return {k: substantive(v) for k, v in value.items() if k != 'receivedAt'}
        if isinstance(value, list):
            return [substantive(v) for v in value]
        return value
    x = substantive(D)
    for k in ("generatedAt", "today"):
        x["meta"].pop(k, None)
    blob = json.dumps(x, ensure_ascii=False, sort_keys=True)
    for f in sorted((RADAR / "site").glob("*")) + [Path(__file__)]:
        blob += hashlib.sha256(f.read_bytes()).hexdigest()
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def gh_out(**kv) -> None:
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")


def gh_summary(text: str) -> None:
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="只校验数据，不联网")
    ap.add_argument("--offline", action="store_true", help="不联网，只用缓存")
    ap.add_argument("--force", action="store_true", help="无论行情是否变化都标记 changed=true")
    ap.add_argument("--out", default=str(RADAR / "dist" / "investment-radar"))
    ap.add_argument("--cache", default=str(RADAR / ".cache" / "quotes.json"))
    ap.add_argument('--audit-json', default=str(REPO / 'audit' / 'runtime' / 'build-report.json'))
    a = ap.parse_args()

    now = dt.datetime.now(BJ)
    data, rep = load_and_validate(RADAR, REPO, now.date())
    for w in rep.warnings:
        log(w)
    if rep.errors:
        for e in rep.errors:
            log(e)
        log(f"\n校验失败：{len(rep.errors)} 个错误。请按提示修改 radar/data/*.toml。")
        gh_summary("### ❌ 数据校验失败\n" + "\n".join(f"- {e}" for e in rep.errors))
        return 1
    log(f"校验通过：{len(data['industries'])} 个行业 · {len(data['chokepoints'])} 个卡点 · "
        f"{len(data['companies'])} 家公司 · {len(rep.warnings)} 条提醒")
    if a.check:
        return 0

    cache_p = Path(a.cache)
    cache = json.loads(cache_p.read_text("utf-8")) if cache_p.exists() else {}
    fresh, notes = fetch_all(data, cache, a.offline)
    for n in notes:
        log("·", n)
    mk = merge(fresh, cache)
    now = dt.datetime.now(BJ)  # receipts were collected after the initial validation time
    D, stale, missing = assemble(data, mk, fresh, now)
    blockers = release_blockers(D)
    report_path = Path(a.audit_json)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({'generatedAt': now.isoformat(), 'blockers': blockers,
                                       'data': D, 'notes': notes}, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    if not a.offline:
        cache_p.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_p.with_suffix('.tmp')
        tmp.write_text(json.dumps({**mk, 'fingerprint': cache.get('fingerprint'), 'savedAt': now.isoformat()},
                                  ensure_ascii=False, allow_nan=False), encoding='utf-8')
        tmp.replace(cache_p)
    n = len(data["companies"])
    log(f"行情：新抓 {len(fresh['daily'])}/{n}，用缓存 {len(stale)}，缺失 {len(missing)}；截至 {D['meta']['asOfLabel']}")
    if stale:
        log("  用缓存：", "、".join(stale))
    if missing:
        log("  缺失：", "、".join(missing))
    if len(missing) > n * MAX_MISSING:
        log(f"缺失超过 {int(MAX_MISSING * 100)}%，中止构建，不发布。")
        gh_summary(f"### ❌ 行情缺失过多（{len(missing)}/{n}），本次未发布\n" + "\n".join(f"- {x}" for x in notes))
        gh_out(changed="false")
        return 2

    if blockers:
        for reason in blockers:
            log('BLOCKED:', reason)
        gh_out(changed='false')
        gh_summary('### 构建阻断：冻结前端无法安全表达当前数据\n' + '\n'.join('- ' + b for b in blockers))
        return 3

    p = render(D, Path(a.out))
    fp = fingerprint(D)
    changed = a.force or fp != cache.get("fingerprint")
    if not a.offline:
        cache_p.parent.mkdir(parents=True, exist_ok=True)
        cache_p.write_text(json.dumps({**mk, "fingerprint": fp, "savedAt": now.isoformat(timespec="minutes")},
                                      ensure_ascii=False, separators=(",", ":")), "utf-8")
    log(f"已生成 {p}（{p.stat().st_size // 1024} KB）· 指纹 {fp} · {'有变化，需要部署' if changed else '与上次相同，跳过部署'}")
    gh_out(changed=str(bool(changed)).lower(), asof=D["meta"]["asOfLabel"], fingerprint=fp)
    gh_summary(f"### {'✅ 已生成，将部署' if changed else '⏸️ 行情无变化，跳过部署'}\n"
               f"- 行情截至：{D['meta']['asOfLabel']}\n- 新抓 {len(fresh['daily'])}/{n}，用缓存 {len(stale)}，缺失 {len(missing)}\n"
               + "".join(f"- {x}\n" for x in notes + rep.warnings[:20]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
