from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Any, Callable

from evo2.evaluation.moea_metrics import (
    approximate_hypervolume,
    expanded_reference_point,
    ideal_anchor_point,
    ideal_gap,
    ideal_point,
    igd,
    nondominated,
    reference_point,
)

try:
    import numpy as np
    from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting

    _PYMOO_NDS = NonDominatedSorting()
except Exception:  # pragma: no cover - optional acceleration
    np = None
    _PYMOO_NDS = None


@dataclass(frozen=True)
class MOEAConfig:
    population_size: int = 256
    generations: int = 250
    seeds: int = 3
    archive_limit: int = 128
    tournament_size: int = 3
    mutation_rate: float = 0.35
    hv_samples: int = 0
    record_history: bool = False
    history_interval: int = 5


GREEN_OBJECTIVES = ["distance", "lateness", "emission"]
CLOUD_OBJECTIVES = ["energy", "load_imbalance"]


@dataclass(frozen=True)
class ScalarGAConfig:
    population_size: int = 256
    generations: int = 300
    seeds: int = 3
    mutation_rate: float = 0.4
    elite_fraction: float = 0.12
    record_history: bool = False
    history_interval: int = 5


def green_vrp_stage_reference(
    state: dict[str, Any],
    previous_solution: dict[str, Any] | None,
    score_solution: Callable[[dict[str, Any], dict[str, Any], dict[str, Any] | None], dict[str, float]],
    config: MOEAConfig,
    seed_offset: int = 0,
) -> dict[str, Any]:
    active_orders = [o["id"] for o in state["orders"] if o.get("active", True)]
    vehicles = [v["id"] for v in state["vehicles"] if v.get("available", True)]

    def make_random(rng: random.Random) -> dict[str, Any]:
        perm = active_orders[:]
        rng.shuffle(perm)
        vehicle_order = vehicles[:]
        rng.shuffle(vehicle_order)
        return {
            "kind": "green_vrp",
            "permutation": perm,
            "vehicle_order": vehicle_order,
            "weights": _random_weights(rng, GREEN_OBJECTIVES),
        }

    decode_context = _green_decode_context(state)

    def decode(genome: dict[str, Any]) -> dict[str, Any]:
        return _decode_green_vrp_with_context(decode_context, genome)

    return _run_moea(
        make_random=make_random,
        decode=decode,
        score=lambda solution: score_solution(state, solution, previous_solution),
        objective_names=GREEN_OBJECTIVES,
        config=config,
        seed_offset=seed_offset,
        seeded_genomes=_green_seeded_genomes(state, previous_solution),
    )


def cloud_stage_reference(
    state: dict[str, Any],
    previous_solution: dict[str, Any] | None,
    score_solution: Callable[[dict[str, Any], dict[str, Any], dict[str, Any] | None], dict[str, float]],
    config: MOEAConfig,
    seed_offset: int = 0,
) -> dict[str, Any]:
    active_jobs = [j["id"] for j in state["jobs"] if j.get("active", True)]
    machines = [m["id"] for m in state["machines"] if m.get("available", True)]

    def make_random(rng: random.Random) -> dict[str, Any]:
        order = active_jobs[:]
        rng.shuffle(order)
        machine_order = machines[:]
        rng.shuffle(machine_order)
        return {
            "kind": "cloud",
            "job_order": order,
            "machine_order": machine_order,
            "weights": _random_weights(rng, CLOUD_OBJECTIVES),
        }

    decode_context = _cloud_decode_context(state)

    def decode(genome: dict[str, Any]) -> dict[str, Any]:
        return _decode_cloud_with_context(decode_context, genome)

    def cloud_score(solution: dict[str, Any]) -> dict[str, float]:
        return _score_cloud_with_context(decode_context, solution, previous_solution)

    return _run_moea(
        make_random=make_random,
        decode=decode,
        score=cloud_score,
        objective_names=CLOUD_OBJECTIVES,
        config=config,
        seed_offset=seed_offset,
        seeded_genomes=_cloud_seeded_genomes(state, previous_solution),
    )


def evaluate_against_reference(
    candidate_archive: list[dict[str, Any]],
    reference_archive: list[dict[str, Any]],
    objective_names: list[str],
    hv_reference_point: dict[str, float] | None = None,
    hv_ideal_point: dict[str, float] | None = None,
    hv_samples: int = 0,
) -> dict[str, float]:
    if not reference_archive:
        return {"hv": 0.0, "hv_ratio": 0.0, "igd": float("inf")}
    hv_ideal_point = hv_ideal_point or ideal_point(reference_archive, objective_names)
    hv_reference_point = expanded_reference_point(
        reference_archive,
        objective_names,
        hv_reference_point,
    )
    gap_anchor = ideal_anchor_point(reference_archive, objective_names)
    ref_hv = approximate_hypervolume(reference_archive, objective_names, hv_reference_point, hv_ideal_point, hv_samples)
    cand_hv = approximate_hypervolume(candidate_archive, objective_names, hv_reference_point, hv_ideal_point, hv_samples)
    return {
        "hv": cand_hv,
        "reference_hv": ref_hv,
        "hv_ratio": round(cand_hv / ref_hv, 6) if ref_hv > 0 else 0.0,
        "igd": igd(candidate_archive, reference_archive, objective_names, hv_reference_point, hv_ideal_point),
        "ideal_gap": ideal_gap(candidate_archive, reference_archive, objective_names, hv_reference_point, gap_anchor),
    }


