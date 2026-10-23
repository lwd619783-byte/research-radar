"""Contract-driven Notion normalization and last-good reconciliation.

This module does not perform network requests or inspect credentials. Original
simplified rows are retained separately from the cleaned DATA representation so
that last-good contents are revalidated against every new build clock.
"""

from __future__ import annotations

import copy
import math
import re
import unicodedata
from datetime import date, datetime, timezone, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from research_snapshot import (
    TABLES, SUBSTITUTABLE, ResearchAbort, load_last_good, make_snapshot,
    schema_hash, snapshot_sha256,
)
from research_view import public_first_sources, urls


TOKEN = re.compile(r"\{\{earnings:([^{}]+)\}\}")
SCORES = ("景气度", "业绩兑现", "卡点强度", "估值位置")


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _today(clock):
    value = clock if isinstance(clock, datetime) else datetime.fromisoformat(str(clock).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone(timedelta(hours=8)))
    return value.astimezone(timezone(timedelta(hours=8))).date()


def _normalized_text(text):
    return re.sub(r"[\s\u3000]+", "", unicodedata.normalize("NFKC", text))


def _has_words(text, words):
    text = _normalized_text(text)
    return any(_normalized_text(word) in text for word in words)


def _text_length(text, tokens=False):
    return len(TOKEN.sub("x" * 10, text)) if tokens else len(text)


def _truncate(text, limit, tokens=False):
    if not tokens:
        return text[:limit - 1] + "…"
    parts = re.split(r"(\{\{earnings:[^{}]+\}\})", text)
    output, length = [], 0
    for part in parts:
        if TOKEN.fullmatch(part):
            if length + 10 > limit - 1:
                break
            output.append(part)
            length += 10
        else:
            remaining = limit - 1 - length
            output.append(part[:remaining])
            length += min(len(part), remaining)
            if len(part) > remaining:
                break
    return "".join(output) + "…"


