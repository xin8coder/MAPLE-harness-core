"""Scripted responses for an explicitly labeled offline demo, not an LLM.

TSS operators, search, data-patch application, persistence and exports are real.
Only the provider responses are replaced with these inspectable fixtures.
"""
import json


SETUP = '''
def build_problem(public_context):
    tables = public_context["tables"]
    orders = tables["garment_export_orders"]
    teams = tables["garment_export_teams"]
    warehouses = tables["garment_export_warehouses"]
    ids = [row["id"] for row in orders]
    return {
        "data": {"orders": orders, "teams": teams, "warehouses": warehouses,
                 "policy": tables["garment_export_policy"][0]},
        "segments": [
            {"name": "team", "kind": "assignment", "demands": ids, "resources": [row["id"] for row in teams]},
            {"name": "warehouse", "kind": "assignment", "demands": ids, "resources": [row["id"] for row in warehouses]},
            {"name": "sequence", "kind": "permutation", "values": ids},
        ],
        "solver_mode": "moea", "objective_names": ["cost_cny", "late_carton_hours"],
    }
'''

FITNESS = '''
def evaluate(genome, data):
    orders = {row["id"]: row for row in data["orders"]}
    teams = {row["id"]: row for row in data["teams"]}
    warehouses = {row["id"]: row for row in data["warehouses"]}
    clock = {key: 0.0 for key in teams}
    used = {key: 0 for key in warehouses}
    storage = 0.0
    shipping = 0.0
    delay = 0.0
    plan = []
    for key in genome["sequence"]:
        order = orders[key]
        tid = genome["team"][key]
        wid = genome["warehouse"][key]
        team = teams[tid]
        warehouse = warehouses[wid]
        cartons = float(order["cartons"])
        duration = float(data["policy"]["setup_hours_per_order"])
        duration += cartons * float(order["minutes_per_carton"]) / (60.0 * float(team["workers"]) * float(team["efficiency"]))
        start = clock[tid]
        clock[tid] += duration
        arrival = clock[tid] + float(warehouse["transfer_hours"])
        late = max(0.0, arrival - float(order["due_hour"]))
        delay += late * cartons
        used[wid] += cartons
        storage += cartons * float(warehouse["storage_cny_carton"])
        shipping += cartons * float(warehouse["shipping_cny_carton"])
        plan.append({"order_id": key, "customer": order["customer"], "team": tid, "warehouse": wid,
                     "start_hour": start, "finish_hour": clock[tid], "arrival_hour": arrival,
                     "due_hour": float(order["due_hour"]), "late_hours": late, "cartons": cartons})
    violations = {}
    labor = 0.0
    shifts = []
    for key, team in teams.items():
        hours = clock[key]
        overtime = max(0.0, hours - float(team["regular_hours"]))
        wage = float(team["wage_cny_hour"]) * float(team["workers"])
        labor += wage * (hours + overtime * (float(data["policy"]["overtime_multiplier"]) - 1.0))
        excess = max(0.0, hours - float(team["max_hours"]))
        if excess > 1e-9:
            violations["team_hours_" + key] = excess
        shifts.append({"team": key, "workers": team["workers"], "start_hour": 0,
                       "finish_hour": hours, "overtime_hours": overtime})
    storage_plan = []
    for key, warehouse in warehouses.items():
        excess = max(0.0, used[key] - float(warehouse["capacity"]))
        if excess > 1e-9:
            violations["warehouse_capacity_" + key] = excess
        storage_plan.append({"warehouse": key, "used": used[key], "capacity": warehouse["capacity"]})
    cost = labor + storage + shipping
    return penalty_result(cost, violations, objectives=[cost, delay], solution={
        "order_plan": plan, "worker_shifts": shifts, "warehouse_plan": storage_plan,
        "cost_breakdown": {"labor_cny": labor, "warehouse_cny": storage, "shipping_cny": shipping},
        "total_cost_cny": cost, "late_carton_hours": delay,
    })
'''


class OfflineClient:
    model = "offline-scripted-demo"

    def chat(self, messages, **kwargs):
        system = next(message["content"] for message in messages if message["role"] == "system").lower()
        if "fill setup.py and fitness.py slots" in system:
            result = {"setup.py": SETUP, "fitness.py": FITNESS}
        elif "classify dynamic optimization updates" in system:
            result = {"data_update": True, "patch_setup": False, "patch_fitness": False,
                      "restart_skill": "warm_restart_v1", "reason": "Public deadline and team-size changes only.", "state_binding_queries": []}
        elif "patch public optimization data" in system:
            result = {"operations": [
                {"op": "update_row", "path": ["tables", "garment_export_orders"], "match": {"id": "UK-204"}, "values": {"due_hour": 4.5}},
                {"op": "update_row", "path": ["tables", "garment_export_teams"], "match": {"id": "B"}, "values": {"workers": 3}},
            ], "reason": "UK-204 cutoff is 12:30; team B has three workers."}
        elif "semantic channel" in system:
            result = {"reuse_risk": "medium", "change_mechanisms": ["deadline", "capacity"], "full_vote": False,
                      "evidence_paths": ["tables.garment_export_orders", "tables.garment_export_teams"], "reason": "Representation and objectives are unchanged."}
        else:
            raise AssertionError("Unimplemented offline prompt: " + system[:120])
        return {"choices": [{"message": {"content": json.dumps(result)}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "simulated": True}}


def client_factory(**kwargs):
    return OfflineClient()