def inrc_stage_reference(
    state: dict[str, Any],
    previous_roster: dict[str, str] | None,
    score_roster: Callable[[dict[str, Any], dict[str, str], dict[str, str] | None], dict[str, float]],
    construct_roster: Callable[[dict[str, Any], dict[str, str] | None], dict[str, str]],
    config: ScalarGAConfig,
    seed_offset: int = 0,
) -> dict[str, Any]:
    nurses = [n["id"] for n in state["nurses"]]
    days = list(state["days"])
    shifts = list(state["shifts"])
    unavailable = {(u["nurse"], u["day"]) for u in state.get("unavailable", [])}
    seeded = construct_roster(state, None)
    best_solution = copy.deepcopy(seeded)
    best_score = score_roster(state, best_solution, previous_roster)
    evaluations = 0
    history: list[dict[str, Any]] = []
    for seed_idx in range(config.seeds):
        rng = random.Random(seed_offset + seed_idx * 9173)
        population = [copy.deepcopy(seeded)]
        while len(population) < config.population_size:
            population.append(_random_inrc_roster(state, rng, nurses, days, shifts, unavailable, seeded if rng.random() < 0.35 else None))
        scored = [(score_roster(state, sol, previous_roster), sol) for sol in population]
        evaluations += len(scored)
        if config.record_history:
            history.append(_scalar_history_row(seed_idx, 0, scored))
        for generation in range(1, config.generations + 1):
            scored.sort(key=lambda item: item[0]["objective"])
            elite_count = max(2, int(config.elite_fraction * config.population_size))
            next_population = [copy.deepcopy(sol) for _, sol in scored[:elite_count]]
            while len(next_population) < config.population_size:
                p1 = _scalar_tournament(scored, rng)
                p2 = _scalar_tournament(scored, rng)
                child = _crossover_roster(p1, p2, rng)
                if rng.random() < config.mutation_rate:
                    child = _mutate_roster(state, child, rng, nurses, days, shifts, unavailable)
                next_population.append(_repair_inrc_roster(state, child))
            scored = [(score_roster(state, sol, previous_roster), sol) for sol in next_population]
            evaluations += len(scored)
            if config.record_history and (generation % max(1, config.history_interval) == 0 or generation == config.generations):
                history.append(_scalar_history_row(seed_idx, generation, scored))
        scored.sort(key=lambda item: item[0]["objective"])
        if scored[0][0]["objective"] < best_score["objective"]:
            best_score, best_solution = scored[0]
    return {
        "objective": float(best_score["objective"]),
        "score": best_score,
        "solution": best_solution,
        "evaluations": evaluations,
        "solver_config": config.__dict__,
        "history": history,
    }


