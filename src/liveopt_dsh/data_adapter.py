"""Deterministic public-data preparation for LiveOpt Workbenches."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .serialization import json_safe
from .store import StateStore


SUPPORTED_SUFFIXES = frozenset({".csv", ".tsv", ".json", ".jsonl"})
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]+")
_INTEGER = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)$")
_FLOAT = re.compile(
    r"^[+-]?(?:(?:[0-9]+\.[0-9]*)|(?:[0-9]*\.[0-9]+)|(?:[0-9]+))(?:[eE][+-]?[0-9]+)?$"
)


def prepare_public_data(
    store: StateStore,
    workspace_root: Path,
    sources: list[dict[str, Any]] | None = None,
    *,
    inline_tables: dict[str, list[dict[str, Any]]] | None = None,
    column_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert public files and inline records into named relational tables."""

    sources = list(sources or [])
    inline_tables = dict(inline_tables or {})
    if not sources and not inline_tables:
        raise ValueError("provide at least one public data source or inline table")
    tables: dict[str, list[dict[str, Any]]] = {}
    dictionary: dict[str, Any] = {}
    source_records: list[dict[str, Any]] = []
    for raw_source in sources:
        if not isinstance(raw_source, dict):
            raise ValueError("each source must be an object with a path")
        raw_path = str(raw_source.get("path") or "").strip()
        if not raw_path:
            raise ValueError("each source requires path")
        path = store.resolve_public_path(raw_path, workspace_root)
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(
                f"unsupported public data format {suffix!r}; use CSV, TSV, JSON, or JSONL"
            )
        requested_name = str(raw_source.get("table_name") or "").strip()
        requested_id = str(raw_source.get("id_column") or "").strip()
        loaded = _load_source(path, requested_name=requested_name)
        if requested_name and len(loaded) != 1:
            raise ValueError("table_name can rename only a source containing one table")
        for source_name, records in loaded.items():
            table_name = _safe_name(requested_name or source_name)
            if table_name in tables:
                raise ValueError(
                    f"duplicate prepared table {table_name!r}; set distinct table_name values"
                )
            normalized, metadata = _normalize_records(
                records,
                id_column=requested_id,
                infer_scalars=suffix in {".csv", ".tsv"},
            )
            tables[table_name] = normalized
            dictionary[table_name] = {
                "source": str(path.relative_to(workspace_root.resolve())),
                "row_count": len(normalized),
                **metadata,
            }
            source_records.append(
                {
                    "path": str(path.relative_to(workspace_root.resolve())),
                    "format": suffix.removeprefix("."),
                    "table": table_name,
                }
            )

    for raw_name, records in inline_tables.items():
        table_name = _safe_name(raw_name)
        if table_name in tables:
            raise ValueError(f"duplicate prepared table {table_name!r}")
        normalized, metadata = _normalize_records(
            _records(records), id_column="", infer_scalars=False
        )
        tables[table_name] = normalized
        dictionary[table_name] = {
            "source": "inline_public_data",
            "row_count": len(normalized),
            **metadata,
        }
        source_records.append(
            {"path": None, "format": "inline", "table": table_name}
        )

    for group in list(column_groups or []):
        _materialize_column_group(tables, dictionary, source_records, group)

    public_context = {
        "tables": tables,
        "data_dictionary": dictionary,
        "prepared_sources": source_records,
    }
    canonical = json.dumps(
        json_safe(public_context), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    data_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    record = {
        "schema_version": 1,
        "prepared_data_id": data_id,
        "public_context": public_context,
    }
    artifact = store.save_prepared_data(data_id, record)
    return {
        "prepared_data_id": data_id,
        "artifact": str(artifact.relative_to(store.root)),
        "tables": [
            {
                "name": name,
                "rows": len(tables[name]),
                "columns": dictionary[name]["columns"],
                "id_column": dictionary[name]["id_column"],
            }
            for name in tables
        ],
    }


def _materialize_column_group(
    tables: dict[str, list[dict[str, Any]]],
    dictionary: dict[str, Any],
    source_records: list[dict[str, Any]],
    raw_group: dict[str, Any],
) -> None:
    """Relationalize repeated wide columns using user-visible naming templates."""

    if not isinstance(raw_group, dict):
        raise ValueError("each column_groups entry must be an object")
    raw_source_table = str(raw_group.get("source_table") or "").strip()
    raw_output_table = str(raw_group.get("output_table") or "").strip()
    if not raw_source_table or not raw_output_table:
        raise ValueError("column group requires source_table and output_table")
    source_table = _safe_name(raw_source_table)
    output_table = _safe_name(raw_output_table)
    if source_table not in tables:
        raise ValueError(f"column group source table does not exist: {source_table!r}")
    if output_table in tables:
        raise ValueError(f"column group output table already exists: {output_table!r}")
    raw_fields = raw_group.get("fields")
    if not isinstance(raw_fields, dict) or not raw_fields:
        raise ValueError("column group requires fields: {output_name: column_{id}_template}")
    fields = {
        _safe_name(name): str(template).strip().lower()
        for name, template in raw_fields.items()
    }
    if any(template.count("{id}") != 1 for template in fields.values()):
        raise ValueError("every column group field template must contain exactly one {id}")

    rows = tables[source_table]
    columns = {
        str(key)
        for row in rows
        if isinstance(row, dict)
        for key in row
    }
    entity_ids: set[str] = set()
    for template in fields.values():
        prefix, suffix = template.split("{id}", 1)
        for column in columns:
            lowered = column.lower()
            if not lowered.startswith(prefix) or not lowered.endswith(suffix):
                continue
            stop = len(lowered) - len(suffix) if suffix else len(lowered)
            identifier = lowered[len(prefix) : stop]
            if identifier:
                entity_ids.add(identifier)
    if not entity_ids:
        raise ValueError(
            f"column group templates matched no columns in table {source_table!r}"
        )

    source_id_column = _safe_name(
        raw_group.get("source_id_column")
        or dictionary[source_table].get("id_column")
        or "row_id"
    )
    source_id_name = _safe_name(raw_group.get("source_id_name") or source_id_column)
    entity_id_name = _safe_name(raw_group.get("entity_id_name") or "entity_id")
    entity_case = str(raw_group.get("entity_id_case") or "preserve").strip().lower()
    if entity_case not in {"preserve", "lower", "upper"}:
        raise ValueError("entity_id_case must be preserve, lower, or upper")

    materialized: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        source_id = row.get(source_id_column, row_index)
        for identifier in sorted(entity_ids):
            output_id = identifier
            if entity_case == "upper":
                output_id = identifier.upper()
            elif entity_case == "lower":
                output_id = identifier.lower()
            record: dict[str, Any] = {
                source_id_name: source_id,
                entity_id_name: output_id,
            }
            present = False
            for output_name, template in fields.items():
                column = template.replace("{id}", identifier)
                value = row.get(column)
                record[output_name] = value
                present = present or value is not None
            if present:
                materialized.append(record)

    column_names = [source_id_name, entity_id_name, *fields]
    tables[output_table] = materialized
    dictionary[output_table] = {
        "source": f"derived:{source_table}",
        "row_count": len(materialized),
        "columns": [
            {
                "name": name,
                "source_name": name,
                "type": _native_column_type([row.get(name) for row in materialized]),
            }
            for name in column_names
        ],
        "column_aliases": {name: name for name in column_names},
        "id_column": None,
        "derived_from": source_table,
        "column_group": json_safe(raw_group),
    }
    source_records.append(
        {
            "path": None,
            "format": "column_group",
            "table": output_table,
            "source_table": source_table,
        }
    )


def _native_column_type(values: list[Any]) -> str:
    present = [value for value in values if value is not None]
    if present and all(isinstance(value, bool) for value in present):
        return "boolean"
    if present and all(isinstance(value, int) and not isinstance(value, bool) for value in present):
        return "integer"
    if present and all(
        isinstance(value, (int, float)) and not isinstance(value, bool) for value in present
    ):
        return "number"
    return "string"


def _load_source(path: Path, *, requested_name: str) -> dict[str, list[dict[str, Any]]]:
    suffix = path.suffix.lower()
    fallback = requested_name or path.stem
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if not reader.fieldnames:
                raise ValueError(f"public data file has no header: {path}")
            return {fallback: [dict(row) for row in reader]}
    if suffix == ".jsonl":
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row {line_number} must be an object")
            records.append(row)
        return {fallback: records}

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict) and isinstance(payload.get("public_context"), dict):
        payload = payload["public_context"]
    if isinstance(payload, dict) and isinstance(payload.get("tables"), dict):
        return {
            str(name): _records(value)
            for name, value in payload["tables"].items()
        }
    if isinstance(payload, dict) and payload and all(
        isinstance(value, list) for value in payload.values()
    ):
        return {str(name): _records(value) for name, value in payload.items()}
    return {fallback: _records(payload)}


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(value)]
    if not isinstance(value, list):
        raise ValueError("a prepared JSON table must be an object or a list")
    records: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        if isinstance(row, dict):
            records.append(dict(row))
        else:
            records.append({"value": row, "row_index": index})
    return records


