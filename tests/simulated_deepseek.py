"""Prompt-driven, no-network DeepSeek simulator for application regression tests."""

from __future__ import annotations

import json
from typing import Any


HEALTHCARE_SETUP = '''
def build_problem(public_context):
    tables = public_context["tables"]
    programs = [dict(row) for row in tables["programs"]]
    budget = float(tables["policy"][0]["budget"])
    variables = []
    objective = {}
    extraction = []
    for index, row in enumerate(programs):
        name = "x_" + str(index)
        variables.append({"name": name, "type": "binary", "lb": 0, "ub": 1})
        objective[name] = float(row["health_gain"])
        extraction.append({"var": name, "id": row["id"]})
    constraint = {
        "coefficients": {"x_" + str(index): float(row["cost"]) for index, row in enumerate(programs)},
        "sense": "<=",
        "rhs": budget,
    }
    return {
        "data": {"programs": programs, "budget": budget},
        "segments": [],
        "solver_mode": "linear_mip",
        "objective_names": ["health_gain"],
        "linear_program_spec": {
            "variables": variables,
            "objective": {"coefficients": objective},
            "sense": "maximize",
            "constraints": [constraint],
            "solution_extraction": {
                "type": "binary_selection",
                "variables": extraction,
                "selected_field": "selected_programs",
            },
        },
    }
'''

HEALTHCARE_FITNESS = '''
def evaluate(genome, data):
    return penalty_result(0.0, {}, objectives=[0.0], solution={"selected_programs": []})
'''

ROUTING_SETUP = '''
def build_problem(public_context):
    cities = [dict(row) for row in public_context["tables"]["cities"]]
    ids = [row["id"] for row in cities]
    return {
        "data": {"cities": cities},
        "segments": [{"name": "tour", "kind": "permutation", "values": ids}],
        "solver_mode": "scalar_ga",
        "objective_names": ["route_length"],
    }
'''

ROUTING_FITNESS = '''
def evaluate(genome, data):
    tour = list(genome["tour"])
    coordinates = {row["id"]: (float(row["x"]), float(row["y"])) for row in data["cities"]}
    length = 0.0
    for index, city in enumerate(tour):
        nxt = tour[(index + 1) % len(tour)]
        x1, y1 = coordinates[city]
        x2, y2 = coordinates[nxt]
        length += math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
    return penalty_result(length, {}, objectives=[length], solution={"tour": tour, "route_length": length})
'''

ENERGY_SETUP = '''
def build_problem(public_context):
    devices = [dict(row) for row in public_context["tables"]["devices"]]
    policy = dict(public_context["tables"]["policy"][0])
    return {
        "data": {"devices": devices, "policy": policy},
        "segments": [{
            "name": "dispatch",
            "kind": "real_vector",
            "length": len(devices),
            "lower": [float(row["min_kw"]) for row in devices],
            "upper": [float(row["max_kw"]) for row in devices],
        }],
        "solver_mode": "moea",
        "objective_names": ["operating_cost", "emissions"],
    }
'''

ENERGY_FITNESS = '''
def evaluate(genome, data):
    dispatch = [float(value) for value in genome["dispatch"]]
    devices = data["devices"]
    demand = float(data["policy"]["demand_kw"])
    cost = sum(value * float(row["cost_per_kwh"]) for value, row in zip(dispatch, devices))
    emissions = sum(value * value * float(row["emission_factor"]) for value, row in zip(dispatch, devices))
    shortfall = max(0.0, demand - sum(dispatch))
    violations = {}
    if shortfall > 1e-9:
        violations["demand_shortfall"] = shortfall
    solution = {"dispatch": {row["id"]: value for row, value in zip(devices, dispatch)}}
    return penalty_result(cost + emissions, violations, objectives=[cost, emissions], solution=solution)
'''

INVENTORY_SETUP = '''
def build_problem(public_context):
    periods = [dict(row) for row in public_context["tables"]["periods"]]
    policy = dict(public_context["tables"]["policy"][0])
    return {
        "data": {"periods": periods, "policy": policy},
        "segments": [{
            "name": "orders",
            "kind": "int_vector",
            "length": len(periods),
            "lower": 0,
            "upper": [int(row["max_order"]) for row in periods],
        }],
        "solver_mode": "scalar_ga",
        "objective_names": ["inventory_cost"],
    }
'''

