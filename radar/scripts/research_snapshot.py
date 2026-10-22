"""Deterministic, credential-free last-good research snapshots."""

from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
import re
from pathlib import Path


TABLES = ("industries", "chokepoints", "companies", "financials", "daily", "weekly")
SUBSTITUTABLE = frozenset(TABLES[:4])


class ResearchAbort(Exception):
    """A publication blocker whose public attributes contain only safe diagnostics."""

    def __init__(self, code="no_last_good", *, codes=None, detail=None):
        self.code = code
        self.codes = list(dict.fromkeys([*(codes or []), code]))
        self.detail = detail or {}
        self.exit_code = 2
        super().__init__(code)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


def snapshot_sha256(snapshot):
    return hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()


def schema_hash(schema, table_contract):
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    shape = {
        name: properties.get(name, {}).get("type", spec["type"])
        for name, spec in table_contract["properties"].items() if spec["level"] != "ignore"
    }
    return "sha256:" + hashlib.sha256(canonical_json(shape).encode("utf-8")).hexdigest()


def load_last_good(value, contract=None):
    """Return a validated independent snapshot, or None for absent/invalid input."""
    if value is None:
        return None
    try:
        if isinstance(value, dict):
            snapshot = copy.deepcopy(value)
        elif isinstance(value, bytes):
            snapshot = json.loads(value.decode("utf-8"))
        elif isinstance(value, str) and value.lstrip().startswith("{"):
            snapshot = json.loads(value)
        else:
            snapshot = json.loads(Path(value).read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict):
            return None
        expected = str((contract or {}).get("contract_version", "v3.0")).removeprefix("v")
        if snapshot.get("schemaVersion") != 1 or str(snapshot.get("contractVersion", "")).removeprefix("v") != expected:
            return None
        if snapshot.get("notionVersion") != (contract or {}).get("notion_version", "2026-03-11"):
            return None
        if datetime.fromisoformat(snapshot['builtAt']).tzinfo is None:
            return None
        for table in TABLES:
            entry = snapshot["tables"][table]
            if not isinstance(entry, dict) or not isinstance(entry["rows"], list) or not isinstance(entry["fetchedAt"], str):
                return None
            if (entry.get('source') not in ('notion', 'last_good') or
                    not isinstance(entry.get('schemaHash'), str) or
                    not re.fullmatch(r'sha256:[0-9a-f]{64}', entry['schemaHash']) or
                    datetime.fromisoformat(entry['fetchedAt']).tzinfo is None):
                return None
            seen = set()
            for row in entry["rows"]:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not isinstance(row.get("props"), dict):
                    return None
                if row["id"] in seen or not all(isinstance(row.get(key), str) for key in ("created_time", "last_edited_time")):
                    return None
                seen.add(row["id"])
        canonical_json(snapshot)
        return snapshot
    except (OSError, ValueError, TypeError, KeyError):
        return None


def make_snapshot(tables, contract, fixed_clock):
    result = {
        "schemaVersion": 1,
        "contractVersion": str(contract["contract_version"]).removeprefix("v"),
        "notionVersion": contract["notion_version"],
        "builtAt": fixed_clock,
        "tables": {},
    }
    for name in TABLES:
        entry = tables[name]
        rows = []
        for row in entry["rows"]:
            rows.append({key: copy.deepcopy(row[key]) for key in ("id", "created_time", "last_edited_time", "props")})
        result["tables"][name] = {
            "source": entry["source"], "fetchedAt": entry["fetchedAt"],
            "schemaHash": entry["schemaHash"], "rows": sorted(rows, key=lambda row: row["id"]),
        }
    return result


def write_snapshot(path, snapshot):
    """Atomic write; callers validate the complete release before publishing it."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_bytes(canonical_json(snapshot).encode("utf-8"))
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
