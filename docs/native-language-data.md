# Native-language data

The application accepts Chinese worksheet names, headers, and entity names.
Users do not need to translate their workbook or explicitly ask for Chinese
replies. The latest user message determines reply language. The interface
language is only a fallback for language-neutral input.

## Mapping workflow

1. `liveopt_prepare_uploads` or `liveopt_prepare_data` retains original schema
   labels and returns a compact `schema_preview` when mapping is needed.
2. The Harness LLM proposes `table_mappings` through `liveopt_map_data`.
   Tables and columns must map one-to-one to canonical names. Missing fields,
   collisions, invalid identifiers, and contradictory source labels are rejected.
3. The returned prepared-data identifier refers to a new immutable record.
   Numeric values, units, entity identifiers, and original input files do not
   change. Code reads canonical keys and keeps original entity values.
4. Prose-only tables and uploaded requirement documents reach the Workbench
   generator in full. Incomplete documents and oversized prose require smaller
   complete inputs instead of silently dropping business rules.
5. The mapping remains in session state during updates. Export maps solution
   fields back to source labels. New result fields are reported through
   `unmapped_result_fields`; the LLM can label their actual paths with another
   `liveopt_export(result_labels=...)` call. Those labels are stored per turn,
   without modifying numerical results or earlier turns.

Localized CSV/JSON copies and `field_mapping.json` accompany the canonical raw
files. The explorer uses the same labels while plotting original numbers.
Semantic ambiguity still requires clarification; schema validation alone does
not establish that an LLM understood every business rule correctly.

## Chinese garment example

`examples/garment_export/inputs/chinese/` contains a Chinese-only workbook and
three conversational inputs. They contain no instruction to respond in Chinese.
The example is fictitious and uses the same numerical data as the English-keyed
workbook, with Chinese entity identifiers.

Generate inputs without an API call:

```bash
python examples/garment_export/build_chinese_inputs.py
```

Run a paid integration check explicitly:

```bash
PYTHONPATH=src python examples/garment_export/run_chinese_demo.py \
  --run-api --state-dir /tmp/maple-chinese-test --session-id chinese-test
```

Use the application's normal provider output limit. A forced 5,000-token limit
can truncate reasoning plus generated code and is not representative of the
deployed configuration. `--reuse-mapping` accepts a previously validated schema
response for the same workbook schema, avoiding another translation call.

The 2026-09-29 Flash check (`demo-chinese-20260929-v3`) passed independent public
business-rule validation for 26 initial and 30 updated retained candidates.
The update changes the UK order deadline and the second team's headcount.
Only this validated session was copied into the deployed application.
These are application checks, not paper benchmark measurements.

Verification includes 72 Python tests, the installed DSH prompt assembly test,
and browser checks at 1440px and 430px for selection, nonblank chart canvases,
Chinese result fields, and a Unicode-filename Excel download.
