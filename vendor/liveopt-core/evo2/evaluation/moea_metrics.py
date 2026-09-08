from __future__ import annotations

import math
import random
from typing import Any, Iterable

try:
    import numpy as np
    from pymoo.indicators.hv import HV
    from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting

    _PYMOO_NDS = NonDominatedSorting()
except Exception:  # pragma: no cover - optional acceleration
    np = None
    HV = None
    _PYMOO_NDS = None


def objective_vector(item: dict[str, Any], names: list[str]) -> tuple[float, ...]:
    objectives = item.get("objectives", item)
    return tuple(float(objectives[name]) for name in names)


def dominates(a: Iterable[float], b: Iterable[float]) -> bool:
    av = tuple(a)
    bv = tuple(b)
    return all(x <= y for x, y in zip(av, bv)) and any(x < y for x, y in zip(av, bv))


def nondominated(items: list[dict[str, Any]], objective_names: list[str]) -> list[dict[str, Any]]:
    vectors = [objective_vector(item, objective_names) for item in items]
    if _PYMOO_NDS is not None and np is not None and vectors:
        matrix = np.array(vectors, dtype=float)
        front = _PYMOO_NDS.do(matrix, only_non_dominated_front=True)
        out = [items[int(idx)] for idx in front]
    else:
        out = []
        for idx, item in enumerate(items):
            if not any(dominates(vectors[j], vectors[idx]) for j in range(len(items)) if j != idx):
                out.append(item)
    seen = set()
    unique: list[dict[str, Any]] = []
    for item in sorted(out, key=lambda x: (sum(objective_vector(x, objective_names)), objective_vector(x, objective_names))):
        key = tuple(round(v, 9) for v in objective_vector(item, objective_names))
        if key not in seen:
            unique.append(item)
            seen.add(key)
    return unique


DEFAULT_REFERENCE_MARGIN = 0.15
EVALUATION_REFERENCE_MARGIN = 0.5


def reference_point(items: list[dict[str, Any]], objective_names: list[str], margin: float = DEFAULT_REFERENCE_MARGIN) -> dict[str, float]:
    if not items:
        return {name: 1.0 for name in objective_names}
    vectors = [objective_vector(item, objective_names) for item in items]
    ref: dict[str, float] = {}
    for idx, name in enumerate(objective_names):
        values = [v[idx] for v in vectors]
        low, high = min(values), max(values)
        span = max(high - low, abs(high), 1.0)
        ref[name] = round(high + margin * span + 1e-9, 6)
    return ref


def expanded_reference_point(
    items: list[dict[str, Any]],
    objective_names: list[str],
    base_ref: dict[str, float] | None = None,
    min_margin: float = EVALUATION_REFERENCE_MARGIN,
) -> dict[str, float]:
    """Return a fixed, stage-level HV reference point with enough slack for comparison.

    Generated NLDO reference trajectories may carry a tight point based only on the
    held-out reference front. For evaluation, the point should still be fixed for
    the stage, but it needs enough margin to distinguish feasible approximations
    that are worse than the reference front. This helper only expands a supplied
    point; it never shrinks it.
    """
    expanded = reference_point(items, objective_names, margin=min_margin)
    if not base_ref:
        return expanded
    out: dict[str, float] = {}
    for name in objective_names:
        try:
            existing = float(base_ref[name])
        except (KeyError, TypeError, ValueError):
            existing = expanded[name]
        out[name] = round(max(existing, expanded[name]), 6)
    return out


def ideal_point(items: list[dict[str, Any]], objective_names: list[str]) -> dict[str, float]:
    if not items:
        return {name: 0.0 for name in objective_names}
    vectors = [objective_vector(item, objective_names) for item in items]
    return {name: min(v[idx] for v in vectors) for idx, name in enumerate(objective_names)}


def ideal_anchor_point(
    items: list[dict[str, Any]],
    objective_names: list[str],
    margin: float = 0.1,
) -> dict[str, float]:
    """Return a utopia-style anchor derived from the held-out reference front.

    All current NLDO Pareto objectives are minimization objectives. For positive
    objective values this matches the paper-facing rule "best reference value
    times 0.9"; for negative values it moves the anchor further in the improving
    direction instead of accidentally making it worse.
    """
    if not items:
        return {name: 0.0 for name in objective_names}
    ideal = ideal_point(items, objective_names)
    out: dict[str, float] = {}
    for name, value in ideal.items():
        value = float(value)
        out[name] = value - margin * max(abs(value), 1.0)
    return out


