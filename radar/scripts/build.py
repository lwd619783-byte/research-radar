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
    if not bars:
        return {}
    a = [b[2] for b in bars]
    last, ld = a[-1], bars[-1][0]

    def ret(n):
        return last / a[-1 - n] - 1 if len(a) > n and a[-1 - n] else None

    base = [b[2] for b in bars if b[0][:4] < ld[:4]]
    win = a[-252:]
    d0 = dt.date.fromisoformat(bars[0][0])
    sd, prev = [], d0
    for b in bars:
        cur = dt.date.fromisoformat(b[0])
        sd.append((cur - prev).days)
        prev = cur
    return {
        "price": round(bars[-1][1], 3 if bars[-1][1] < 10 else 2), "r1d": r4(ret(1), 5), "r5": r4(ret(5)), "r20": r4(ret(20)), "r60": r4(ret(60)),
        "ytd": r4(last / base[-1] - 1) if base else None, "dd52": r4(last / max(win) - 1) if win else None,
        "hi52": max(b[1] for b in bars[-252:]), "ld": ld,
        "s0": d0.isoformat(), "sd": sd, "sc": [sig4(b[1]) for b in bars],
    }


def ratio_block(cyb: list[list], hl: list[list]) -> dict:
    """创业板指 ÷ 中证红利 月度比值。分位只和「已走完的月份」比较（当月未走完）。"""
    c, h = dict(cyb), dict(hl)
    months = sorted(set(c) & set(h))
    series = [[m, round(c[m] / h[m], 4)] for m in months]
    cur = series[-1][1]
    full = [v for _, v in series[:-1]]
    m60, m120 = full[-60:], full[-120:]
    n60, n120 = sum(v < cur for v in m60), sum(v < cur for v in m120)
    return {"series": series, "cur": cur, "cyb": round(c[months[-1]], 2), "hl": round(h[months[-1]], 2),
            "p60": n60 / len(m60), "p120": n120 / len(m120), "n60": n60, "n120": n120}


