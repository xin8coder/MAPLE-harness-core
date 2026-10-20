"""Exercise the real application service, Excel upload and one public update.

No API calls without --run-api. A new session is required on every run.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

from liveopt_dsh.config import ServiceConfig
from liveopt_dsh.explorer import solution_options
from liveopt_dsh.service import LiveOptService

from build_inputs import build_inputs
from scenario import INITIAL_REQUEST, TABLES, UPDATE_REQUEST
from validate_results import validate_candidates


def await_job(service, job_id):
    previous = None
    while True:
        job = service.wait_for_job(job_id, timeout_seconds=5)
        signature = (job.get("status"), job.get("phase"))
        if signature != previous:
            print(json.dumps({"job_id": job_id, "status": signature[0], "phase": signature[1]}, ensure_ascii=False), flush=True)
            previous = signature
        if job["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            if job["status"] != "succeeded":
                raise RuntimeError(str(job.get("error") or job["status"]))
            return job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-api", action="store_true")
    parser.add_argument("--offline-demo", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Reuse a completed initial turn and run its update")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--session-id", default=f"demo-garment-{int(time.time())}")
    args = parser.parse_args()
    if args.run_api and args.offline_demo:
        parser.error("Choose API or offline demo, not both")
    root = Path(__file__).resolve().parent
    workbook = build_inputs(root / "inputs")
    from offline_client import client_factory
    service = LiveOptService(ServiceConfig(state_dir=args.state_dir, workspace_root=root, network_mode="direct", max_result_archive=120),
                             client_factory=client_factory if args.offline_demo else None)
    try:
        exists = service.store.session_exists(args.session_id)
        if exists and not args.resume:
            raise ValueError("Refusing to overwrite an existing demonstration session")
        if args.resume and (not exists or service.store.load_snapshot(args.session_id)["turn"] != 0):
            raise ValueError("Resume requires a retained initial turn and no completed update")
        upload = service.store.save_upload(filename=workbook.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", payload=workbook.read_bytes())
        prepared = service.prepare_uploads([upload["upload_id"]])
        context = service.store.load_prepared_data(prepared["prepared_data_id"])["public_context"]
        for name, records in TABLES.items():
            assert context["tables"]["garment_export_" + name] == records, f"Excel import changed table {name}"
        print(json.dumps({"preflight": "passed", "tables": list(context["tables"]), "api_enabled": args.run_api}), flush=True)
        if not args.run_api and not args.offline_demo:
            return
        if args.resume:
            jobs = [json.loads(path.read_text()) for path in service.store.jobs_dir.glob("*.json")]
            initial = next(job for job in reversed(jobs) if job.get("session_id") == args.session_id and job.get("kind") == "start" and job.get("status") == "succeeded")
        else:
            started = service.submit_start(problem=INITIAL_REQUEST, prepared_data_id=prepared["prepared_data_id"],
                session_id=args.session_id, task_id="外贸服装 · 打包排班与仓储", provider="deepseek", model="offline-scripted-demo" if args.offline_demo else "deepseek-flash",
                population_size=60, generations=40, seed=17, archive_limit=120, max_repairs=2, solver_preference="evolutionary")
            initial = await_job(service, started["job_id"])
        service.export_results(args.session_id)
        first = solution_options(service.store, args.session_id, 0)
        assert first["counts"]["feasible"] > 0, "Initial search has no feasible plan"
        assert len(first["objective_names"]) == 2, "Expected separate cost and delay objectives"
        initial_validation = validate_candidates(service.store.load_snapshot(args.session_id), first)
        service.store.save_session_bytes(args.session_id, "demo_validation_t000.json", json.dumps(initial_validation).encode())
        updated = service.submit_update(session_id=args.session_id, update=UPDATE_REQUEST, update_id="t001")
        update_job = await_job(service, updated["job_id"])
        service.export_results(args.session_id)
        after = service.store.load_snapshot(args.session_id)
        changed = after["public_context"]["tables"]
        assert next(row for row in changed["garment_export_orders"] if row["id"] == "UK-204")["due_hour"] == 4.5
        assert next(row for row in changed["garment_export_teams"] if row["id"] == "B")["workers"] == 3
        second = solution_options(service.store, args.session_id, 1)
        assert second["counts"]["feasible"] > 0, "Updated search has no feasible plan"
        update_validation = validate_candidates(after, second)
        service.store.save_session_bytes(args.session_id, "demo_validation_t001.json", json.dumps(update_validation).encode())
        for payload in (first, second):
            assert all(all(math.isfinite(value) for value in row["objectives"]) for row in payload["candidates"] if row["selectable"])
        manifest = {
            "session_id": args.session_id, "model": "offline-scripted-demo" if args.offline_demo else "deepseek-flash",
            "mode": "offline_numerical" if args.offline_demo else "real_api_simulated_business_data",
            "population_size": 60, "generations": 40, "seed": 17,
            "initial_counts": first["counts"], "updated_counts": second["counts"],
            "initial_job": initial["job_id"], "update_job": update_job["job_id"],
            "initial_objectives": first["objective_names"], "updated_objectives": second["objective_names"],
            "validation": {"initial": initial_validation, "update": update_validation},
        }
        # Demo provenance is display metadata, not an input to optimization.
        after["demo_metadata"] = {"mode": manifest["mode"], "data": "fictitious_garment_export", "language": "zh", "validation": "passed"}
        service.store.save_snapshot(args.session_id, after)
        for name in ("garment_export.xlsx", "initial_request.txt", "update_1.txt", "natural_language_data.txt"):
            service.store.save_session_bytes(args.session_id, "demo_inputs/" + name, (root / "inputs" / name).read_bytes())
        service.store.save_session_bytes(args.session_id, "demo_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode())
        print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    finally:
        service.close()


if __name__ == "__main__":
    main()
