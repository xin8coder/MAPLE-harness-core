from __future__ import annotations

import json

import pytest

from evo2.agents.liveopt_workbench_impl import ScaffoldTrace, compile_scaffold_project
from evo2.core.template_optimizer import EvolutionConfig, FitnessResult, SegmentSpec, run_evolution
from liveopt_dsh.compat import (
    evolution_progress,
    install_provider_compatibility,
    parse_code_slots_compat,
    verify_linear_solution,
)


def test_provider_json_slot_envelope_is_accepted():
    response = json.dumps(
        {
            "setup.py": "def build_problem(public_context):\n    return {}",
            "fitness.py": "def evaluate(genome, data):\n    return {}",
        }
    )
    slots = parse_code_slots_compat(response)
    assert set(slots) == {"setup.py", "fitness.py"}
    assert slots["setup.py"].startswith("def build_problem")


def test_paper_markdown_slot_format_is_unchanged():
    response = """### setup.py
```python
def build_problem(public_context):
    return {}
```
### fitness.py
```python
def evaluate(genome, data):
    return {}
```
"""
    slots = parse_code_slots_compat(response)
    assert set(slots) == {"setup.py", "fitness.py"}


def test_nested_markdown_fences_are_sanitized():
    response = """### setup.py
```python
```python
def build_problem(public_context):
    return {}
```
```
### fitness.py
```python
def evaluate(genome, data):
    return {}
```
"""
    slots = parse_code_slots_compat(response)
    assert slots["setup.py"].startswith("def build_problem")
    assert "```" not in slots["setup.py"]


def test_slot_syntax_feedback_names_slot_line_and_source():
    install_provider_compatibility()
    with pytest.raises(ValueError, match=r"slot build_problem.*line 2.*source='return'"):
        compile_scaffold_project(
            "broken",
            {"tables": {}},
            {
                "setup.py": "def build_problem(public_context):\nreturn",
                "fitness.py": "def evaluate(genome, data):\n    return {}",
            },
            ScaffoldTrace(model="test"),
        )


def test_linear_incumbent_verifier_checks_constraints_and_integrality():
    spec = {
        "variables": [
            {"name": "x", "type": "integer", "lb": 0, "ub": 4},
            {"name": "y", "type": "continuous", "lb": 0, "ub": 5},
        ],
        "constraints": [
            {"coefficients": {"x": 2, "y": 1}, "sense": "<=", "rhs": 7}
        ],
    }
    valid = verify_linear_solution(spec, {"x": 2.0, "y": 3.0})
    assert valid["feasible"] is True
    fractional = verify_linear_solution(spec, {"x": 2.25, "y": 2.0})
    assert fractional["feasible"] is False
    assert fractional["max_integrality_violation"] == 0.25
    violated = verify_linear_solution(spec, {"x": 4.0, "y": 3.0})
    assert violated["feasible"] is False
    assert violated["max_scaled_constraint_violation"] > 0


def test_evolution_progress_reports_each_generation():
    install_provider_compatibility()
    records = []

    def evaluate(genome, _data):
        value = float(genome["x"][0])
        return FitnessResult(scalar=value, feasible=True, solution={"x": value})

    with evolution_progress(records.append, total_generations=3):
        run_evolution(
            [SegmentSpec(name="x", kind="int_vector", length=1, lower=0, upper=5)],
            evaluate,
            config=EvolutionConfig(population_size=6, generations=3, seed=1),
        )

    assert [item["generation"] for item in records] == [0, 1, 2, 3]
    assert records[-1]["percent"] == 100.0
    assert records[-1]["population_size"] == 6
    assert records[-1]["feasible_count"] == 6