INVENTORY_FITNESS = '''
def evaluate(genome, data):
    orders = [int(value) for value in genome["orders"]]
    inventory = int(data["policy"].get("initial_inventory", 0))
    total = 0.0
    trajectory = []
    for order, row in zip(orders, data["periods"]):
        inventory += order - int(row["demand"])
        total += float(row["order_cost"]) * order
        total += float(row["holding_cost"]) * max(0, inventory)
        total += float(row["shortage_cost"]) * max(0, -inventory)
        trajectory.append(inventory)
    return penalty_result(total, {}, objectives=[total], solution={"orders": orders, "inventory": trajectory})
'''

BUDGET_SETUP = '''
def build_problem(public_context):
    projects = [dict(row) for row in public_context["tables"]["projects"]]
    budget = float(public_context["tables"]["policy"][0]["budget"])
    return {
        "data": {"projects": projects, "budget": budget},
        "segments": [{"name": "selected", "kind": "binary_vector", "length": len(projects)}],
        "solver_mode": "scalar_ga",
        "objective_names": ["negative_public_value"],
    }
'''

BUDGET_FITNESS = '''
def evaluate(genome, data):
    flags = [int(value) for value in genome["selected"]]
    selected = [row for row, flag in zip(data["projects"], flags) if flag]
    cost = sum(float(row["cost"]) for row in selected)
    value = sum(float(row["public_value"]) for row in selected)
    excess = max(0.0, cost - float(data["budget"]))
    violations = {}
    if excess > 1e-9:
        violations["budget_excess"] = excess
    return penalty_result(-value, violations, objectives=[-value], solution={"selected_projects": [row["id"] for row in selected], "total_cost": cost})
'''

CNC_SETUP = '''
def build_problem(public_context):
    tables = public_context["tables"]
    jobs = [dict(row) for row in tables["cnc_orders"]]
    machines = [dict(row) for row in tables["machines"] if bool(row.get("active", True))]
    options = [dict(row) for row in tables["job_machine_options"]]
    job_ids = [row["job_id"] for row in jobs]
    machine_ids = [row["id"] for row in machines]
    return {
        "data": {"jobs": jobs, "machines": machines, "options": options},
        "segments": [
            {"name": "machine_by_job", "kind": "assignment", "demands": job_ids, "resources": machine_ids},
            {"name": "sequence", "kind": "permutation", "values": job_ids},
        ],
        "solver_mode": "moea",
        "objective_names": ["energy", "weighted_tardiness"],
    }
'''

CNC_FITNESS = '''
def evaluate(genome, data):
    assignments = dict(genome["machine_by_job"])
    sequence = list(genome["sequence"])
    jobs = {row["job_id"]: row for row in data["jobs"]}
    machines = {row["id"]: row for row in data["machines"]}
    options = {(row["job_id"], row["machine_id"]): row for row in data["options"]}
    clock = {machine_id: 0.0 for machine_id in machines}
    last_family = {machine_id: None for machine_id in machines}
    energy = 0.0
    tardiness = 0.0
    invalid = 0.0
    schedule = []
    for job_id in sequence:
        job = jobs[job_id]
        machine_id = assignments.get(job_id)
        option = options.get((job_id, machine_id), {})
        if machine_id not in machines or not bool(option.get("eligible", False)) or option.get("processing_h") is None:
            invalid += 1.0
            continue
        machine = machines[machine_id]
        setup = 0.0 if last_family[machine_id] in (None, job["family"]) else float(machine["setup_rate"]) * float(job["setup_level"])
        start = max(clock[machine_id], float(job["release_h"]))
        duration = float(option["processing_h"]) + setup
        end = start + duration
        clock[machine_id] = end
        last_family[machine_id] = job["family"]
        energy += duration * float(machine["power_kw"])
        tardiness += max(0.0, end - float(job["due_h"])) * float(job["priority_w"])
        schedule.append({"job_id": job_id, "machine_id": machine_id, "start": start, "end": end})
    violations = {}
    if invalid > 0:
        violations["invalid_assignments"] = invalid
    return penalty_result(energy + tardiness, violations, objectives=[energy, tardiness], solution={"schedule": schedule})
'''


