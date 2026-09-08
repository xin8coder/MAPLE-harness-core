from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any

from evo2.agents.llm_client import create_llm_client
from evo2.memory.schemas import to_plain


@dataclass
class PlannerTrace:
    model: str
    planner: str
    prompt_version: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw_content: str = ""
    error: str | None = None
    plan: dict[str, Any] = field(default_factory=dict)


class ReActPlanner:
    """Pure-language planning baseline.

    The model produces an explicit action plan and a direct solution proposal.
    It does not generate code patches.
    """

    prompt_version = "react_planner_v2_minified_json"

    def __init__(self, model: str = "deepseek-v4-pro", client: Any | None = None):
        self.model = model
        self.client = client or create_llm_client(model=model)
        self.last_trace = PlannerTrace(model=model, planner="react", prompt_version=self.prompt_version)

    def plan(self, problem: dict[str, Any], memory: dict[str, Any] | None = None, update_text: str | None = None) -> dict[str, Any]:
        user = {
            "planner": "ReAct",
            "integrity_contract": _integrity_contract(tool_augmented=False),
            "task": "Return one compact JSON object containing a direct solution proposal. Keep all strings short.",
            "problem": _compact_problem(problem),
            "memory": _compact_memory(memory),
            "update_text": update_text or "",
            "required_output_schema": {
                "reasoning_summary": "short string under 80 chars",
                "actions": [{"type": "analyze|replan|repair|verify", "description": "short string"}],
                "solution_plan": {"representation": "direct_solution_json", "content": {}},
                "solver_choice": "direct_llm",
                "confidence": "low|medium|high",
            },
            "example_output": {
                "reasoning_summary": "direct proposal",
                "actions": [{"type": "replan", "description": "assign feasible slots"}],
                "solution_plan": {
                    "representation": "direct_solution_json",
                    "content": {"decisions": {}, "leftover": []},
                },
                "solver_choice": "direct_llm",
                "confidence": "low",
            },
            "output_rules": [
                "Return exactly one minified JSON object.",
                "The first character must be { and the last character must be }.",
                "Do not output code.",
                "Do not output markdown.",
                "Do not output comments or trailing commas.",
                "Do not include line breaks inside string values.",
                "Do not choose lp, ga, moea, or hybrid.",
                "Only produce a direct natural-language-to-solution proposal.",
                "The solution_plan must be a complete solution JSON that can be parsed without extra tool execution.",
                "Use only problem, memory, observations, and update_text provided in this request.",
                "Do not infer from hidden benchmark oracles, hidden deltas, expected labels, file names, or hard-coded benchmark rules.",
            ],
        }
        return self._call(user)

    def _call(self, user: dict[str, Any]) -> dict[str, Any]:
        self.last_trace = PlannerTrace(model=self.model, planner="react", prompt_version=self.prompt_version)
        try:
            response = self.client.chat(
                [
                    {"role": "system", "content": "You are ReAct baseline planner. Return only valid JSON."},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
                ],
                temperature=0.0,
                json_mode=True,
            )
            self.last_trace.usage = response.get("usage", {}) or {}
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            self.last_trace.raw_content = content
            parsed = _extract_json(content)
            self.last_trace.plan = parsed
            return parsed
        except Exception as exc:
            self.last_trace.error = str(exc)
            raise