def asof_label(asof: str, now: dt.datetime) -> str:
    d = dt.date.fromisoformat(asof)
    md = f"{d.month}/{d.day}"
    if asof != now.date().isoformat():
        return f"{md} 收盘"
    hm = now.hour * 60 + now.minute
    if hm < 9 * 60 + 30:
        return f"{md} 开盘前"
    if hm < 11 * 60 + 30 or 13 * 60 <= hm < 15 * 60:
        return f"{md} {now:%H:%M} 盘中"
    if hm < 13 * 60:
        return f"{md} 午间"
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
    h = quotes.Http()
    ratio_cfg = cfg["ratio"] or {}
    jobs = {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for s in syms:
            jobs[ex.submit(quotes.daily, h, s)] = ("daily", s)
        for x in cfg["indices"]:
            jobs[ex.submit(quotes.index_quote, h, x["symbol"], x.get("tencent", ""))] = ("index", x["symbol"])
        curs = sorted({c["cur"] for c in data["companies"]} - {"USD"})
        for cur in curs:
            jobs[ex.submit(quotes.fx, h, cur)] = ("fx", cur)
        for key, tx, yh in (("cyb", ratio_cfg.get("growth_tencent", "sz399006"), ratio_cfg.get("growth_yahoo", "399006.SZ")),
                            ("hl", ratio_cfg.get("dividend_tencent", "sh000922"), ratio_cfg.get("dividend_yahoo", "000922.SS"))):
            jobs[ex.submit(quotes.monthly, h, tx, yh)] = ("ratio", key)
        for f in cf.as_completed(jobs):
            kind, key = jobs[f]
            try:
                fresh[kind][key] = f.result()
            except Exception as e:  # noqa: BLE001
                notes.append(f"{kind} {key} 抓取失败：{str(e)[:160]}")
    fresh["quote"] = quotes.yahoo_quotes(h, syms)
    if not fresh["quote"]:
        notes.append("Yahoo 市值/PE 批量接口不可用，市值与 PE 使用缓存或 companies.toml 的 fallback_*")
    return fresh, notes


def merge(fresh: dict, cache: dict) -> dict:
    """新数据覆盖缓存；没抓到的保留缓存（之后标记为 stale）。"""
    out = {}
    for k in ("daily", "quote", "index", "fx", "ratio"):
        out[k] = dict(cache.get(k, {}))
        out[k].update(fresh.get(k, {}))
    return out


# ---------------- 组装 DATA ----------------
def assemble(data: dict, mk: dict, fresh: dict, now: dt.datetime) -> tuple[dict, list[str], list[str]]:
    cfg = data["config"]
    fxf = {k: float(v) for k, v in (cfg["fx_fallback"] or {}).items()}
    fx = {"USD": 1.0}
    for cur in ("CNY", "HKD", "TWD", "KRW", "JPY"):
        fx[cur] = mk["fx"].get(cur) or fxf.get(cur) or 1.0
    fx["EUR"] = mk["fx"].get("EUR") or (1 / fxf["EURUSD"] if fxf.get("EURUSD") else 0.9)

    stale, missing, cos = [], [], []
    for c in data["companies"]:
        s = c["sym"]
        d = mk["daily"].get(s)
        m = metrics(d["bars"]) if d else {}
        if not d:
            missing.append(c["name"])
        elif s not in fresh["daily"] and not fresh.get("offline"):
            stale.append(c["name"])
            m["stale"] = True
        q = mk["quote"].get(s) or {}
        cur = (q.get("currency") or (d or {}).get("currency") or c["cur"])
        if cur not in fx:
            cur = c["cur"]
        mcap = q.get("marketCap")
        mcap_usd = round(mcap / fx[cur] / 1e8, 1) if mcap else (round(c["fallback_mcap_usd_bn"] * 10, 1) if c["fallback_mcap_usd_bn"] else None)
        pe = q.get("trailingPE")
        pe = round(pe, 1) if isinstance(pe, (int, float)) and pe > 0 else c["fallback_pe"]
        hi52 = q.get("fiftyTwoWeekHigh") or (d or {}).get("hi52") or m.get("hi52")
        row = {k: c[k] for k in ("id", "name", "code", "sym", "mkt", "role", "ind", "cp", "revg", "earng", "gm",
                                 "period", "flash", "view", "next", "url")}
        row.update({"cur": cur, "pe": pe, "mcapUSD": mcap_usd,
                    "price": None, "r1d": None, "r5": None, "r20": None, "r60": None, "ytd": None, "dd52": None,
                    "s0": None, "sd": [], "sc": [], "ld": None})
        row.update(m)
        row["hi52"] = round(hi52, 3 if hi52 < 10 else 2) if hi52 else None
        cos.append(row)

    a_dates = [c["ld"] for c in cos if c["mkt"] == "A股" and c["ld"]]
    all_dates = [c["ld"] for c in cos if c["ld"]]
    asof = max(a_dates or all_dates or [now.date().isoformat()])

    idx = []
    for x in cfg["indices"]:
        v = mk["index"].get(x["symbol"])
        if v:
            idx.append({"name": x["name"], "price": round(v["price"], 2),
                        "chg": round(v["chg"], 5)})
    ratio = None
    if mk["ratio"].get("cyb") and mk["ratio"].get("hl"):
        ratio = ratio_block(mk["ratio"]["cyb"], mk["ratio"]["hl"])

    wk = cfg["weekly"] or {}
    meta = {
        "asOf": asof, "asOfLabel": asof_label(asof, now), "today": now.date().isoformat(),
        "generatedAt": now.isoformat(timespec="minutes"), "repoUrl": cfg["repo_url"], "title": cfg["title"],
        "weekly": {"week": wk.get("week", ""), "focus": wk.get("focus", ""), "lead": wk.get("lead", ""),
                   "calHint": wk.get("calendar_hint", ""), "thermoAction": wk.get("thermo_action", "")},
        "stale": stale, "fx": {k: round(v, 4) for k, v in fx.items()},
    }
    out = {"meta": meta, "industries": data["industries"], "chokepoints": data["chokepoints"],
           "companies": cos, "indices": idx, "ratio": ratio}
    return out, stale, missing


def render(D: dict, out_dir: Path) -> Path:
    site = RADAR / "site"
    h = (site / "index.html").read_text("utf-8")
    css = (site / "style.css").read_text("utf-8")
    js = (site / "app.js").read_text("utf-8")
    data = json.dumps(D, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
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
            {"key": "Cache-Control", "value": "public, max-age=0, must-revalidate"}]}],
    }, indent=2), "utf-8")
    (out_dir / "robots.txt").write_text("User-agent: *\nDisallow: /\n", "utf-8")
    return p


def fingerprint(D: dict) -> str:
    x = json.loads(json.dumps(D))
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
    D, stale, missing = assemble(data, mk, fresh, now)
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