SLOTS = {
    "healthcare": (HEALTHCARE_SETUP, HEALTHCARE_FITNESS),
    "routing": (ROUTING_SETUP, ROUTING_FITNESS),
    "energy": (ENERGY_SETUP, ENERGY_FITNESS),
    "inventory": (INVENTORY_SETUP, INVENTORY_FITNESS),
    "budget": (BUDGET_SETUP, BUDGET_FITNESS),
    "cnc": (CNC_SETUP, CNC_FITNESS),
}


class SimulatedDeepSeekClient:
    """Return API-shaped responses selected from the actual prompt text."""

    def __init__(self, model: str = "deepseek-v4-flash"):
        self.model = model
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        system = next(
            (str(message.get("content") or "") for message in messages if message.get("role") == "system"),
            "",
        )
        user = next(
            (str(message.get("content") or "") for message in reversed(messages) if message.get("role") == "user"),
            "",
        )
        content = self._response(system, user)
        self.calls.append(
            {
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
                "content": content,
            }
        )
        prompt_tokens = sum(len(str(message.get("content") or "")) // 4 for message in messages)
        completion_tokens = len(content) // 4
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "simulated": True,
            },
        }

    def _response(self, system: str, user: str) -> str:
        lowered = user.lower()
        if "fill setup.py and fitness.py slots" in system:
            case = _case_from_prompt(lowered)
            setup, fitness = SLOTS[case]
            return json.dumps({"setup.py": setup.strip(), "fitness.py": fitness.strip()})
        if "classify dynamic optimization updates" in system.lower():
            return json.dumps(
                {
                    "data_update": True,
                    "patch_setup": False,
                    "patch_fitness": False,
                    "restart_skill": "warm_restart_v1",
                    "reason": "The resource membership change is represented in public tables and the Workbench loops over those rows.",
                    "state_binding_queries": [],
                }
            )
        if "patch public optimization data" in system.lower():
            if "m1" not in lowered:
                raise AssertionError("simulator received an unsupported data update")
            return json.dumps(
                {
                    "operations": [
                        {
                            "op": "update_row",
                            "path": ["tables", "machines"],
                            "match": {"id": "M1"},
                            "values": {"active": False},
                        },
                        {
                            "op": "update_row",
                            "path": ["tables", "job_machine_options"],
                            "match": {"machine_id": "M1"},
                            "values": {"eligible": False},
                        },
                    ],
                    "reason": "M1 is disabled in public resource and eligibility tables.",
                }
            )
        if "semantic channel" in system.lower():
            return json.dumps(
                {
                    "reuse_risk": "medium",
                    "change_mechanisms": ["resource_membership"],
                    "full_vote": False,
                    "evidence_paths": ["tables.machines", "tables.job_machine_options"],
                    "reason": "The encoding remains compositional after one public resource is disabled.",
                }
            )
        if "patch only requested python code slots" in system.lower():
            case = _case_from_prompt(lowered)
            setup, fitness = SLOTS[case]
            return json.dumps({"setup.py": setup.strip(), "fitness.py": fitness.strip()})
        raise AssertionError(f"unsupported simulated DeepSeek prompt: {system[:100]!r}")


def _case_from_prompt(prompt: str) -> str:
    markers = {
        "healthcare": ("healthcare", "health gain", "医疗"),
        "routing": ("cold-chain", "hamiltonian", "delivery route"),
        "energy": ("microgrid", "emissions", "dispatch"),
        "inventory": ("inventory", "shortage", "库存"),
        "budget": ("public budget", "公共预算", "public_value"),
        "cnc": ("cnc", "parallel-machine", "machine_by_job"),
    }
    for case, terms in markers.items():
        if any(term in prompt for term in terms):
            return case
    raise AssertionError(f"simulator cannot identify problem prompt: {prompt[:180]!r}")


class SimulatedClientFactory:
    def __init__(self):
        self.clients: list[SimulatedDeepSeekClient] = []

    def __call__(self, **kwargs: Any) -> SimulatedDeepSeekClient:
        client = SimulatedDeepSeekClient(model=str(kwargs.get("model") or "deepseek-v4-flash"))
        self.clients.append(client)
        return client