class ReActToolsPlanner:
    """ReAct baseline with explicit external tool calls.

    This baseline is intentionally tool-augmented but not EVO2-specific: it can
    inspect the current problem, choose verifier/LP/GA tools, and submit a
    solution. It does not receive EVO2 artifact patches, memory-grounded restart
    policies, or population-transfer mechanisms.
    """

    prompt_version = "react_tools_planner_v2_minified_json"

    def __init__(self, model: str = "deepseek-v4-pro", client: Any | None = None):
        self.model = model
        self.client = client or create_llm_client(model=model)
        self.last_trace = PlannerTrace(model=model, planner="react_tools", prompt_version=self.prompt_version)

    def plan(
        self,
        problem: dict[str, Any],
        memory: dict[str, Any] | None = None,
        update_text: str | None = None,
        observations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        user = {
            "planner": "ReAct+Tools",
            "integrity_contract": _integrity_contract(tool_augmented=True),
            "task": "Return one compact JSON object with the next tool action(s). Keep strings short.",
            "problem": _compact_problem(problem),
            "memory": _compact_memory(memory),
            "update_text": update_text or "",
            "observations": observations or [],
            "available_tools": {
                "verifier": {
                    "description": "Check a candidate solution against current constraints.",
                    "arguments": {"solution": "optional direct solution JSON"},
                },
                "linear_program_solver_v1": {
                    "description": "Solve with LP/MILP only when a linear_program_spec is available.",
                    "arguments": {"linear_program_spec": "optional LP/MILP spec override"},
                },
                "ga_full_restart": {
                    "description": "Run a full-restart GA/MOEA-style solver under the shared evaluation budget.",
                    "arguments": {},
                },
                "submit_solution": {
                    "description": "Submit the final solution JSON.",
                    "arguments": {"solution": "complete solution JSON"},
                },
            },
            "required_output_schema": {
                "thought": "short string under 80 chars",
                "actions": [
                    {
                        "tool": "verifier|linear_program_solver_v1|ga_full_restart|submit_solution",
                        "arguments": {},
                        "purpose": "short",
                    }
                ],
                "final_solution": {"decisions": {}, "leftover": []},
                "confidence": "low|medium|high",
            },
            "example_output": {
                "thought": "use optimizer tool",
                "actions": [{"tool": "ga_full_restart", "arguments": {}, "purpose": "solve current stage"}],
                "final_solution": {"decisions": {}, "leftover": []},
                "confidence": "medium",
            },
            "output_rules": [
                "Return exactly one minified JSON object.",
                "The first character must be { and the last character must be }.",
                "Do not output markdown.",
                "Do not output comments or trailing commas.",
                "Do not include line breaks inside string values.",
                "Do not generate code patches.",
                "Do not use EVO2 memory, restart policies, artifact patches, or population transfer.",
                "Use ga_full_restart for complex combinatorial or multi-objective stages when no LP/MILP spec is available.",
                "Use linear_program_solver_v1 only if problem.metadata.linear_program_spec, memory.linear_program_spec, or your action arguments include a valid spec.",
                "Use submit_solution once a tool result or direct proposal should be treated as final.",
                "Use only problem, memory, observations, update_text, and listed tools.",
                "Do not infer from hidden benchmark oracles, hidden deltas, expected labels, file names, or hard-coded benchmark rules.",
            ],
        }
        return self._call(user)

    def _call(self, user: dict[str, Any]) -> dict[str, Any]:
        self.last_trace = PlannerTrace(model=self.model, planner="react_tools", prompt_version=self.prompt_version)
        try:
            response = self.client.chat(
                [
                    {"role": "system", "content": "You are ReAct+Tools baseline planner. Return only valid JSON."},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
                ],
                temperature=0.0,
                json_mode=True,
            )
            self.last_trace.usage = response.get("usage", {}) or {}
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            self.last_trace.raw_content = content
            parsed = _extract_json(content)
            self.last_trace.plan = parsed
            return parsed
        except Exception as exc:
            self.last_trace.error = str(exc)
            raise


class OptimAIPlanner:
    """Optimization-oriented agent baseline following the OptimAI workflow.

    The dynamic version re-formulates the current public problem at each stage,
    generates multiple candidate solver-code plans, executes generated solver
    code against public tools, and uses UCB scheduling to choose which branch to
    debug next. It is intentionally not patch/memory-restart based.
    """

    prompt_version = "optimai_faithful_dynamic_v1"

    def __init__(self, model: str = "deepseek-v4-pro", client: Any | None = None):
        self.model = model
        self.client = client or create_llm_client(model=model)
        self.last_trace = PlannerTrace(model=model, planner="optimai", prompt_version=self.prompt_version)

    def plan(self, problem: dict[str, Any], memory: dict[str, Any] | None = None, update_text: str | None = None) -> dict[str, Any]:
        user = {
            "planner": "OptimAI",
            "integrity_contract": _integrity_contract(tool_augmented=True),
            "task": "Return one compact JSON object selecting LP/MILP or GA. Keep strings short.",
            "problem": _compact_problem(problem),
            "memory": _compact_memory(memory),
            "update_text": update_text or "",
            "required_output_schema": {
                "reasoning_summary": "short",
                "solver_choice": "lp|ga",
                "tool_plan": [
                    {"tool": "linear_program_solver_v1|ga", "purpose": "short"}
                ],
                "solution_plan": {"representation": "solver_plan_json", "content": {}},
                "confidence": "low|medium|high",
            },
            "example_output": {
                "reasoning_summary": "combinatorial stage",
                "solver_choice": "ga",
                "tool_plan": [{"tool": "ga", "purpose": "full restart solve"}],
                "solution_plan": {"representation": "solver_plan_json", "content": {}},
                "confidence": "medium",
            },
            "output_rules": [
                "Return exactly one minified JSON object.",
                "The first character must be { and the last character must be }.",
                "Do not output markdown, comments, or trailing commas.",
                "Do not include line breaks inside string values.",
                "Do not choose direct_llm, moea, or hybrid.",
                "Choose lp only when a linear_program_spec is present in problem or memory.",
                "Choose ga for all other dynamic combinatorial cases.",
                "The solution_plan should describe the solver intent, not a finished assignment.",
                "Use only problem, memory, update_text, and public solver/tool descriptions.",
                "Do not infer from hidden benchmark oracles, hidden deltas, expected labels, file names, or hard-coded benchmark rules.",
            ],
        }
        return self._call(user)

    def run(
        self,
        problem: dict[str, Any],
        memory: dict[str, Any] | None = None,
        update_text: str | None = None,
        tools: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the faithful OptimAI-style dynamic baseline.

        Returns a dict containing at least solution, verification, objective,
        solver_decision, solver_result, and optimai_trace.
        """
        started = time.perf_counter()
        tools = tools or {}
        budget = budget or {}
        num_plans = int(budget.get("optimai_num_plans", 3) or 3)
        debug_rounds = int(budget.get("optimai_debug_rounds", 6) or 6)
        repair_attempts = int(budget.get("optimai_json_repair_attempts", 3) or 3)
        ucb_c = float(budget.get("optimai_ucb_c", 1.4) or 1.4)
        self.last_trace = PlannerTrace(model=self.model, planner="optimai", prompt_version=self.prompt_version)
        calls: list[dict[str, Any]] = []
        branches: list[dict[str, Any]] = []

        formulation = self._call_json(
            "formulator",
            _optimai_formulator_prompt(problem, memory, update_text),
            calls,
            repair_attempts,
        )
        plan_pack = self._call_json(
            "planner",
            _optimai_planner_prompt(problem, memory, update_text, formulation, num_plans),
            calls,
            repair_attempts,
        )
        plans = plan_pack.get("plans") if isinstance(plan_pack, dict) else []
        if not isinstance(plans, list) or not plans:
            raise ValueError("OptimAI planner returned no candidate plans")
        plans = plans[:num_plans]

        for index, plan in enumerate(plans):
            branch = {
                "branch_id": str(plan.get("plan_id") or f"plan_{index}"),
                "plan": plan,
                "prior_score": _clamp_score(plan.get("score", plan.get("decider_prior_score", 5))),
                "attempts": 0,
                "code": "",
                "observations": [],
            }
            code_pack = self._call_json(
                "coder",
                _optimai_coder_prompt(problem, memory, update_text, formulation, plan),
                calls,
                repair_attempts,
            )
            branch["code"] = _code_from_pack(code_pack)
            observation = self._execute_branch(branch, problem, memory, tools)
            if observation.get("success"):
                return self._finish_success(branch, observation, formulation, plans, branches, calls, started)
            branches.append(branch)

        for _round in range(debug_rounds):
            branch = _select_ucb_branch(branches, ucb_c)
            critic_pack = self._call_json(
                "code_critic",
                _optimai_critic_prompt(problem, memory, update_text, formulation, branch),
                calls,
                repair_attempts,
            )
            revised_code = _code_from_pack(critic_pack)
            if revised_code.strip():
                branch["code"] = revised_code
            observation = self._execute_branch(branch, problem, memory, tools)
            if observation.get("success"):
                return self._finish_success(branch, observation, formulation, plans, branches, calls, started)

        self.last_trace.usage = _sum_usage(call.get("usage", {}) for call in calls)
        self.last_trace.raw_content = calls[-1].get("raw_content", "") if calls else ""
        self.last_trace.plan = {
            "status": "failed",
            "formulation": formulation,
            "plans": plans,
            "branches": _branch_trace(branches),
            "llm_calls": calls,
            "latency_seconds": time.perf_counter() - started,
        }
        raise ValueError("OptimAI failed to produce a feasible executable solution")

    def _call(self, user: dict[str, Any]) -> dict[str, Any]:
        self.last_trace = PlannerTrace(model=self.model, planner="optimai", prompt_version=self.prompt_version)
        try:
            response = self.client.chat(
                [
                    {"role": "system", "content": "You are OptimAI baseline planner. Return only valid JSON."},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
                ],
                temperature=0.0,
                json_mode=True,
            )
            self.last_trace.usage = response.get("usage", {}) or {}
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            self.last_trace.raw_content = content
            parsed = _extract_json(content)
            self.last_trace.plan = parsed
            return parsed
        except Exception as exc:
            self.last_trace.error = str(exc)
            raise

    def _call_json(self, role: str, user: dict[str, Any], calls: list[dict[str, Any]], repair_attempts: int) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": f"You are the OptimAI {role} agent. Return one valid compact JSON object only."},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ]
        last_error: Exception | None = None
        for attempt in range(max(1, repair_attempts)):
            response = self.client.chat(messages, temperature=0.0, json_mode=True)
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = response.get("usage", {}) or {}
            calls.append({"role": role, "attempt": attempt + 1, "usage": usage, "raw_content": content})
            messages.append({"role": "assistant", "content": content})
            try:
                return _extract_json(content)
            except Exception as exc:
                last_error = exc
                messages.append(
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "observation_type": "json_parse_error",
                                "role": role,
                                "error": str(exc),
                                "instruction": "Repair the previous response as one strict JSON object. Do not change the intended optimization content.",
                                "invalid_response_preview": content[:4000],
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
        raise last_error or ValueError(f"OptimAI {role} failed")

    def _execute_branch(
        self,
        branch: dict[str, Any],
        problem: dict[str, Any],
        memory: dict[str, Any] | None,
        tools: dict[str, Any],
    ) -> dict[str, Any]:
        branch["attempts"] = int(branch.get("attempts", 0) or 0) + 1
        started = time.perf_counter()
        try:
            raw = _execute_solver_code(branch.get("code", ""), problem, memory or {}, tools)
            solution = _solution_from_solver_output(raw)
            verifier = tools.get("verifier")
            objective_fn = tools.get("objective")
            verification = verifier(solution) if callable(verifier) else {"feasible": True, "violations": {}}
            objective = objective_fn(solution) if callable(objective_fn) else None
            observation = {
                "success": bool(verification.get("feasible")),
                "raw_output": raw,
                "solution": solution,
                "verification": verification,
                "objective": objective,
                "solver_decision": _solver_decision_from_output(raw, branch.get("plan", {})),
                "latency_seconds": time.perf_counter() - started,
            }
        except Exception as exc:
            observation = {
                "success": False,
                "error": repr(exc),
                "latency_seconds": time.perf_counter() - started,
            }
        branch.setdefault("observations", []).append(_compact_observation(observation))
        return observation

    def _finish_success(
        self,
        branch: dict[str, Any],
        observation: dict[str, Any],
        formulation: dict[str, Any],
        plans: list[dict[str, Any]],
        branches: list[dict[str, Any]],
        calls: list[dict[str, Any]],
        started: float,
    ) -> dict[str, Any]:
        all_branches = list(branches)
        if branch not in all_branches:
            all_branches.append(branch)
        usage = _sum_usage(call.get("usage", {}) for call in calls)
        trace = {
            "status": "success",
            "formulation": formulation,
            "plans": plans,
            "selected_branch": branch.get("branch_id"),
            "branches": _branch_trace(all_branches),
            "llm_calls": calls,
            "latency_seconds": time.perf_counter() - started,
            "ucb_debug": True,
        }
        self.last_trace.usage = usage
        self.last_trace.raw_content = calls[-1].get("raw_content", "") if calls else ""
        self.last_trace.plan = trace
        return {
            "solution": observation.get("solution", {}),
            "verification": observation.get("verification", {}),
            "objective": observation.get("objective"),
            "solver_decision": observation.get("solver_decision", {"skill_id": "optimai_generated_code"}),
            "solver_result": {
                "success": True,
                "raw_output": observation.get("raw_output"),
                "branch_id": branch.get("branch_id"),
            },
            "optimai_trace": trace,
        }


def _extract_json(content: str) -> dict:
    content = (content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


def _compact_problem(problem: dict[str, Any]) -> dict[str, Any]:
    problem = to_plain(problem)
    entities = problem.get("entities", {}) if isinstance(problem.get("entities"), dict) else {}
    compact_entities: dict[str, Any] = {}
    for key, value in entities.items():
        if isinstance(value, list):
            compact_entities[key] = value[:20]
        elif isinstance(value, dict):
            compact_entities[key] = dict(list(value.items())[:20])
        else:
            compact_entities[key] = value
    metadata = problem.get("metadata", {}) if isinstance(problem.get("metadata"), dict) else {}
    compact_metadata = {
        k: v
        for k, v in metadata.items()
        if k in {"initial_natural_language_task", "linear_program_spec", "objectives", "reference", "baseline_policy", "public_update_history"}
    }
    if isinstance(compact_metadata.get("public_update_history"), list):
        compact_metadata["public_update_history"] = compact_metadata["public_update_history"][-12:]
    return {
        "task_id": problem.get("task_id", ""),
        "domain": problem.get("domain", ""),
        "entities": compact_entities,
        "variables": problem.get("variables", {}),
        "constraints": (problem.get("constraints") or [])[:30],
        "objective": problem.get("objective", {}),
        "metadata": compact_metadata,
    }


def _integrity_contract(tool_augmented: bool) -> dict[str, Any]:
    return {
        "public_inputs_only": True,
        "hidden_oracle_access": False,
        "hidden_delta_access": False,
        "expected_label_access": False,
        "hard_coded_benchmark_rules": False,
        "tool_augmented": tool_augmented,
    }


def _compact_memory(memory: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(memory, dict):
        return {}
    plain = to_plain(memory)
    public: dict[str, Any] = {}
    for key in [
        "public_update_history",
        "accepted_state_summary",
        "current_public_state_summary",
        "previous_solution_summary",
        "previous_candidate_summary",
        "baseline_transcript_tail",
        "baseline_observations",
        "linear_program_spec",
    ]:
        value = plain.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            public[key] = value[-12:] if key == "public_update_history" else value[-5:]
        elif isinstance(value, dict):
            public[key] = dict(list(value.items())[:40])
        else:
            public[key] = value
    return public


def _optimai_formulator_prompt(problem: dict[str, Any], memory: dict[str, Any] | None, update_text: str | None) -> dict[str, Any]:
    return {
        "role": "formulator",
        "integrity_contract": _integrity_contract(tool_augmented=True),
        "task": "Extract a mathematical optimization formulation from public inputs for the current dynamic stage.",
        "problem": _compact_problem(problem),
        "memory": _compact_memory(memory),
        "update_text": update_text or "",
        "required_output_schema": {
            "problem_type": "LP|MILP|NLP|combinatorial|multi_objective|unknown",
            "decision_variables": [],
            "objectives": [],
            "hard_constraints": [],
            "public_data_dependencies": [],
            "dynamic_context": "short",
            "solver_requirements": [],
        },
        "output_rules": _optimai_common_rules(),
    }


def _optimai_planner_prompt(
    problem: dict[str, Any],
    memory: dict[str, Any] | None,
    update_text: str | None,
    formulation: dict[str, Any],
    num_plans: int,
) -> dict[str, Any]:
    return {
        "role": "planner",
        "integrity_contract": _integrity_contract(tool_augmented=True),
        "task": f"Generate {num_plans} diverse candidate solver-code plans for the current optimization stage.",
        "problem": _compact_problem(problem),
        "memory": _compact_memory(memory),
        "update_text": update_text or "",
        "formulation": formulation,
        "available_tools": _optimai_tool_descriptions(),
        "required_output_schema": {
            "plans": [
                {
                    "plan_id": "p1",
                    "solver_choice": "linear_program_solver_v1|ga_full_restart|artifact_repair",
                    "algorithm": "short",
                    "implementation_notes": [],
                    "score": "1..10 numeric prior",
                }
            ]
        },
        "output_rules": _optimai_common_rules()
        + [
            "Return exactly the requested plans array.",
            "Use linear_program_solver_v1 only when a valid linear_program_spec is visible.",
            "Use ga_full_restart for nonlinear, combinatorial, multi-objective, or dynamic stages without LP spec.",
            "Do not use EVO2 patch memory, restart policy, generated repair skill, or population transfer.",
        ],
    }


def _optimai_coder_prompt(
    problem: dict[str, Any],
    memory: dict[str, Any] | None,
    update_text: str | None,
    formulation: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "role": "coder",
        "integrity_contract": _integrity_contract(tool_augmented=True),
        "task": "Generate Python code for one function solver(problem, memory, tools) implementing the selected OptimAI plan.",
        "problem": _compact_problem(problem),
        "memory": _compact_memory(memory),
        "update_text": update_text or "",
        "formulation": formulation,
        "selected_plan": plan,
        "available_tools": _optimai_tool_descriptions(),
        "required_output_schema": {
            "code_lines": [
                "def solver(problem, memory, tools):",
                "    return {'solver_choice': 'ga_full_restart', 'solution': tools['ga_full_restart']({})['solution']}",
            ],
            "expected_behavior": "short",
        },
        "output_rules": _optimai_common_rules()
        + [
            "Output only JSON with code_lines.",
            "Code must define solver(problem, memory, tools).",
            "The solver may call tools['ga_full_restart'](options), tools['linear_program_solver_v1'](spec), tools['verifier'](solution), and tools['objective'](solution).",
            "The solver must return a dict with solution and solver_choice.",
            "Do not import EVO2 internals or read hidden files.",
        ],
    }


def _optimai_critic_prompt(
    problem: dict[str, Any],
    memory: dict[str, Any] | None,
    update_text: str | None,
    formulation: dict[str, Any],
    branch: dict[str, Any],
) -> dict[str, Any]:
    return {
        "role": "code_critic",
        "integrity_contract": _integrity_contract(tool_augmented=True),
        "task": "Debug the selected solver code using the real execution/verifier observations. Return a corrected full solver function.",
        "problem": _compact_problem(problem),
        "memory": _compact_memory(memory),
        "update_text": update_text or "",
        "formulation": formulation,
        "selected_plan": branch.get("plan", {}),
        "current_code": branch.get("code", ""),
        "observations": branch.get("observations", [])[-5:],
        "available_tools": _optimai_tool_descriptions(),
        "required_output_schema": {
            "diagnosis": "short",
            "code_lines": ["def solver(problem, memory, tools):", "    return {'solution': memory.get('current_solution', {})}"],
        },
        "output_rules": _optimai_common_rules()
        + [
            "Use the actual error/verification feedback; do not hand-wave.",
            "Return full replacement code_lines for solver(problem, memory, tools).",
            "Do not use EVO2 patch/restart/population-transfer mechanisms.",
        ],
    }


def _optimai_common_rules() -> list[str]:
    return [
        "Return exactly one compact JSON object.",
        "No markdown, comments outside strings, code fences, or trailing commas.",
        "Use only public problem, memory summaries, update_text, and listed tools.",
        "Do not infer from hidden benchmark oracles, hidden deltas, expected labels, file names, or hard-coded benchmark rules.",
        "Do not access hidden/reference/evaluation files.",
    ]


def _optimai_tool_descriptions() -> dict[str, Any]:
    return {
        "ga_full_restart": "Run the shared GA/MOEA budget from scratch/current artifact state; returns {'success', 'solution', 'metadata'}.",
        "linear_program_solver_v1": "Solve an explicit numeric LP/MILP spec when available.",
        "verifier": "Check a candidate solution for current public constraints.",
        "objective": "Evaluate a candidate solution with the current public objective.",
    }


def _code_from_pack(pack: dict[str, Any]) -> str:
    lines = pack.get("code_lines") if isinstance(pack, dict) else None
    if isinstance(lines, list) and lines:
        return "\n".join(str(line) for line in lines)
    code = pack.get("code") if isinstance(pack, dict) else ""
    return code if isinstance(code, str) else ""


def _execute_solver_code(code: str, problem: dict[str, Any], memory: dict[str, Any], tools: dict[str, Any]) -> Any:
    if not isinstance(code, str) or "def solver" not in code:
        raise ValueError("OptimAI generated code must define solver(problem, memory, tools)")
    env = {"__builtins__": __builtins__, "math": math}
    exec(compile(code, "<optimai_generated_solver>", "exec"), env, env)
    solver = env.get("solver")
    if not callable(solver):
        raise ValueError("OptimAI generated code did not define callable solver")
    return solver(problem, memory, tools)


def _solution_from_solver_output(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and isinstance(raw.get("solution"), dict):
        return raw["solution"]
    if isinstance(raw, dict):
        return raw
    return {}


def _solver_decision_from_output(raw: Any, plan: dict[str, Any]) -> dict[str, Any]:
    choice = None
    if isinstance(raw, dict):
        choice = raw.get("solver_choice") or raw.get("tool")
    choice = choice or plan.get("solver_choice") or "optimai_generated_code"
    return {"skill_id": str(choice), "reason": str(plan.get("algorithm", "OptimAI generated solver code"))[:200]}


def _compact_observation(observation: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "success": observation.get("success"),
        "error": observation.get("error"),
        "verification": observation.get("verification"),
        "objective": observation.get("objective"),
        "latency_seconds": observation.get("latency_seconds"),
    }
    raw = observation.get("raw_output")
    if isinstance(raw, dict):
        compact["raw_keys"] = sorted(raw)[:20]
        compact["solver_choice"] = raw.get("solver_choice")
    return {k: v for k, v in compact.items() if v is not None}


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except Exception:
        score = 5.0
    return max(1.0, min(10.0, score))


def _select_ucb_branch(branches: list[dict[str, Any]], c: float) -> dict[str, Any]:
    if not branches:
        raise ValueError("No OptimAI branches to debug")
    total = sum(max(1, int(branch.get("attempts", 0) or 0)) for branch in branches)
    best_branch = branches[0]
    best_value = -1e18
    for branch in branches:
        attempts = max(1, int(branch.get("attempts", 0) or 0))
        reward = float(branch.get("prior_score", 5.0)) / 10.0
        last = (branch.get("observations") or [{}])[-1]
        if last.get("success"):
            reward += 1.0
        elif last.get("error"):
            reward -= 0.2
        value = reward + c * math.sqrt(math.log(total + 1.0) / attempts)
        if value > best_value:
            best_value = value
            best_branch = branch
    return best_branch


def _branch_trace(branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "branch_id": branch.get("branch_id"),
            "plan": branch.get("plan"),
            "attempts": branch.get("attempts", 0),
            "prior_score": branch.get("prior_score"),
            "observations": branch.get("observations", []),
            "code_preview": str(branch.get("code", ""))[:1600],
        }
        for branch in branches
    ]


def _sum_usage(usages) -> dict[str, int]:
    total = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "local_cache_hits": 0,
        "local_cache_saved_tokens": 0,
    }
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        for key in ["prompt_tokens", "completion_tokens", "total_tokens", "local_cache_hits", "local_cache_saved_tokens"]:
            total[key] += int(usage.get(key, 0) or 0)
        details = usage.get("prompt_tokens_details", {}) if isinstance(usage.get("prompt_tokens_details"), dict) else {}
        cache_hit = int(usage.get("prompt_cache_hit_tokens", usage.get("cache_hit_tokens", details.get("cached_tokens", 0))) or 0)
        cache_miss = int(usage.get("prompt_cache_miss_tokens", usage.get("cache_miss_tokens", 0)) or 0)
        if not cache_miss and usage.get("prompt_tokens") is not None:
            cache_miss = max(0, int(usage.get("prompt_tokens", 0) or 0) - cache_hit)
        total["prompt_cache_hit_tokens"] += cache_hit
        total["prompt_cache_miss_tokens"] += cache_miss
    return total
