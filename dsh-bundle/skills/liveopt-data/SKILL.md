---
name: liveopt-data
description: Prepare uploaded documents and public data files before LiveOpt optimization.
---

# LiveOpt Data

Use `mcp__liveopt__liveopt_prepare_data` when optimization data is stored in public files rather than already supplied as a structured object.

When the question contains browser-generated `[LiveOpt upload: ...; id=...]` references, use `mcp__liveopt__liveopt_prepare_uploads` instead. Send all referenced ids together so document prose and data tables become one public context. TXT, Markdown, PDF, and DOCX are extracted as named public documents; CSV, TSV, JSON, JSONL, and XLSX are converted into typed tables. Do not paste extracted content back into the conversation.

- Pass one source entry per file. Each entry requires `path` and may set `table_name` and `id_column`. `sources` may be empty when all public records come from `inline_tables`.
- Put finite resource records and mutable parameters stated in the user's natural-language request in `inline_tables`. This is public data extraction, not an inferred hidden contract. Preserve exactly the identifiers and values the user supplied.
- Use `column_groups` to relationalize repeated wide columns. Each group names `source_table`, `output_table`, `source_id_column`, `entity_id_name`, and `fields`, where every field value is a visible column template containing `{id}`. For example, `{"processing_h":"p_{id}_h","eligible":"eligible_{id}"}` turns repeated machine columns into one row per source/entity pair. The transformation is generic and must be derived from visible headers rather than a benchmark name.
- Paths must remain inside the selected workspace. Do not copy file contents into the conversation.
- Preserve the returned `prepared_data_id` and pass it to `mcp__liveopt__liveopt_start`.
- Read the returned table summary to confirm row counts, normalized columns, and the public identifier column. If a source is ambiguous, ask the user only for the missing table or identifier meaning; do not invent schema semantics.
- The adapter preserves source-column mappings in the data dictionary and converts unambiguous CSV scalar columns to booleans, integers, or numbers. Public identifiers and leading-zero values remain strings.
- Confirm that every resource which may later be added, removed, disabled, or edited appears in a table. If it does not, add an inline public table before optimization instead of allowing `setup.py` to embed a fixed list.

## Native-language spreadsheets

If preparation returns `mapping_required: true`, read `schema_preview` and call `mcp__liveopt__liveopt_map_data` before starting. You infer semantic names from the original headers, sample cells, units, and the user's request. Supply each normalized source table with `name`, `display_name`, and `columns` mapping every normalized source column to a descriptive ASCII snake_case name. Set `id_column` only for a truly unique identifier. Use original-language display names and `language` matching the user's request. The tool validates a one-to-one renaming and returns a NEW `prepared_data_id`; use that id for solving.

`table_mappings` is an object keyed by the returned normalized table name, not an array. Its `name` is the NEW semantic name. Shape: `{"field_abc":{"name":"orders","display_name":"订单","columns":{"field_def":"order_id"},"id_column":"order_id"}}`. Include every actual table and column; these sample identifiers are illustrative only.

Keep Chinese entity names and identifiers as cell values. Do not rewrite numeric values, dates, units, objective definitions, or business rules during translation. If a header is ambiguous, ask a short business question in the user's language. Do not ask the user to translate the workbook or to request Chinese replies explicitly.

Use optional `result_labels` for derived solution fields and objectives, e.g. `{"total_cost":"总成本（元）","arrival_hour":"到港时刻（开工后小时）"}`. Labels for existing fields come from the source headers. Paths such as `orders.id` disambiguate fields shared by different tables. Persisted mappings accompany later updates and result exports; do not recreate English IDs on each turn.