def _scalar_history_row(seed_idx: int, generation: int, scored: list[tuple[dict[str, float], dict[str, str]]]) -> dict[str, Any]:
    values = sorted(float(item[0]["objective"]) for item in scored)
    best = min(scored, key=lambda item: item[0]["objective"])[0]
    return {
        "seed": seed_idx,
        "generation": generation,
        "best_objective": round(float(best["objective"]), 6),
        "median_objective": round(values[len(values) // 2], 6) if values else 0.0,
        "worst_objective": round(values[-1], 6) if values else 0.0,
        "coverage_shortage": best.get("coverage_shortage", 0),
        "absence_violations": best.get("absence_violations", 0),
        "fairness_penalty": best.get("fairness_penalty", 0),
        "disruption": best.get("disruption", 0),
    }


def _run_moea(
    make_random: Callable[[random.Random], dict[str, Any]],
    decode: Callable[[dict[str, Any]], dict[str, Any]],
    score: Callable[[dict[str, Any]], dict[str, float]],
    objective_names: list[str],
    config: MOEAConfig,
    seed_offset: int,
    seeded_genomes: list[dict[str, Any]],
) -> dict[str, Any]:
    all_candidates: list[dict[str, Any]] = []
    final_population: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for seed_idx in range(config.seeds):
        rng = random.Random(seed_offset + seed_idx * 1009)
        population = [copy.deepcopy(g) for g in seeded_genomes[: config.population_size]]
        while len(population) < config.population_size:
            population.append(make_random(rng))
        scored = _score_population(population, decode, score, objective_names)
        if config.record_history:
            history.append(_history_row(seed_idx, 0, scored, objective_names))
        for generation in range(1, config.generations + 1):
            ranks = _rank_map(scored, objective_names)
            crowding = _crowding_map(scored, objective_names)
            offspring: list[dict[str, Any]] = []
            while len(offspring) < config.population_size:
                p1 = _tournament(scored, ranks, crowding, rng, config.tournament_size)
                p2 = _tournament(scored, ranks, crowding, rng, config.tournament_size)
                child = _crossover(p1["genome"], p2["genome"], rng)
                if rng.random() < config.mutation_rate:
                    child = _mutate(child, rng)
                offspring.append(child)
            combined = scored + _score_population(offspring, decode, score, objective_names)
            scored = _select_next_generation(combined, objective_names, config.population_size)
            if config.record_history and (generation % max(1, config.history_interval) == 0 or generation == config.generations):
                history.append(_history_row(seed_idx, generation, scored, objective_names))
        all_candidates.extend(scored)
        final_population = scored
    archive_candidates = _constraint_feasible_candidates(all_candidates)
    archive = nondominated(archive_candidates, objective_names)
    archive = _limit_archive(archive, objective_names, config.archive_limit)
    ref = reference_point(archive, objective_names)
    ideal = ideal_point(archive, objective_names)
    reference_hv = approximate_hypervolume(archive, objective_names, ref, ideal, config.hv_samples)
    return {
        "archive": archive,
        "archive_size": len(archive),
        "final_population": final_population,
        "objective_names": objective_names,
        "hv_reference_point": ref,
        "hv_ideal_point": ideal,
        "reference_hv": reference_hv,
        "self_igd": igd(archive, archive, objective_names, ref, ideal),
        "evaluations": config.population_size * (config.generations + 1) * config.seeds,
        "final_population_size": len(final_population),
        "history": history,
    }


def _history_row(seed_idx: int, generation: int, scored: list[dict[str, Any]], objective_names: list[str]) -> dict[str, Any]:
    front = nondominated(scored, objective_names)
    best = min(scored, key=lambda item: item["scalar_score"])
    row: dict[str, Any] = {
        "seed": seed_idx,
        "generation": generation,
        "best_scalar": round(float(best["scalar_score"]), 6),
        "archive_size": len(front),
    }
    for name in objective_names:
        row[f"min_{name}"] = round(min(float(item["objectives"][name]) for item in scored), 6)
    return row


def _score_population(
    population: list[dict[str, Any]],
    decode: Callable[[dict[str, Any]], dict[str, Any]],
    score: Callable[[dict[str, Any]], dict[str, float]],
    objective_names: list[str],
) -> list[dict[str, Any]]:
    scored = []
    for genome in population:
        solution = decode(genome)
        objectives = score(solution)
        constraint_penalty = _constraint_penalty(objectives)
        scored.append({
            "genome": genome,
            "solution": solution,
            "objectives": objectives,
            "scalar_score": sum(float(objectives[name]) for name in objective_names) + constraint_penalty,
            "constraint_penalty": constraint_penalty,
        })
    return scored


def _constraint_penalty(objectives: dict[str, Any]) -> float:
    return float(objectives.get("resource_violations", 0.0)) * 1000.0


def _constraint_feasible_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return items
    if "resource_violations" not in items[0].get("objectives", {}):
        return items
    feasible = [
        item
        for item in items
        if float(item["objectives"].get("resource_violations", 0.0)) <= 1e-9
    ]
    return feasible or items


def _random_inrc_roster(
    state: dict[str, Any],
    rng: random.Random,
    nurses: list[str],
    days: list[str],
    shifts: list[str],
    unavailable: set[tuple[str, str]],
    seed_roster: dict[str, str] | None,
) -> dict[str, str]:
    roster = copy.deepcopy(seed_roster) if seed_roster else {}
    for nurse in nurses:
        for day in days:
            key = f"{nurse}|{day}"
            if (nurse, day) in unavailable:
                roster.pop(key, None)
                continue
            if rng.random() < 0.42:
                roster[key] = rng.choice(shifts)
            elif key in roster and rng.random() < 0.20:
                roster.pop(key, None)
    return _repair_inrc_roster(state, roster)


def _repair_inrc_roster(state: dict[str, Any], roster: dict[str, str] | None) -> dict[str, str]:
    roster = copy.deepcopy(roster or {})
    nurses = [n["id"] for n in state["nurses"]]
    unavailable = {(u["nurse"], u["day"]) for u in state.get("unavailable", [])}
    for key in list(roster):
        nurse, day = key.split("|")
        if (nurse, day) in unavailable:
            roster.pop(key)
    load = {nurse: 0 for nurse in nurses}
    nurse_day = set()
    for key in list(roster):
        nurse, day = key.split("|")
        if (nurse, day) in nurse_day:
            roster.pop(key)
            continue
        nurse_day.add((nurse, day))
        load[nurse] = load.get(nurse, 0) + 1
    for day in state["days"]:
        for shift in state["shifts"]:
            need = int(state["coverage"][day][shift])
            assigned = [key.split("|")[0] for key, value in roster.items() if key.endswith("|" + day) and value == shift]
            while len(assigned) < need:
                nurse = _choose_inrc_nurse(state, nurses, load, nurse_day, day, shift, unavailable)
                if not nurse:
                    break
                roster[f"{nurse}|{day}"] = shift
                nurse_day.add((nurse, day))
                load[nurse] = load.get(nurse, 0) + 1
                assigned.append(nurse)
    return roster


def _choose_inrc_nurse(
    state: dict[str, Any],
    nurses: list[str],
    load: dict[str, int],
    nurse_day: set[tuple[str, str]],
    day: str,
    shift: str,
    unavailable: set[tuple[str, str]],
) -> str | None:
    prefer_off = {(p["nurse"], p["day"]) for p in state.get("prefer_off", [])}
    candidates = []
    for nurse in nurses:
        if (nurse, day) in unavailable or (nurse, day) in nurse_day:
            continue
        if load.get(nurse, 0) >= 5:
            continue
        limit = state.get("night_limit", {}).get(nurse)
        if shift == "night" and limit and (not limit.get("day") or limit.get("day") == day):
            continue
        penalty = load.get(nurse, 0) * 10
        if (nurse, day) in prefer_off:
            penalty += 50
        candidates.append((penalty, nurse))
    candidates.sort()
    return candidates[0][1] if candidates else None


def _scalar_tournament(scored: list[tuple[dict[str, float], dict[str, str]]], rng: random.Random, k: int = 3) -> dict[str, str]:
    choices = [scored[rng.randrange(len(scored))] for _ in range(k)]
    return copy.deepcopy(min(choices, key=lambda item: item[0]["objective"])[1])


def _crossover_roster(a: dict[str, str], b: dict[str, str], rng: random.Random) -> dict[str, str]:
    keys = sorted(set(a) | set(b))
    child = {}
    for key in keys:
        if key in a and key in b:
            child[key] = a[key] if rng.random() < 0.5 else b[key]
        elif key in a and rng.random() < 0.5:
            child[key] = a[key]
        elif key in b and rng.random() < 0.5:
            child[key] = b[key]
    return child


def _mutate_roster(
    state: dict[str, Any],
    roster: dict[str, str],
    rng: random.Random,
    nurses: list[str],
    days: list[str],
    shifts: list[str],
    unavailable: set[tuple[str, str]],
) -> dict[str, str]:
    roster = copy.deepcopy(roster)
    for _ in range(max(1, len(roster) // 18)):
        nurse = rng.choice(nurses)
        day = rng.choice(days)
        key = f"{nurse}|{day}"
        if (nurse, day) in unavailable:
            roster.pop(key, None)
        elif rng.random() < 0.25:
            roster.pop(key, None)
        else:
            roster[key] = rng.choice(shifts)
    return roster


def _rank_map(items: list[dict[str, Any]], objective_names: list[str]) -> dict[int, int]:
    if _PYMOO_NDS is not None and np is not None:
        fronts = _pymoo_fronts(items, objective_names)
        ranks: dict[int, int] = {}
        for rank, front in enumerate(fronts):
            for idx in front:
                ranks[int(idx)] = rank
        return ranks
    ranks: dict[int, int] = {}
    for rank, front in enumerate(_fast_nondominated_fronts(items, objective_names)):
        for idx in front:
            ranks[idx] = rank
    return ranks


def _pymoo_fronts(items: list[dict[str, Any]], objective_names: list[str], n_stop_if_ranked: int | None = None):
    matrix = np.array([_selection_vector(item, objective_names) for item in items], dtype=float)
    return _PYMOO_NDS.do(matrix, n_stop_if_ranked=n_stop_if_ranked)


def dominates_vec(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def _selection_vector(item: dict[str, Any], objective_names: list[str]) -> tuple[float, ...]:
    penalty = float(item.get("constraint_penalty", _constraint_penalty(item.get("objectives", {}))))
    return (penalty, *[float(item["objectives"][name]) for name in objective_names])


def _fast_nondominated_fronts(items: list[dict[str, Any]], objective_names: list[str]) -> list[list[int]]:
    """Return NSGA-II nondominated fronts using pairwise domination counts."""
    size = len(items)
    if size == 0:
        return []
    vectors = [_selection_vector(item, objective_names) for item in items]
    dominates: list[list[int]] = [[] for _ in range(size)]
    domination_count = [0] * size
    first_front: list[int] = []

    for i in range(size):
        vi = vectors[i]
        for j in range(i + 1, size):
            vj = vectors[j]
            if dominates_vec(vi, vj):
                dominates[i].append(j)
                domination_count[j] += 1
            elif dominates_vec(vj, vi):
                dominates[j].append(i)
                domination_count[i] += 1
        if domination_count[i] == 0:
            first_front.append(i)

    fronts: list[list[int]] = []
    current = first_front
    while current:
        fronts.append(current)
        next_front: list[int] = []
        for idx in current:
            for dominated_idx in dominates[idx]:
                domination_count[dominated_idx] -= 1
                if domination_count[dominated_idx] == 0:
                    next_front.append(dominated_idx)
        current = next_front
    return fronts


def _crowding_map(items: list[dict[str, Any]], objective_names: list[str]) -> dict[int, float]:
    crowding = {idx: 0.0 for idx in range(len(items))}
    for name in objective_names:
        order = sorted(range(len(items)), key=lambda idx: float(items[idx]["objectives"][name]))
        if not order:
            continue
        crowding[order[0]] = crowding[order[-1]] = float("inf")
        low = float(items[order[0]]["objectives"][name])
        high = float(items[order[-1]]["objectives"][name])
        denom = max(high - low, 1e-9)
        for pos in range(1, len(order) - 1):
            prev_v = float(items[order[pos - 1]]["objectives"][name])
            next_v = float(items[order[pos + 1]]["objectives"][name])
            crowding[order[pos]] += (next_v - prev_v) / denom
    return crowding


def _tournament(
    scored: list[dict[str, Any]],
    ranks: dict[int, int],
    crowding: dict[int, float],
    rng: random.Random,
    tournament_size: int,
) -> dict[str, Any]:
    choices = [rng.randrange(len(scored)) for _ in range(tournament_size)]
    best = min(choices, key=lambda idx: (ranks[idx], -crowding[idx], scored[idx]["scalar_score"]))
    return scored[best]


def _select_next_generation(items: list[dict[str, Any]], objective_names: list[str], size: int) -> list[dict[str, Any]]:
    if _PYMOO_NDS is not None and np is not None:
        selected: list[dict[str, Any]] = []
        fronts = _pymoo_fronts(items, objective_names, n_stop_if_ranked=size)
        for front in fronts:
            front_items = [items[int(idx)] for idx in front]
            if len(selected) + len(front_items) <= size:
                selected.extend(front_items)
            else:
                local_crowding = _crowding_map(front_items, objective_names)
                order = sorted(range(len(front_items)), key=lambda idx: (-local_crowding[idx], front_items[idx]["scalar_score"]))
                selected.extend(front_items[idx] for idx in order[: size - len(selected)])
                break
        return selected[:size]
    selected: list[dict[str, Any]] = []
    for front_indices in _fast_nondominated_fronts(items, objective_names):
        if len(selected) >= size:
            break
        front = [items[idx] for idx in front_indices]
        if len(selected) + len(front) <= size:
            selected.extend(front)
        else:
            local_crowding = _crowding_map(front, objective_names)
            front_sorted = sorted(range(len(front)), key=lambda idx: (-local_crowding[idx], front[idx]["scalar_score"]))
            selected.extend(front[idx] for idx in front_sorted[: size - len(selected)])
            break
    return selected[:size]


def _limit_archive(items: list[dict[str, Any]], objective_names: list[str], limit: int) -> list[dict[str, Any]]:
    if len(items) <= limit:
        return _strip_genomes(items)
    crowding = _crowding_map(items, objective_names)
    order = sorted(range(len(items)), key=lambda idx: (-crowding[idx], items[idx]["scalar_score"]))
    return _strip_genomes([items[idx] for idx in order[:limit]])


def _strip_genomes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "profile": item.get("profile", "offline_moea"),
            "solution": item["solution"],
            "objectives": item["objectives"],
            "scalar_score": round(float(item.get("scalar_score", sum(item["objectives"].values()))), 6),
        }
        for item in items
    ]


def _crossover(a: dict[str, Any], b: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    if a.get("kind") == "cloud_fixed_assignments" and b.get("kind") == "cloud_fixed_assignments":
        return copy.deepcopy(a)
    if a.get("kind") == "cloud_fixed_assignments":
        return copy.deepcopy(b)
    if b.get("kind") == "cloud_fixed_assignments":
        return copy.deepcopy(a)
    child = copy.deepcopy(a)
    if a.get("kind") == "green_vrp":
        child["permutation"] = _ordered_crossover(a["permutation"], b["permutation"], rng)
        child["vehicle_order"] = _ordered_crossover(a["vehicle_order"], b["vehicle_order"], rng)
    else:
        child["job_order"] = _ordered_crossover(a["job_order"], b["job_order"], rng)
        child["machine_order"] = _ordered_crossover(a["machine_order"], b["machine_order"], rng)
    child["weights"] = {
        key: (float(a["weights"].get(key, 1.0)) + float(b["weights"].get(key, 1.0))) / 2.0
        for key in sorted(set(a.get("weights", {})) | set(b.get("weights", {})))
    }
    return child


def _ordered_crossover(a: list[str], b: list[str], rng: random.Random) -> list[str]:
    if len(a) <= 2:
        return a[:]
    lo = rng.randrange(len(a))
    hi = rng.randrange(lo, len(a))
    segment = a[lo : hi + 1]
    rest = [x for x in b if x not in segment]
    return rest[:lo] + segment + rest[lo:]


def _mutate(genome: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    genome = copy.deepcopy(genome)
    if genome.get("kind") == "cloud_fixed_assignments":
        return genome
    keys = ["permutation", "vehicle_order"] if genome.get("kind") == "green_vrp" else ["job_order", "machine_order"]
    for key in keys:
        values = genome.get(key, [])
        if len(values) >= 2 and rng.random() < 0.75:
            i, j = rng.sample(range(len(values)), 2)
            values[i], values[j] = values[j], values[i]
    for key in sorted(genome.get("weights", {})):
        if rng.random() < 0.5:
            genome["weights"][key] = max(0.05, min(5.0, float(genome["weights"][key]) * rng.uniform(0.65, 1.55)))
    return genome


def _random_weights(rng: random.Random, names: list[str]) -> dict[str, float]:
    return {name: round(10 ** rng.uniform(-0.6, 0.6), 4) for name in names}


def _green_seeded_genomes(state: dict[str, Any], previous_solution: dict[str, Any] | None) -> list[dict[str, Any]]:
    orders = [o for o in state["orders"] if o.get("active", True)]
    vehicles = [v for v in state["vehicles"] if v.get("available", True)]
    orderings = [
        sorted(orders, key=lambda o: (o["due"], -o["priority"])),
        sorted(orders, key=lambda o: (-o["priority"], o["due"])),
        sorted(orders, key=lambda o: (o["demand"], o["due"])),
        sorted(orders, key=lambda o: (_distance(state["depot"], o), o["due"])),
    ]
    vehicle_orders = [
        sorted(vehicles, key=lambda v: (-v["capacity"], v["emission_rate"])),
        sorted(vehicles, key=lambda v: (v["emission_rate"], -v["capacity"])),
    ]
    profiles = [
        {"distance": 2.0, "lateness": 0.8, "emission": 0.8, "priority_penalty": 1.0},
        {"distance": 0.6, "lateness": 2.5, "emission": 0.7, "priority_penalty": 2.0},
        {"distance": 0.8, "lateness": 0.8, "emission": 2.5, "priority_penalty": 1.0},
        {"distance": 1.0, "lateness": 1.0, "emission": 1.0, "priority_penalty": 1.0},
    ]
    out = []
    for ordering in orderings:
        for vehicle_order in vehicle_orders:
            for weights in profiles:
                out.append({
                    "kind": "green_vrp",
                    "permutation": [o["id"] for o in ordering],
                    "vehicle_order": [v["id"] for v in vehicle_order],
                    "weights": copy.deepcopy(weights),
                })
    return out


def _cloud_seeded_genomes(state: dict[str, Any], previous_solution: dict[str, Any] | None) -> list[dict[str, Any]]:
    jobs = [j for j in state["jobs"] if j.get("active", True)]
    machines = [m for m in state["machines"] if m.get("available", True)]
    orderings = [
        sorted(jobs, key=lambda j: (j["deadline"], -j["priority"])),
        sorted(jobs, key=lambda j: (-j["priority"], j["deadline"])),
        sorted(jobs, key=lambda j: (-j["cpu"] - j["mem"] / 4, j["deadline"])),
        sorted(jobs, key=lambda j: (-j["latency_sensitivity"], j["deadline"], -j["priority"])),
    ]
    machine_orders = [
        sorted(machines, key=lambda m: (-m["cpu"], -m["mem"])),
        sorted(machines, key=lambda m: (m["energy_idle"] + m["energy_per_cpu"] * m["cpu"], m["id"])),
        sorted(machines, key=lambda m: (not m.get("gpu", False), m["energy_per_cpu"], m["id"])),
    ]
    profiles = [
        {"sla_violations": 3.0, "latency": 1.5, "energy": 0.5, "load_imbalance": 0.7},
        {"sla_violations": 1.0, "latency": 0.7, "energy": 2.6, "load_imbalance": 0.8},
        {"sla_violations": 1.5, "latency": 2.4, "energy": 0.6, "load_imbalance": 0.6},
        {"sla_violations": 1.4, "latency": 0.9, "energy": 0.8, "load_imbalance": 2.6},
    ]
    out = []
    for ordering in orderings:
        for machine_order in machine_orders:
            for weights in profiles:
                out.append({
                    "kind": "cloud",
                    "job_order": [j["id"] for j in ordering],
                    "machine_order": [m["id"] for m in machine_order],
                    "weights": copy.deepcopy(weights),
                })
    return out


def _green_decode_context(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_map": {o["id"]: o for o in state["orders"] if o.get("active", True)},
        "vehicle_map": {v["id"]: v for v in state["vehicles"] if v.get("available", True)},
        "depot": state["depot"],
        "traffic": _traffic_factor_map(state),
        "carbon_multiplier": float(state.get("carbon_multiplier", 1.0)),
    }


def _decode_green_vrp(state: dict[str, Any], genome: dict[str, Any], previous_solution: dict[str, Any] | None) -> dict[str, Any]:
    return _decode_green_vrp_with_context(_green_decode_context(state), genome)


def _decode_green_vrp_with_context(context: dict[str, Any], genome: dict[str, Any]) -> dict[str, Any]:
    order_map = context["order_map"]
    vehicle_map = context["vehicle_map"]
    depot = context["depot"]
    traffic = context["traffic"]
    carbon_multiplier = context["carbon_multiplier"]
    routes = {vid: [] for vid in genome.get("vehicle_order", []) if vid in vehicle_map}
    for vid in vehicle_map:
        routes.setdefault(vid, [])
    loads = {vid: 0.0 for vid in routes}
    route_time = {vid: 0.0 for vid in routes}
    route_loc = {vid: depot for vid in routes}
    weights = genome["weights"]
    for oid in genome.get("permutation", []):
        if oid not in order_map:
            continue
        order = order_map[oid]
        best_vid = None
        best_cost = float("inf")
        for vid in routes:
            vehicle = vehicle_map[vid]
            if loads[vid] + order["demand"] > vehicle["capacity"]:
                continue
            leg = _distance(route_loc[vid], order)
            arrival = route_time[vid] + leg * traffic.get(order["id"], 1.0)
            lateness = max(0.0, arrival - order["due"])
            cost = (
                leg * weights.get("distance", 1.0)
                + leg * vehicle["emission_rate"] * carbon_multiplier * weights.get("emission", 1.0)
                + lateness * weights.get("lateness", 1.0)
                - order["priority"] * weights.get("priority_penalty", 1.0)
            )
            if cost < best_cost:
                best_cost = cost
                best_vid = vid
        if best_vid:
            routes[best_vid].append(oid)
            loads[best_vid] += order["demand"]
            leg = _distance(route_loc[best_vid], order)
            arrival = route_time[best_vid] + leg * traffic.get(order["id"], 1.0)
            route_time[best_vid] = max(arrival, float(order["ready"])) + float(order["service"])
            route_loc[best_vid] = order
    return {"routes": [{"vehicle": vid, "orders": orders} for vid, orders in routes.items() if orders]}


def _green_insertion_cost(state: dict[str, Any], route: list[str], order: dict[str, Any], vehicle: dict[str, Any], weights: dict[str, float]) -> float:
    order_map = {o["id"]: o for o in state["orders"]}
    loc = state["depot"] if not route else order_map[route[-1]]
    leg = _distance(loc, order)
    lateness = max(0.0, _arrival_time(state, route, order) - order["due"])
    return (
        leg * weights.get("distance", 1.0)
        + leg * vehicle["emission_rate"] * state.get("carbon_multiplier", 1.0) * weights.get("emission", 1.0)
        + lateness * weights.get("lateness", 1.0)
        - order["priority"] * weights.get("priority_penalty", 1.0)
    )


def _cloud_decode_context(state: dict[str, Any]) -> dict[str, Any]:
    machines = list(state["machines"])
    available = [m for m in machines if m.get("available", True)]
    return {
        "job_map": {j["id"]: j for j in state["jobs"] if j.get("active", True)},
        "machine_map": {m["id"]: m for m in machines},
        "available_machine_map": {m["id"]: m for m in available},
        "machines": machines,
        "available_machines": available,
        "available_machine_ids": {m["id"] for m in available},
        "energy_price": float(state.get("energy_price", 1.0)),
        "carbon_intensity": float(state.get("carbon_intensity", 1.0)),
    }


def _decode_cloud(state: dict[str, Any], genome: dict[str, Any], previous_solution: dict[str, Any] | None) -> dict[str, Any]:
    return _decode_cloud_with_context(_cloud_decode_context(state), genome)


def _decode_cloud_with_context(context: dict[str, Any], genome: dict[str, Any]) -> dict[str, Any]:
    job_map = context["job_map"]
    machine_map = context["available_machine_map"]
    if genome.get("kind") == "cloud_fixed_assignments":
        assignments = {
            jid: mid
            for jid, mid in genome.get("assignments", {}).items()
            if jid in job_map and mid in machine_map
        }
        return {"assignments": assignments}
    remaining = {mid: {"cpu": machine_map[mid]["cpu"], "mem": machine_map[mid]["mem"]} for mid in machine_map}
    assignments: dict[str, str] = {}
    machine_order = [mid for mid in genome.get("machine_order", []) if mid in machine_map] + [mid for mid in machine_map if mid not in genome.get("machine_order", [])]
    for jid in genome.get("job_order", []):
        if jid not in job_map:
            continue
        job = job_map[jid]
        best_mid = None
        best_cost = float("inf")
        for mid in machine_order:
            machine = machine_map[mid]
            if job.get("gpu_required") and not machine.get("gpu", False):
                continue
            rem = remaining[mid]
            if rem["cpu"] < job["cpu"] or rem["mem"] < job["mem"]:
                continue
            cost = _cloud_assignment_cost(context, job, machine, rem, genome["weights"])
            if cost < best_cost:
                best_cost = cost
                best_mid = mid
        if best_mid:
            assignments[jid] = best_mid
            remaining[best_mid]["cpu"] -= job["cpu"]
            remaining[best_mid]["mem"] -= job["mem"]
    return {"assignments": assignments}


def _score_cloud_with_context(
    context: dict[str, Any],
    solution: dict[str, Any],
    previous_solution: dict[str, Any] | None,
) -> dict[str, float]:
    job_map = context["job_map"]
    machine_map = context["machine_map"]
    machines = context["machines"]
    used_cpu = {m["id"]: 0.0 for m in machines}
    used_mem = {m["id"]: 0.0 for m in machines}
    sla = 0.0
    latency = 0.0
    energy = 0.0
    infeasible = 0.0
    assignments = solution.get("assignments", {}) if isinstance(solution.get("assignments"), dict) else {}
    for job_id, machine_id in assignments.items():
        if job_id not in job_map or machine_id not in machine_map:
            infeasible += 1.0
            continue
        job = job_map[job_id]
        machine = machine_map[machine_id]
        if not machine.get("available", True) or (job.get("gpu_required") and not machine.get("gpu", False)):
            infeasible += 1.0
        used_cpu[machine_id] += job["cpu"]
        used_mem[machine_id] += job["mem"]
        util = used_cpu[machine_id] / max(machine["cpu"], 1)
        job_latency = _job_latency(job, machine, util)
        latency += job_latency * job["latency_sensitivity"]
        sla += max(0.0, job_latency - job["deadline"]) * job["priority"]
        energy += (
            machine["energy_idle"] + machine["energy_per_cpu"] * used_cpu[machine_id]
        ) * context["energy_price"] * context["carbon_intensity"]
    for machine in machines:
        if used_cpu[machine["id"]] > machine["cpu"] or used_mem[machine["id"]] > machine["mem"]:
            infeasible += 5.0
    missed = set(job_map) - set(assignments)
    sla += sum(job_map[job_id]["priority"] * 80.0 for job_id in missed)
    latency += len(missed) * 120.0
    migration = _cloud_migration_disruption(context, assignments, previous_solution)
    balance = _cloud_load_imbalance(context, used_cpu)
    return {
        "resource_violations": round(infeasible + float(len(missed)), 3),
        "sla_violations": round(sla + infeasible * 100.0, 3),
        "latency": round(latency, 3),
        "energy": round(energy, 3),
        "migration_disruption": round(migration, 3),
        "load_imbalance": round(balance, 3),
    }


def _cloud_migration_disruption(context: dict[str, Any], assignments: dict[str, str], previous_solution: dict[str, Any] | None) -> float:
    if not previous_solution:
        return 0.0
    previous = previous_solution.get("assignments", {})
    if not isinstance(previous, dict):
        return 0.0
    keys = set(assignments) & set(previous)
    available = context["available_machine_ids"]
    return float(sum(1 for key in keys if previous.get(key) in available and assignments.get(key) != previous.get(key)))


def _cloud_load_imbalance(context: dict[str, Any], used_cpu: dict[str, float]) -> float:
    available = context["available_machines"]
    if not available:
        return 0.0
    utils = [used_cpu[m["id"]] / max(m["cpu"], 1) for m in available]
    avg = sum(utils) / len(utils)
    return sum(abs(u - avg) for u in utils) * 100.0


def _cloud_assignment_cost(context: dict[str, Any], job: dict[str, Any], machine: dict[str, Any], rem: dict[str, float], weights: dict[str, float]) -> float:
    cpu_after = rem["cpu"] - job["cpu"]
    mem_after = rem["mem"] - job["mem"]
    utilization = 1.0 - cpu_after / max(machine["cpu"], 1)
    latency = _job_latency(job, machine, utilization)
    sla = max(0.0, latency - job["deadline"]) * job["priority"]
    energy = (machine["energy_idle"] + machine["energy_per_cpu"] * job["cpu"]) * context["energy_price"] * context["carbon_intensity"]
    balance = abs(cpu_after / max(machine["cpu"], 1) - mem_after / max(machine["mem"], 1)) * 10.0
    return (
        sla * weights.get("sla_violations", 1.0)
        + latency * weights.get("latency", 1.0)
        + energy * weights.get("energy", 1.0)
        + balance * weights.get("load_imbalance", 1.0)
    )


def _previous_vehicle_map(solution: dict[str, Any] | None) -> dict[str, str]:
    if not solution:
        return {}
    out = {}
    for route in solution.get("routes", []):
        for oid in route.get("orders", []):
            out[oid] = route["vehicle"]
    return out


def _arrival_time(state: dict[str, Any], route: list[str], order: dict[str, Any]) -> float:
    order_map = {o["id"]: o for o in state["orders"]}
    time = 0.0
    loc = state["depot"]
    for oid in route:
        current = order_map[oid]
        time += _distance(loc, current) * _traffic_factor(state, oid)
        time = max(time, current["ready"]) + current["service"]
        loc = current
    return time + _distance(loc, order) * _traffic_factor(state, order["id"])


def _traffic_factor(state: dict[str, Any], order_id: str) -> float:
    factor = 1.0
    for zone in state.get("traffic_zones", []):
        if zone["order"] == order_id:
            factor *= float(zone["factor"])
    return factor


def _traffic_factor_map(state: dict[str, Any]) -> dict[str, float]:
    factors: dict[str, float] = {}
    for zone in state.get("traffic_zones", []):
        order = str(zone.get("order"))
        factors[order] = factors.get(order, 1.0) * float(zone.get("factor", 1.0))
    return factors


def _distance(a: dict[str, float], b: dict[str, float]) -> float:
    dx = float(a["x"]) - float(b["x"])
    dy = float(a["y"]) - float(b["y"])
    return (dx * dx + dy * dy) ** 0.5


def _job_latency(job: dict[str, Any], machine: dict[str, Any], utilization: float) -> float:
    base = job["cpu"] * 3.0 + job["mem"] * 0.45
    gpu_penalty = 0.65 if job.get("gpu_required") and machine.get("gpu", False) else 1.0
    congestion = 1.0 + max(0.0, utilization - 0.7) * 1.8
    return base * congestion * gpu_penalty