def _normalize_records(
    records: list[dict[str, Any]],
    *,
    id_column: str,
    infer_scalars: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_columns: list[str] = []
    for row in records:
        for key in row:
            key = str(key).strip()
            if key and key not in source_columns:
                source_columns.append(key)
    aliases: dict[str, str] = {}
    used: set[str] = set()
    for source in source_columns:
        base = _safe_name(source)
        alias = base
        counter = 2
        while alias in used:
            alias = f"{base}_{counter}"
            counter += 1
        aliases[source] = alias
        used.add(alias)

    columns: dict[str, list[Any]] = {aliases[name]: [] for name in source_columns}
    for row in records:
        stripped = {str(key).strip(): value for key, value in row.items()}
        for source in source_columns:
            columns[aliases[source]].append(stripped.get(source))
    normalized_columns: dict[str, list[Any]] = {}
    types: dict[str, str] = {}
    requested_id_alias = aliases.get(id_column, id_column if id_column in used else "")
    inferred_id = requested_id_alias or _infer_id_column(list(columns))
    for name, values in columns.items():
        converted, type_name = _infer_values(
            values,
            allow_numeric=infer_scalars and name != inferred_id,
        )
        normalized_columns[name] = converted
        types[name] = type_name
    normalized = [
        {name: normalized_columns[name][index] for name in normalized_columns}
        for index in range(len(records))
    ]
    return normalized, {
        "columns": [
            {
                "name": aliases[source],
                "source_name": source,
                "type": types[aliases[source]],
            }
            for source in source_columns
        ],
        "column_aliases": aliases,
        "id_column": inferred_id or None,
    }


def _infer_values(values: list[Any], *, allow_numeric: bool) -> tuple[list[Any], str]:
    if not allow_numeric:
        converted = [_empty_to_none(value) for value in values]
        present_native = [value for value in converted if value is not None]
        if present_native and all(isinstance(value, bool) for value in present_native):
            return converted, "boolean"
        if present_native and all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in present_native
        ):
            return converted, "integer"
        if present_native and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in present_native
        ):
            return converted, "number"
        return converted, "string"
    present = [str(value).strip() for value in values if _empty_to_none(value) is not None]
    lowered = {value.lower() for value in present}
    if present and lowered <= {"true", "false", "yes", "no"}:
        return [
            None if _empty_to_none(value) is None else str(value).strip().lower() in {"true", "yes"}
            for value in values
        ], "boolean"
    if present and all(_INTEGER.fullmatch(value) and not _has_leading_zero(value) for value in present):
        return [None if _empty_to_none(value) is None else int(str(value).strip()) for value in values], "integer"
    if present and any(_has_leading_zero(value) for value in present):
        return [_empty_to_none(value) for value in values], "string"
    if present and all(_FLOAT.fullmatch(value) for value in present):
        return [None if _empty_to_none(value) is None else float(str(value).strip()) for value in values], "number"
    return [_empty_to_none(value) for value in values], "string"


def _infer_id_column(columns: list[str]) -> str:
    for candidate in columns:
        lowered = candidate.lower()
        if lowered == "id" or lowered.endswith("_id"):
            return candidate
    return ""


def _empty_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _has_leading_zero(value: str) -> bool:
    unsigned = value.lstrip("+-")
    return unsigned.isdigit() and len(unsigned) > 1 and unsigned.startswith("0")


def _safe_name(value: str) -> str:
    cleaned = _SAFE_NAME.sub("_", str(value).strip()).strip("_").lower()
    if not cleaned:
        cleaned = "table"
    if cleaned[0].isdigit():
        cleaned = f"field_{cleaned}"
    return cleaned
