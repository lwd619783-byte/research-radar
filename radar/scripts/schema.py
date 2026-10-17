"""读取并校验 radar/data/*.toml。只用标准库（Python ≥ 3.11）。

错误（error）会让构建失败；提醒（warning）只打印，不阻断。
"""
from __future__ import annotations

import datetime as dt
import re
import tomllib
from pathlib import Path

MARKETS = {"A股", "港股", "美股", "台股", "韩股", "日股", "欧股"}
TIGHTNESS = {"极紧": "🔴极紧", "偏紧": "🟠偏紧", "缓解中": "🟢缓解中"}
SCORE_KEYS = ("boom", "delivery", "choke", "valuation")
MARKET_CUR = {"A股": "CNY", "港股": "HKD", "美股": "USD", "台股": "TWD", "韩股": "KRW", "日股": "JPY", "欧股": "EUR"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, where: str, msg: str) -> None:
        self.errors.append(f"[错误] {where}：{msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"[提醒] {where}：{msg}")


def _load(path: Path, rep: Report) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        rep.err(path.name, "文件不存在")
    except tomllib.TOMLDecodeError as e:
        rep.err(path.name, f"TOML 语法错误：{e}（常见原因：引号没闭合、中文引号当成英文引号、逗号多余）")
    return {}


def _str(rep: Report, where: str, obj: dict, key: str, required: bool = True) -> str:
    v = obj.get(key, "")
    if not isinstance(v, str):
        rep.err(where, f"{key} 必须是字符串（用英文双引号包起来）")
        return ""
    if required and not v.strip():
        rep.err(where, f"缺少 {key}")
    return v.strip()


def _num(rep: Report, where: str, v, key: str):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        rep.err(where, f"{key} 必须是数字（不要加引号或 %），现在是 {v!r}")
        return None
    return float(v)


def _date(rep: Report, where: str, v: str, key: str):
    if not v:
        return None
    try:
        return dt.date.fromisoformat(v)
    except ValueError:
        rep.err(where, f"{key} 必须是 YYYY-MM-DD 格式的日期或空字符串，现在是 {v!r}")
        return None


def load_and_validate(radar_dir: Path, repo_root: Path, today: dt.date | None = None):
    """返回 (data, report)。data = {config, industries, chokepoints, companies}，均已规范化。"""
    rep = Report()
    today = today or dt.date.today()
    d = radar_dir / "data"
    cfg = _load(d / "config.toml", rep)
    ind_raw = _load(d / "industries.toml", rep).get("industry", [])
    cp_raw = _load(d / "chokepoints.toml", rep).get("chokepoint", [])
    co_raw = _load(d / "companies.toml", rep).get("company", [])
    if rep.errors:
        return None, rep

    # ---- config ----
    site = cfg.get("site", {})
    weekly = cfg.get("weekly", {})
    repo_url = str(site.get("repo_url", "")).strip().rstrip("/")
    if repo_url and not re.match(r"^https://github\.com/[^/]+/[^/]+$", repo_url):
        rep.err("config.toml [site]", f"repo_url 应形如 https://github.com/用户名/仓库名，现在是 {repo_url!r}")
    kb_branch = str(site.get("kb_branch", "main")).strip() or "main"
    indices = cfg.get("index", [])
    if not indices:
        rep.warn("config.toml", "没有配置 [[index]]，跑马灯将不显示指数")
    for i, x in enumerate(indices):
        if not x.get("symbol") or not x.get("name"):
            rep.err(f"config.toml [[index]] 第{i+1}个", "需要 symbol 和 name")
    fxf = cfg.get("fx_fallback", {})

    def kb_url(path: str, where: str) -> str:
        if not path:
            return ""
        if path.startswith("http"):
            return path
        if not (repo_root / path).exists():
            rep.warn(where, f"kb 路径在仓库中不存在：{path}（检查文件名是否被改过）")
        if not repo_url:
            return ""
        from urllib.parse import quote
        return f"{repo_url}/blob/{kb_branch}/{quote(path)}"

    # ---- industries ----
    industries, names = [], set()
    for i, x in enumerate(ind_raw):
        w = f"industries.toml 第{i+1}个行业"
        n = _str(rep, w, x, "name")
        w = f"industries.toml「{n or i+1}」"
        if n in names:
            rep.err(w, "行业名重复")
        names.add(n)
        sc = x.get("scores", {})
        s = []
        for k in SCORE_KEYS:
            v = sc.get(k)
            if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 5:
                rep.err(w, f"scores.{k} 必须是 1–5 的整数，现在是 {v!r}")
                v = 1
            s.append(v)
        extra = set(sc) - set(SCORE_KEYS)
        if extra:
            rep.err(w, f"scores 里有未知字段 {sorted(extra)}，只能是 {list(SCORE_KEYS)}")
        kb = _str(rep, w, x, "kb", required=False)
        industries.append({
            "name": n, "s": s, "total": sum(s),
            "logic": _str(rep, w, x, "logic"), "signal": _str(rep, w, x, "signal", False),
            "risk": _str(rep, w, x, "risk", False), "reps": _str(rep, w, x, "reps", False),
            "kb": kb, "url": kb_url(kb, w),
        })
    industries.sort(key=lambda r: -r["total"])  # 稳定排序：同分保持文件顺序

    focus = str(weekly.get("focus", "")).strip()
    if focus and focus not in names:
        rep.err("config.toml [weekly]", f"focus「{focus}」不在 industries.toml 里")

    # ---- chokepoints ----
    chokepoints, cp_ind = [], {}
    for i, x in enumerate(cp_raw):
        n = _str(rep, f"chokepoints.toml 第{i+1}个", x, "name")
        w = f"chokepoints.toml「{n or i+1}」"
        if n in cp_ind:
            rep.err(w, "卡点名重复")
        ind = _str(rep, w, x, "industry")
        if ind and ind not in names:
            rep.err(w, f"industry「{ind}」不在 industries.toml 里")
        t = _str(rep, w, x, "tightness")
        if t not in TIGHTNESS:
            rep.err(w, f"tightness 只能是 极紧 / 偏紧 / 缓解中，现在是 {t!r}")
        cp_ind[n] = ind
        chokepoints.append({"name": n, "ind": ind, "seg": _str(rep, w, x, "segment", False),
                            "tight": TIGHTNESS.get(t, t), "why": _str(rep, w, x, "why", False),
                            "track": _str(rep, w, x, "track", False)})

    # ---- companies ----
    companies, ids, syms, used_cp = [], set(), set(), set()
    for i, x in enumerate(co_raw):
        cid = _str(rep, f"companies.toml 第{i+1}个", x, "id")
        nm = _str(rep, f"companies.toml 第{i+1}个", x, "name")
        w = f"companies.toml「{nm or cid or i+1}」"
        if cid and not re.match(r"^[A-Za-z0-9_-]+$", cid):
            rep.err(w, f"id 只能用英文字母、数字、-、_，现在是 {cid!r}")
        if cid in ids:
            rep.err(w, f"id「{cid}」重复")
        ids.add(cid)
        sym = _str(rep, w, x, "symbol")
        if sym in syms:
            rep.err(w, f"symbol「{sym}」重复")
        syms.add(sym)
        mkt = _str(rep, w, x, "market")
        if mkt not in MARKETS:
            rep.err(w, f"market 只能是 {'/'.join(sorted(MARKETS))}，现在是 {mkt!r}")
        if mkt == "A股" and not re.match(r"^\d{6}\.(SS|SZ|BJ)$", sym):
            rep.err(w, f"A股 symbol 应形如 600000.SS / 300308.SZ，现在是 {sym!r}")
        if mkt == "港股" and not re.match(r"^\d{4,5}\.HK$", sym):
            rep.err(w, f"港股 symbol 应形如 0700.HK，现在是 {sym!r}")
        ind = _str(rep, w, x, "industry")
        cp = _str(rep, w, x, "chokepoint")
        if cp not in cp_ind:
            rep.err(w, f"chokepoint「{cp}」不在 chokepoints.toml 里")
        elif cp_ind[cp] != ind:
            rep.err(w, f"industry「{ind}」与卡点「{cp}」所属行业「{cp_ind[cp]}」不一致")
        used_cp.add(cp)
        nxt = _str(rep, w, x, "next_earnings", False)
        nd = _date(rep, w, nxt, "next_earnings")
        if nd and nd < today:
            rep.warn(w, f"next_earnings {nxt} 已过去：更新 fin / flash，并改成下一次财报日（未知就留空）")
        fin = x.get("fin", {})
        for k in fin:
            if k not in ("period", "revenue_yoy", "profit_yoy", "gross_margin"):
                rep.err(w, f"fin 里有未知字段 {k}")
        pct = lambda k: (lambda v: None if v is None else v / 100)(_num(rep, w, fin.get(k), f"fin.{k}"))
        gm = pct("gross_margin")
        if gm is not None and not -1 <= gm <= 1:
            rep.err(w, "fin.gross_margin 应写百分数（82.1 表示 82.1%）")
        kb = _str(rep, w, x, "kb", False)
        companies.append({
            "id": cid, "name": nm, "code": _str(rep, w, x, "code", False) or sym, "sym": sym, "mkt": mkt,
            "role": _str(rep, w, x, "role", False), "ind": ind, "cp": cp,
            "view": _str(rep, w, x, "view", False), "flash": _str(rep, w, x, "flash", False),
            "next": nxt or None, "period": str(fin.get("period", "")),
            "revg": pct("revenue_yoy"), "earng": pct("profit_yoy"), "gm": gm,
            "fallback_pe": _num(rep, w, x.get("fallback_pe"), "fallback_pe"),
            "fallback_mcap_usd_bn": _num(rep, w, x.get("fallback_mcap_usd_bn"), "fallback_mcap_usd_bn"),
            "cur": MARKET_CUR.get(mkt, "USD"), "kb": kb, "url": kb_url(kb, w),
        })
    for c in chokepoints:
        if c["name"] not in used_cp:
            rep.warn(f"chokepoints.toml「{c['name']}」", "没有任何公司挂在这个卡点下")

    data = {"config": {"title": site.get("title", "投研雷达"), "repo_url": repo_url, "kb_branch": kb_branch,
                       "weekly": weekly, "indices": indices, "fx_fallback": fxf, "ratio": cfg.get("ratio", {})},
            "industries": industries, "chokepoints": chokepoints, "companies": companies}
    return data, rep
