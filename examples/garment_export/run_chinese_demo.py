"""Paid Flash smoke test, opt-in only: infer schema, solve, update, and validate."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import time

from evo2.agents.liveopt_dynamic_impl import _extract_json_object
from liveopt_dsh.config import ServiceConfig
from liveopt_dsh.explorer import solution_options
from liveopt_dsh.service import LiveOptService

from build_chinese_inputs import INITIAL, CONFIRM, UPDATE, SCHEMA, chinese_tables
from build_inputs import build_inputs
from run_demo import await_job
from validate_results import validate_candidates


def validate_mapped(snapshot, options):
    # The independent checker knows source headers, not the LLM's chosen aliases.
    normalized = copy.deepcopy(snapshot)
    context = normalized["public_context"]
    original_tables = context["tables"]
    rebuilt = {}
    for expected, (source_name, source_columns) in SCHEMA.items():
        record = next(item for item in context["localization"]["tables"]
                      if item["source_name"].endswith("_" + source_name))
        aliases = {col["source_name"]: col["name"] for col in record["columns"]}
        rebuilt["garment_export_" + expected] = [
            {key: row[aliases[source]] for key, source in source_columns.items()}
            for row in original_tables[record["name"]]]
    context["tables"] = rebuilt
    return validate_candidates(normalized, options), rebuilt


def label_export(service, session):
    exported = service.export_results(session)
    missing = exported["unmapped_result_fields"]
    if not missing:
        return exported
    options = solution_options(service.store, session)
    context = {"unmapped_result_fields": missing, "existing_labels": exported["localization"]["labels"],
               "solution_example": options["candidates"][0]["solution"]}
    client = service._create_client("deepseek", "deepseek-flash")
    reply = client.chat([
        {"role": "system", "content": "Follow the user's language. Return a JSON object result_labels mapping each supplied result field path to a concise display label. Do not translate entity IDs, change data, or add unknown fields. Preserve units in existing labels. This is display-only localization, not optimization."},
        {"role": "user", "content": "把这些结果栏目和我表格里的叫法对齐，方便我看方案。\n" + json.dumps(context, ensure_ascii=False)},
    ], max_tokens=4096, json_mode=True)
    labels = _extract_json_object(reply["choices"][0]["message"]["content"])["result_labels"]
    exported = service.export_results(session, result_labels=labels)
    service.store.save_session_bytes(session, f"exports/t{exported['turn']:03d}/label_model_reply.json",
                                     json.dumps({"labels": labels, "usage": reply.get("usage")}, ensure_ascii=False, indent=2).encode())
    return exported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-api", action="store_true")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--session-id", default=f"demo-chinese-{int(time.time())}")
    parser.add_argument("--reuse-mapping", type=Path, help="Reuse a checked schema response for the same workbook schema")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    workbook = build_inputs(root / "inputs" / "chinese", tables=chinese_tables(),
                           filename="服装外贸排产数据.xlsx", texts=[("初始需求.txt", INITIAL),
                               ("确认求解.txt", CONFIRM), ("更新需求.txt", UPDATE)])
    if not args.run_api:
        print(f"Prepared {workbook}; pass --run-api to enable paid requests.")
        return
    service = LiveOptService(ServiceConfig(state_dir=args.state_dir, workspace_root=root,
                            network_mode="direct", max_result_archive=100))
    try:
        if service.store.session_exists(args.session_id):
            raise ValueError("Refusing to overwrite an existing session")
        upload = service.store.save_upload(filename=workbook.name, payload=workbook.read_bytes(),
                                           media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        raw = service.prepare_uploads([upload["upload_id"]])
        skill = (root.parents[1] / "dsh-bundle/skills/liveopt-data/SKILL.md").read_text()
        client = service._create_client("deepseek", "deepseek-flash")
        messages = [
            {"role": "system", "content": skill + "\nRespond in the language of the latest user request without asking for a language command. "
             "For this tool test return JSON with language, table_mappings, result_labels, explanation. "
             "Use the same argument schema as liveopt_map_data. Infer all aliases only from the schema preview and user request. "
             "The explanation is a brief user-facing explanation. Do not solve the optimization in this response."},
            {"role": "user", "content": INITIAL},
            {"role": "user", "content": "数据工具返回的表头与样例：\n" + json.dumps(raw, ensure_ascii=False)},
        ]
        if args.reuse_mapping:
            proposed = json.loads(args.reuse_mapping.read_text())
            reply = {"usage": {"reused_schema_mapping": True}}
        else:
            reply = client.chat(messages, max_tokens=8192, json_mode=True)
            proposed = _extract_json_object(reply["choices"][0]["message"]["content"])
        service.store.save_session_bytes(args.session_id, "schema_mapping_reply.json", json.dumps(proposed, ensure_ascii=False, indent=2).encode())
        assert re.search(r"[\u3400-\u9fff]", proposed.get("explanation", ""))
        mapped = service.map_data(raw["prepared_data_id"], proposed["table_mappings"],
                                  language=proposed["language"], result_labels=proposed.get("result_labels"))
        print(json.dumps({"mapping": "passed", "language": mapped["language"], "tables": [t["name"] for t in mapped["tables"]]}, ensure_ascii=False), flush=True)
        session = args.session_id
        service.store.save_session_bytes(session, "schema_mapping_reply.json", json.dumps(proposed, ensure_ascii=False, indent=2).encode())
        for name in (workbook.name, "初始需求.txt", "确认求解.txt", "更新需求.txt"):
            service.store.save_session_bytes(session, "demo_inputs/" + name, (workbook.parent / name).read_bytes())
        started = service.submit_start(problem=INITIAL + "\n" + CONFIRM, prepared_data_id=mapped["prepared_data_id"],
                                       session_id=session, task_id="中文外贸服装排产", solver_preference="evolutionary",
                                       population_size=60, generations=40, max_repairs=2, seed=17)
        await_job(service, started["job_id"])
        service.export_results(session)
        first = solution_options(service.store, session)
        initial_check, _ = validate_mapped(service.store.load_snapshot(session), first)
        assert first["counts"]["feasible"] > 0
        label_export(service, session)
        updated = service.submit_update(session_id=session, update=UPDATE, update_id="t001")
        await_job(service, updated["job_id"])
        exported = service.export_results(session)
        second = solution_options(service.store, session)
        update_check, tables = validate_mapped(service.store.load_snapshot(session), second)
        assert second["counts"]["feasible"] > 0
        exported = label_export(service, session)
        assert next(r for r in tables["garment_export_orders"] if r["id"] == "英国二号")["due_hour"] == 4.5
        assert next(r for r in tables["garment_export_teams"] if r["id"] == "乙组")["workers"] == 3
        assert all(re.search(r"[\u3400-\u9fff]", name) for name in exported["objective_names"])
        manifest = {"session_id": session, "model": "deepseek-flash", "mode": "real_api_simulated_business_data",
                    "mapping_usage": reply.get("usage"), "initial": initial_check, "update": update_check,
                    "initial_counts": first["counts"], "updated_counts": second["counts"],
                    "objective_names": exported["objective_names"], "language": "zh"}
        service.store.save_session_bytes(session, "chinese_demo_validation.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode())
        snapshot = service.store.load_snapshot(session)
        snapshot["demo_metadata"] = {"mode": manifest["mode"], "validation": "passed", "language": "zh"}
        service.store.save_snapshot(session, snapshot)
        print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    finally:
        service.close()


if __name__ == "__main__":
    main()