def _https(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme.lower() == "https" and bool(parsed.hostname) and not any(char.isspace() for char in value)
    except ValueError:
        return False


def simplify_page(page, table_contract):
    """Strip Notion metadata and flatten only contract properties."""
    props = {}
    raw = page.get("properties", {})
    for name, spec in table_contract["properties"].items():
        kind = spec["type"]
        if spec["level"] == "ignore":
            continue
        value = raw.get(name, {})
        if kind in ("title", "rich_text"):
            props[name] = "".join(str(part.get("plain_text", "")) for part in value.get(kind, []) if isinstance(part, dict)).strip()
        elif kind == "select":
            selection = value.get(kind)
            props[name] = selection.get("name") if isinstance(selection, dict) else None
        elif kind == "date":
            selected = value.get(kind)
            props[name] = str(selected["start"])[:10] if isinstance(selected, dict) and selected.get("start") else None
        elif kind == "relation":
            relations = [item.get("id") for item in value.get(kind, []) if isinstance(item, dict) and item.get("id")]
            if value.get("has_more"):
                relations.extend(["__relation_has_more__"] * (max(spec.get("limit", spec.get("max_items", 1)), 1) + 1))
            props[name] = relations
        elif kind == "checkbox":
            props[name] = value.get(kind, False) is True
        else:
            props[name] = value.get(kind)
    return {"id": str(page.get("id", "")), "created_time": page.get("created_time", ""),
            "last_edited_time": page.get("last_edited_time", ""), "props": props}


def _row_key(table, row):
    props = row["props"]
    fields = {"industries": "名称", "chokepoints": "名称", "companies": "代号", "financials": "记录", "daily": "标题", "weekly": "周次"}
    return str(props.get(fields[table]) or row["id"])


def _identity(table, row):
    props = row["props"]
    if table == "financials":
        return (tuple(props.get("公司") or []), props.get("财年"), props.get("期间"), props.get("口径"))
    if table == "daily":
        return (props.get("日期"), props.get("市场"))
    return _row_key(table, row)


def _diagnostic(code, table, row, field="", detail=None):
    return {"code": code, "table": table, "key": _row_key(table, row), "field": field, "detail": detail or {}}


class _InvalidRow(Exception):
    def __init__(self, code, field):
        self.code, self.field = code, field


class _ExcludedRow(Exception):
    pass


def _clean_row(table, row, contract, today, resolved, excluded):
    original = row["props"]
    props, warnings = {}, []
    banned = False
    rejected_text = False

    def warn(code, field, detail=None):
        warnings.append(_diagnostic(code, table, row, field, detail))

    # Exclusions precede validation and must not create unrelated warnings.
    if original.get("停用"):
        raise _ExcludedRow()
    for field, spec in contract["tables"][table]["properties"].items():
        if spec["type"] == "relation" and spec["level"] == "row":
            relations = original.get(field) or []
            target = spec["target"]
            if len(relations) == 1 and relations[0] in excluded[target]:
                if table != "weekly":
                    raise _ExcludedRow()
            if table == "financials" and len(relations) == 1 and relations[0] not in resolved[target]:
                # Financial records for a removed/capped/unusable company do
                # not become orphan research records or trigger table rollback.
                raise _ExcludedRow()
    for field, spec in contract["tables"][table]["properties"].items():
        level, kind = spec["level"], spec["type"]
        if level == "ignore":
            continue
        value = copy.deepcopy(original.get(field))
        if value is None or value == "":
            value = copy.deepcopy(spec.get("default", value))
        if kind in ("title", "rich_text"):
            value = value.strip() if isinstance(value, str) else ""
            if spec.get("banned") and _has_words(value, contract["banned_words"]):
                value, banned = "", True
                warn("banned_words", field)
                rejected_text = table in ("daily", "weekly")
            elif spec.get("banned_prediction") and _has_words(value, contract["prediction_words"]["words"]):
                value, rejected_text = "", True
                warn("prediction_words", field)
            if not value and level == "row" and not rejected_text:
                raise _InvalidRow("missing_required", field)
            if spec.get("regex") and value and not re.fullmatch(spec["regex"], value):
                if level == "row":
                    raise _InvalidRow("regex_mismatch", field)
                warn("regex_mismatch", field)
                value = ""
            if spec.get("regex_by_market") and value:
                market = original.get("市场")
                pattern = spec["regex_by_market"].get(market)
                # Missing/invalid market has its own row diagnostic.
                if pattern and not re.fullmatch(pattern, value):
                    raise _InvalidRow("regex_mismatch", field)
            if spec.get("split") and spec.get("max_items"):
                items = [part.strip() for part in value.split(spec["split"]) if part.strip()]
                if len(items) > spec["max_items"]:
                    items = items[:spec["max_items"]]
                    warn("list_truncated", field)
                value = spec["split"].join(items)
            length = _text_length(value, spec.get("tokens", False))
            if spec.get("hard_len") and length > spec["hard_len"]:
                value = _truncate(value, spec["hard_len"], spec.get("tokens", False))
                warn("text_truncated", field)
            elif spec.get("soft_len") and length > spec["soft_len"]:
                warn("text_long", field)
            if spec.get("iana_tz") and value:
                try:
                    ZoneInfo(value)
                except (ZoneInfoNotFoundError, ValueError):
                    value = contract["market_timezones"].get(original.get("市场"), "")
                    warn("timezone_invalid", field)
        elif kind == "number":
            if value is None:
                if level == "row":
                    raise _InvalidRow("missing_required", field)
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                if level == "row":
                    raise _InvalidRow("number_out_of_range", field)
                value = None
                warn("pct_out_of_range" if spec.get("percent") else "number_out_of_range", field)
            elif spec.get("integer") and value != int(value):
                raise _InvalidRow("number_not_integer", field)
            elif ("min" in spec and value < spec["min"]) or ("max" in spec and value > spec["max"]):
                if level == "row":
                    raise _InvalidRow("number_out_of_range", field)
                value = None
                warn("pct_out_of_range" if spec.get("percent") else "number_out_of_range", field)
            elif field == "营收同比%" and value > 5000:
                warn("pct_suspicious", field)
            elif field == "毛利率%" and 0 < abs(value) < 1:
                warn("pct_maybe_fraction", field)
        elif kind == "select":
            if value is None or value == "":
                if level == "row":
                    raise _InvalidRow("missing_required", field)
                value = None
            elif value not in spec.get("enum", {}):
                if level == "row":
                    raise _InvalidRow("invalid_enum", field)
                warn("invalid_enum", field)
                value = None
        elif kind == "date":
            parsed = _date(value)
            if parsed is None:
                if level == "row":
                    raise _InvalidRow("missing_required" if not value else "regex_mismatch", field)
                if value:
                    warn("regex_mismatch", field)
                value = None
            else:
                value = parsed.isoformat()
        elif kind == "url":
            if value and not _https(value):
                warn("url_invalid", field)
                value = ""
            value = value or ""
        elif kind == "relation":
            value = value if isinstance(value, list) else []
            if spec.get("limit") and len(value) > spec["limit"]:
                if level == "row":
                    raise _InvalidRow("relation_multiple", field)
                warn("relation_multiple", field)
                value = []
            if not value and level == "row":
                raise _InvalidRow("relation_missing", field)
            target = spec["target"]
            missing = [identifier for identifier in value if identifier not in resolved[target]]
            if missing and level == "row":
                raise _InvalidRow("relation_missing", field)
            value = [identifier for identifier in value if identifier in resolved[target]]
            if spec.get("max_items") and len(value) > spec["max_items"]:
                value = value[:spec["max_items"]]
                warn("relation_truncated", field)
        elif kind == "checkbox":
            value = value is True
        props[field] = value

    if table == "financials":
        if props["期末日"] > props["发布日"]:
            raise _InvalidRow("period_after_publish", "期末日")
        if props["发布日"] > today.isoformat():
            raise _InvalidRow("publish_in_future", "发布日")
    if table == "companies":
        if props.get("卡点"):
            choke = resolved["chokepoints"][props["卡点"][0]]["props"]
            if choke["行业"] != props["行业"]:
                props["卡点"] = []
                warn("cp_industry_mismatch", "卡点")
        if props.get("下次财报日") and props["下次财报日"] < today.isoformat():
            warn("earnings_date_past", "下次财报日")
        if props.get("下次财报日") and props.get("财报日状态") == "官方确认" and not props.get("财报日来源"):
            props["财报日状态"] = "预估"
            warn("earnings_confirmed_without_source", "财报日状态")
        if props.get("快讯日期") and props["快讯日期"] > today.isoformat():
            props["快讯日期"] = today.isoformat()
            warn("flash_date_future", "快讯日期")
    clean = {key: row[key] for key in ("id", "created_time", "last_edited_time")}
    clean.update(props=props, banned=banned, rejected_text=rejected_text)
    return clean, warnings


def _deduplicate(table, rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(_identity(table, row), []).append(row)
    kept, duplicates, warnings = [], [], []
    for group in grouped.values():
        if table == "financials":
            # Stable passes implement descending date/edit with ascending id ties.
            group.sort(key=lambda row: row["id"])
            group.sort(key=lambda row: row["last_edited_time"], reverse=True)
            group.sort(key=lambda row: row["props"].get("录入日") or "", reverse=True)
        elif table == "daily":
            group.sort(key=lambda row: row["id"])
            group.sort(key=lambda row: row["last_edited_time"], reverse=True)
        else:
            group.sort(key=lambda row: (row["created_time"], row["id"]))
        kept.append(group[0])
        for row in group[1:]:
            if table in ("financials", "daily"):
                warnings.append(_diagnostic("financial_duplicate" if table == "financials" else "daily_duplicate", table, row))
            else:
                duplicates.append((row, _InvalidRow("duplicate_key", "代号" if table == "companies" else "名称" if table != "weekly" else "周次")))
    return kept, duplicates, warnings


def _validate_table(table, rows, contract, today, resolved, excluded):
    eligible, bad, warnings, excluded_ids = [], [], [], set()
    for row in sorted(rows, key=lambda item: item["id"]):
        try:
            clean, notes = _clean_row(table, row, contract, today, resolved, excluded)
        except _ExcludedRow:
            excluded_ids.add(row["id"])
        except _InvalidRow as error:
            bad.append((row, error))
        else:
            if clean["rejected_text"]:
                # Invalid daily/weekly AI content has a field warning, not an
                # additional missing_required quarantine after clearing it.
                warnings.extend(notes)
                excluded_ids.add(row["id"])
            else:
                clean["_original"] = row
                clean["_warnings"] = notes
                eligible.append(clean)
    kept, duplicates, duplicate_warnings = _deduplicate(table, eligible)
    bad.extend((row["_original"], error) for row, error in duplicates)
    warnings.extend(duplicate_warnings)
    for row in kept:
        warnings.extend(row.pop("_warnings"))
    return kept, bad, warnings, excluded_ids


def _financial_data(row, contract):
    props = row["props"]
    fields = contract["tables"]["financials"]["properties"]
    result = {}
    for name, spec in fields.items():
        mapping = spec.get("data", "")
        if not mapping.startswith("financial.") or name in ("其他来源", "注意事项"):
            continue
        key = mapping.removeprefix("financial.")
        value = props.get(name)
        if spec.get("enum"):
            value = spec["enum"].get(value, "")
        result[key] = value if value is not None else ""
    result["source_urls"] = public_first_sources(([props["来源链接"]] if props.get("来源链接") else []) + urls(props.get("其他来源")))
    result["conditions"] = [line.strip() for line in (props.get("注意事项") or "").splitlines() if line.strip()]
    if not props.get("来源链接"):
        evidence = "missing"
    elif props["口径"] == "单季" and props["报告状态"] in ("正式报告", "仅营收"):
        evidence = "source"
    else:
        evidence = "partial"
    result.update(evidence=evidence, rowSource=row["rowSource"])
    return result


def _attach_financials(companies, financial_rows, contract, today, company_page_ids):
    basis_order = {"单季": 0, "半年": 1, "累计": 2, "全年": 3}
    status_order = {"正式报告": 0, "业绩快报": 1, "初步结果": 2, "业绩预告": 3, "仅营收": 4}
    grouped = {}
    for row in financial_rows:
        financial = _financial_data(row, contract)
        grouped.setdefault(row["props"]["公司"][0], []).append((row, financial))
    for company in companies:
        candidates = grouped.get(company_page_ids[company["id"]], [])
        sourced = [pair for pair in candidates if pair[1]["evidence"] != "missing"]
        pool = sourced or candidates
        pool.sort(key=lambda pair: (-date.fromisoformat(pair[0]["props"]["期末日"]).toordinal(),
                                   basis_order[pair[0]["props"]["口径"]], status_order[pair[0]["props"]["报告状态"]],
                                   -date.fromisoformat(pair[0]["props"]["发布日"]).toordinal(), pair[0]["id"]))
        company.update(revg=None, earng=None, gm=None, period="", financialPartial=False,
                       financialRevenueComparable=False, financialSignalEligible=False, provenance={"financial": None})
        if not pool:
            continue
        row, financial = pool[0]
        props = row["props"]
        for key, name in (("revg", "营收同比%"), ("earng", "净利同比%"), ("gm", "毛利率%")):
            company[key] = props[name] / 100 if props.get(name) is not None else None
        company["period"] = props["显示期间"]
        company["provenance"]["financial"] = financial
        company["financialPartial"] = financial["evidence"] == "partial"
        company["financialRevenueComparable"] = (financial["evidence"] == "source" and financial["report_status"] == "final"
                                                  and (today - date.fromisoformat(props["期末日"])).days <= 200)
        company["financialSignalEligible"] = company["financialRevenueComparable"] and financial["profit_comparison"] == "comparable"


def normalize(fetch, contract, fixed_clock, last_good=None, config=None):
    """Normalize six fetched tables, then reconcile bad tables and individual rows."""
    config = config or {}
    settings = config.get("notion", config)
    today = _today(fixed_clock)
    fixed_clock = fixed_clock.isoformat() if isinstance(fixed_clock, datetime) else str(fixed_clock)
    previous = load_last_good(last_good, contract)
    resolved, excluded = {name: {} for name in TABLES}, {name: set() for name in TABLES}
    metadata = {"source": "notion", "fetchedAt": fixed_clock, "requests": copy.deepcopy(fetch.get("request_stats", fetch.get("requests", {}))),
                "counts": {}, "fallbackTables": [], "quarantined": [], "warnings": []}
    snapshot_tables = {}
    table_rows = {}

    def fallback(table, error):
        error = error or {"code": "notion_bad_json"}
        if previous is None:
            raise ResearchAbort(codes=[error.get("code", "notion_bad_json")], detail={"table": table})
        old = previous["tables"][table]
        metadata["fallbackTables"].append({"table": table, "code": error.get("code", "notion_bad_json"),
                                          "detail": error.get("detail") or {}, "lastGoodFetchedAt": old["fetchedAt"]})
        return copy.deepcopy(old["rows"]), old

    for table in TABLES:
        fetched = fetch.get("tables", {}).get(table, {})
        entry = None
        excluded_now = set()
        source = "notion"
        if fetch.get("stopped_all") or not fetched.get("ok"):
            error = fetched.get("error") or {"code": fetched.get("code", "notion_bad_json"),
                                               "detail": fetched.get("detail", {})}
            rows, entry = fallback(table, fetch.get("error") if fetch.get("stopped_all") else error)
            source = "last_good"
        else:
            rows = []
            if "rows" in fetched:
                # Credential-free production handoff. Only the same simplified
                # row shape used by snapshots is accepted; raw identity metadata
                # never enters the replay path. Trash remains countable/excluded.
                for row in fetched["rows"]:
                    if row.get("in_trash"):
                        excluded_now.add(row["id"])
                        continue
                    rows.append({key: copy.deepcopy(row[key]) for key in
                                 ("id", "created_time", "last_edited_time", "props")})
            else:
                for page in fetched.get("pages", []):
                    if page.get("object") != "page":
                        continue
                    if page.get("in_trash"):
                        excluded_now.add(page["id"])
                        continue
                    rows.append(simplify_page(page, contract["tables"][table]))
        fetched_count = (len(fetched["rows"]) if "rows" in fetched else
                         sum(page.get("object") == "page" for page in fetched.get("pages", [])))
        excluded[table].update(excluded_now)
        good, bad, warnings, clean_excluded = _validate_table(table, rows, contract, today, resolved, excluded)
        eligible_count = len(rows) - len(clean_excluded)
        quality_low = (eligible_count >= settings.get("quality_min_rows", 5)
                       and len(bad) > eligible_count * settings.get("quality_threshold", 0.20))
        original_bad = bad
        if source == "notion" and quality_low:
            rows, entry = fallback(table, {"code": "table_quality_low", "detail": {"bad": len(bad), "total": eligible_count}})
            source = "last_good"
            good, bad, warnings, clean_excluded = _validate_table(table, rows, contract, today, resolved, excluded)
            # Report rejected source rows even though the whole replacement
            # table is used; none of its rows is a row-level substitution.
            for row, error in original_bad:
                metadata["quarantined"].append({"table": table, "pageId": row["id"], "key": _row_key(table, row),
                                                "code": error.code, "field": error.field, "usedLastGood": False})
        excluded[table].update(clean_excluded)
        substitutions = 0
        old_by_id = {row["id"]: row for row in previous["tables"][table]["rows"]} if previous else {}
        for row in good:
            row.update(rowSource=source, substituted=False)
        for row, error in bad:
            used = False
            if table in SUBSTITUTABLE and row["id"] in old_by_id and source == "notion":
                try:
                    old_clean, old_warnings = _clean_row(table, old_by_id[row["id"]], contract, today, resolved, excluded)
                except (_InvalidRow, _ExcludedRow):
                    pass
                else:
                    if not old_clean["rejected_text"] and all(_identity(table, old_clean) != _identity(table, other) for other in good):
                        old_clean.update(_original=old_by_id[row["id"]], rowSource="last_good", substituted=True)
                        good.append(old_clean)
                        warnings.extend(old_warnings)
                        substitutions += 1
                        used = True
            metadata["quarantined"].append({"table": table, "pageId": row["id"], "key": _row_key(table, row),
                                            "code": error.code, "field": error.field, "usedLastGood": used})
        if table == "industries":
            good.sort(key=lambda row: (-sum(row["props"][name] for name in SCORES), -row["props"]["景气度"], row["props"]["名称"]))
        elif table in ("chokepoints", "companies"):
            order = {identifier: n for n, identifier in enumerate(resolved["industries"])}
            good.sort(key=lambda row: (order[row["props"]["行业"][0]],
                                       row["props"].get("排序", 9999) if table == "chokepoints" else row["props"]["代号"],
                                       row["props"]["名称"]))
            if table == "companies" and len(good) > 80:
                dropped = good[80:]
                warnings.append(_diagnostic("company_cap_exceeded", table, dropped[0], detail={"dropped": [row["props"]["代号"] for row in dropped]}))
                excluded[table].update(row["id"] for row in dropped)
                dropped_keys = {_row_key(table, row) for row in dropped}
                warnings = [note for note in warnings if note["code"] == "company_cap_exceeded" or note["key"] not in dropped_keys]
                good = good[:80]
        else:
            good.sort(key=lambda row: row["id"])
        resolved[table] = {row["id"]: row for row in good}
        table_rows[table] = good
        metadata["warnings"].extend(warnings)
        metadata["counts"][table] = {"fetched": fetched_count, "used": len(good), "excluded": len(excluded[table]),
                                     "quarantined": len(original_bad) if quality_low and source == "last_good" else len(bad),
                                     "substituted": substitutions}
        schema = fetched.get("schema", {})
        if "properties" not in schema:
            schema = {"properties": {name: {"type": kind} for name, kind in schema.items()}}
        snapshot_tables[table] = {
            "source": source, "fetchedAt": entry["fetchedAt"] if entry else fixed_clock,
            "schemaHash": entry.get("schemaHash", "") if entry else schema_hash(schema, contract["tables"][table]),
            "rows": [row["_original"] for row in good],
        }

    company_ids = {row["props"]["代号"] for row in table_rows["companies"]}
    for table in TABLES:
        for row in table_rows[table]:
            for field, spec in contract["tables"][table]["properties"].items():
                if spec.get("tokens"):
                    unknown = [identifier for identifier in TOKEN.findall(row["props"].get(field) or "") if identifier not in company_ids]
                    if unknown:
                        metadata["warnings"].append(_diagnostic("token_unknown_company", table, row, field, {"companies": list(dict.fromkeys(unknown))}))
    from research_view import judgment
    result = {"industries": [], "chokepoints": [], "companies": []}
    names = {identifier: row["props"]["名称"] for identifier, row in resolved["industries"].items()}
    choke_names = {identifier: row["props"]["名称"] for identifier, row in resolved["chokepoints"].items()}
    for row in table_rows["industries"]:
        props = row["props"]
        scores = [props[name] for name in SCORES]
        result["industries"].append({"name": props["名称"], "s": scores, "total": sum(scores),
            "logic": props["一句话逻辑"], "signal": props["最新信号"], "risk": props["主要风险"], "reps": props["代表公司"],
            "kb": props["知识库"], "rowSource": row["rowSource"],
            "judgment": judgment(props, today, substituted=row["substituted"], banned=row["banned"])})
    for row in table_rows["chokepoints"]:
        props = row["props"]
        result["chokepoints"].append({"name": props["名称"], "ind": names[props["行业"][0]],
            "tight": contract["tables"]["chokepoints"]["properties"]["紧缺度"]["enum"][props["紧缺度"]],
            "seg": props["细分"], "why": props["为什么卡"], "track": props["跟踪指标"], "rowSource": row["rowSource"],
            "judgment": judgment(props, today, substituted=row["substituted"], banned=row["banned"])})
    for row in table_rows["companies"]:
        props = row["props"]
        flash_date = _date(props["快讯日期"])
        result["companies"].append({"id": props["代号"], "name": props["名称"], "code": props["显示代码"], "sym": props["Yahoo代码"],
            "mkt": props["市场"], "cur": props["币种"], "role": props["定位"], "ind": names[props["行业"][0]],
            "cp": choke_names.get(props["卡点"][0], "") if props["卡点"] else "", "view": props["看点"], "flash": props["快讯"],
            "next": props["下次财报日"], "url": props["知识库"], "flashDate": props["快讯日期"],
            "flashFresh": flash_date is not None and (today - flash_date).days <= 30, "flashSource": props["快讯来源"], "rowSource": row["rowSource"],
            "earnings": {"status": "confirmed" if props["下次财报日"] and props["财报日状态"] == "官方确认" and props["财报日来源"] else "unverified",
                         "source_url": props["财报日来源"], "timezone": props["财报日时区"], "time_note": props["财报日备注"]}})
    _attach_financials(result["companies"], table_rows["financials"], contract, today,
                       {row["props"]["代号"]: row["id"] for row in table_rows["companies"]})
    result["daily_rows"] = [{key: value for key, value in row.items() if not key.startswith("_")} for row in table_rows["daily"]]
    result["weekly_rows"] = [{key: value for key, value in row.items() if not key.startswith("_")} for row in table_rows["weekly"]]
    result["internal"] = {"industry_names": names,
                          "chokepoint_order": {row["props"]["名称"]: row["props"]["排序"] for row in table_rows["chokepoints"]}}
    table_order = {table: n for n, table in enumerate(TABLES)}
    metadata["warnings"].sort(key=lambda note: (table_order[note["table"]], note["key"], note["field"], note["code"]))
    metadata["quarantined"].sort(key=lambda note: (table_order[note["table"]], note["key"], note["pageId"], note["code"]))
    count = len(metadata["fallbackTables"])
    metadata["source"] = "last_good" if count == len(TABLES) else "partial" if count else "notion"
    result["snapshot"] = make_snapshot(snapshot_tables, contract, fixed_clock)
    metadata["snapshotSHA256"] = snapshot_sha256(result["snapshot"])
    result["notion"] = metadata
    return result