def ideal_gap(
    candidate_items: list[dict[str, Any]],
    reference_items: list[dict[str, Any]],
    objective_names: list[str],
    ref: dict[str, float] | None = None,
    anchor: dict[str, float] | None = None,
) -> float:
    """Distance from the candidate front to a fixed ideal anchor.

    This is a smaller-is-better companion to standard larger-is-better HV. The
    anchor and scaling are computed from the reference archive, so candidate
    fronts are compared against the same stage-level objective box.
    """
    if not candidate_items or not reference_items:
        return float("inf")
    ref = ref or reference_point(reference_items, objective_names)
    anchor = anchor or ideal_anchor_point(reference_items, objective_names)
    best = float("inf")
    for item in candidate_items:
        raw = objective_vector(item, objective_names)
        total = 0.0
        for idx, name in enumerate(objective_names):
            denom = max(float(ref[name]) - float(anchor[name]), 1e-9)
            value = max(0.0, (float(raw[idx]) - float(anchor[name])) / denom)
            total += value * value
        best = min(best, math.sqrt(total))
    return round(best, 6)


def normalized_vectors(
    items: list[dict[str, Any]],
    objective_names: list[str],
    ideal: dict[str, float],
    ref: dict[str, float],
) -> list[tuple[float, ...]]:
    vectors = []
    for item in items:
        raw = objective_vector(item, objective_names)
        norm = []
        for idx, name in enumerate(objective_names):
            denom = max(ref[name] - ideal[name], 1e-9)
            norm.append(max(0.0, min(1.5, (raw[idx] - ideal[name]) / denom)))
        vectors.append(tuple(norm))
    return vectors


def approximate_hypervolume(
    items: list[dict[str, Any]],
    objective_names: list[str],
    ref: dict[str, float] | None = None,
    ideal: dict[str, float] | None = None,
    samples: int = 20000,
    seed: int = 0,
) -> float:
    if not items:
        return 0.0
    ref = ref or reference_point(items, objective_names)
    ideal = ideal or ideal_point(items, objective_names)
    vectors = normalized_vectors(items, objective_names, ideal, ref)
    if HV is not None and np is not None and len(objective_names) <= 3:
        matrix = np.array(vectors, dtype=float)
        return round(float(HV(ref_point=np.ones(len(objective_names)))(matrix)), 6)
    if len(objective_names) <= 3:
        return round(_exact_unit_hypervolume(vectors), 6)
    sample_count = samples if samples and samples > 0 else 20000
    rng = random.Random(seed)
    dominated_count = 0
    for _ in range(sample_count):
        point = tuple(rng.random() for _ in objective_names)
        if any(all(v[idx] <= point[idx] for idx in range(len(objective_names))) for v in vectors):
            dominated_count += 1
    return round(dominated_count / sample_count, 6)


def _exact_unit_hypervolume(vectors: list[tuple[float, ...]]) -> float:
    """Exact minimization hypervolume in the normalized unit box.

    The public metric normalizes objectives so that the reference point is
    (1, ..., 1). Points outside that unit box do not dominate any positive
    volume inside it.
    """
    if not vectors:
        return 0.0
    dim = len(vectors[0])
    unit_vectors = [
        tuple(max(0.0, float(value)) for value in vector)
        for vector in vectors
        if len(vector) == dim and all(float(value) < 1.0 for value in vector)
    ]
    if not unit_vectors:
        return 0.0
    return max(0.0, min(1.0, _recursive_unit_hv(_nondominated_vectors(unit_vectors), dim)))


def _recursive_unit_hv(points: list[tuple[float, ...]], dim: int) -> float:
    if not points:
        return 0.0
    if dim == 1:
        return max(0.0, 1.0 - min(point[0] for point in points))
    points = _nondominated_vectors(points)
    cuts = sorted({point[0] for point in points if point[0] < 1.0})
    volume = 0.0
    for idx, cut in enumerate(cuts):
        next_cut = cuts[idx + 1] if idx + 1 < len(cuts) else 1.0
        width = max(0.0, next_cut - cut)
        if width <= 0.0:
            continue
        active = [point[1:] for point in points if point[0] <= cut + 1e-12]
        volume += width * _recursive_unit_hv(active, dim - 1)
    return volume


def _nondominated_vectors(vectors: list[tuple[float, ...]]) -> list[tuple[float, ...]]:
    unique = sorted(set(vectors), key=lambda vector: (sum(vector), vector))
    out: list[tuple[float, ...]] = []
    for idx, vector in enumerate(unique):
        if not any(dominates(other, vector) for j, other in enumerate(unique) if j != idx):
            out.append(vector)
    return out


def igd(
    candidate_items: list[dict[str, Any]],
    reference_items: list[dict[str, Any]],
    objective_names: list[str],
    ref: dict[str, float] | None = None,
    ideal: dict[str, float] | None = None,
) -> float:
    if not candidate_items or not reference_items:
        return float("inf")
    all_items = candidate_items + reference_items
    ref = ref or reference_point(all_items, objective_names)
    ideal = ideal or ideal_point(all_items, objective_names)
    cand_vectors = normalized_vectors(candidate_items, objective_names, ideal, ref)
    ref_vectors = normalized_vectors(reference_items, objective_names, ideal, ref)
    total = 0.0
    for rv in ref_vectors:
        total += min(_euclidean(rv, cv) for cv in cand_vectors)
    return round(total / len(ref_vectors), 6)


def _euclidean(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
