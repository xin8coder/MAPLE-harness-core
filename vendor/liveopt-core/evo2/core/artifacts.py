from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


COMPOSITE_ENCODINGS = {"composite", "typed_composite", "typed_compositional"}
PERMUTATION_ENCODINGS = {"permutation", "order", "order_encoding", "order_permutation", "permutation_order", "sequence"}


@dataclass
class OptimizationContract:
    """Domain-neutral contract inferred from natural language."""

    task_id: str
    domain_label: str = "unknown"
    problem_summary: str = ""
    solution_schema: dict[str, Any] = field(default_factory=dict)
    objective: dict[str, Any] = field(default_factory=dict)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    memory_keys: list[str] = field(default_factory=list)
    update_semantics: list[dict[str, Any]] = field(default_factory=list)
    public_data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GeneratedArtifact:
    """Executable artifact produced by the agent, not manually coded per benchmark."""

    artifact_id: str
    artifact_type: str
    code: str
    function_name: str
    prompt_version: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


STANDARD_MUTATION_OPERATOR_CODE = """
def mutation_operator(genome, contract, memory):
    def _unit(seed, index, salt):
        raw = (abs(int(seed)) * 1103515245 + abs(int(index)) * 12345 + (salt + 1) * 2654435761) % 1000003
        return raw / 1000002.0

    spec = encoding_spec(contract, memory)
    if not isinstance(spec, dict):
        spec = {}
    encoding = str(spec.get('encoding', spec.get('type', ''))).lower()
    metadata = spec.get('metadata', {})
    skill_id = str(metadata.get('operator_skill_id', '')) if isinstance(metadata, dict) else ''
    skill_id = skill_id.lower()
    mem = memory if isinstance(memory, dict) else {}
    try:
        mutation_index = int(mem.get('mutation_index', mem.get('operator_index', 0)) or 0)
    except Exception:
        mutation_index = 0
    try:
        operator_seed = int(mem.get('operator_seed', mem.get('mutation_seed', mutation_index)) or 0)
    except Exception:
        operator_seed = mutation_index

    def _segment_name(segment, idx):
        if isinstance(segment, dict):
            return str(segment.get('name') or segment.get('role') or ('segment_' + str(idx)))
        return 'segment_' + str(idx)

    def _segment_encoding(segment):
        return str(segment.get('encoding', segment.get('type', 'real_vector')) if isinstance(segment, dict) else 'real_vector').lower()

    def _segment_values(segment, raw_genome):
        values = []
        if isinstance(segment, dict) and isinstance(segment.get('values'), list):
            for item in segment.get('values'):
                if item not in values:
                    values.append(item)
        if not values and isinstance(raw_genome, list):
            for item in raw_genome:
                if item not in values:
                    values.append(item)
        if not values:
            try:
                values = list(range(int(segment.get('dimension', segment.get('dim', 0)) or 0))) if isinstance(segment, dict) else []
            except Exception:
                values = []
        return values

    def _normalize_order(raw_genome, segment):
        values = _segment_values(segment, raw_genome)
        raw = list(raw_genome) if isinstance(raw_genome, list) else []
        out = []
        for item in raw:
            if item in values and item not in out:
                out.append(item)
        for item in values:
            if item not in out:
                out.append(item)
        return out

    def _bounds(segment, dimension):
        lower = segment.get('lower_bounds', segment.get('lb', segment.get('lower', 0))) if isinstance(segment, dict) else 0
        upper = segment.get('upper_bounds', segment.get('ub', segment.get('upper', 1))) if isinstance(segment, dict) else 1
        if not isinstance(lower, list):
            lower = [lower] * max(1, dimension)
        if not isinstance(upper, list):
            upper = [upper] * max(1, dimension)
        return lower, upper

    def _normalize_vector(raw_genome, segment):
        raw = list(raw_genome) if isinstance(raw_genome, list) else []
        try:
            dimension = int(segment.get('dimension', segment.get('dim', len(raw))) or len(raw)) if isinstance(segment, dict) else len(raw)
        except Exception:
            dimension = len(raw)
        lower, _upper = _bounds(segment if isinstance(segment, dict) else {}, dimension)
        out = []
        for i in range(dimension):
            if i < len(raw):
                out.append(raw[i])
            elif i < len(lower):
                out.append(lower[i])
            else:
                out.append(0)
        return out

    def _mutate_segment(raw_genome, segment, seg_idx):
        seg_encoding = _segment_encoding(segment)
        seg_skill = str(segment.get('operator_skill_id', segment.get('skill_id', '')) if isinstance(segment, dict) else '').lower()
        is_seg_order = seg_encoding in {'order_permutation', 'permutation', 'order', 'order_encoding', 'permutation_order', 'sequence'} or 'permutation' in seg_skill or 'order' in seg_skill
        local_seed = operator_seed + (seg_idx + 1) * 104729
        local_index = mutation_index + seg_idx * 7919
        if is_seg_order:
            out = _normalize_order(raw_genome, segment)
            if len(out) > 2:
                i = int(_unit(local_seed, local_index, 313) * len(out))
                j = int(_unit(local_seed + 17, local_index, 719) * len(out))
                if i == j:
                    j = (i + max(1, len(out) // 2)) % len(out)
                lo, hi = sorted([i, j])
                op = int(_unit(local_seed + 31, local_index, 991) * 3)
                if op == 0:
                    out[i], out[j] = out[j], out[i]
                elif op == 1:
                    out[lo:hi + 1] = list(reversed(out[lo:hi + 1]))
                else:
                    item = out.pop(i)
                    out.insert(j if j < len(out) else len(out), item)
            elif len(out) > 1:
                out[0], out[1] = out[1], out[0]
            return out
        out = _normalize_vector(raw_genome, segment)
        if not out:
            return out
        lower, upper = _bounds(segment if isinstance(segment, dict) else {}, len(out))
        pos = (local_index + local_seed) % len(out)
        if seg_encoding == 'binary' or 'binary' in seg_skill:
            count = max(1, min(len(out), 1 + len(out) // 20))
            for step_idx in range(count):
                p = (pos + step_idx * 7) % len(out)
                try:
                    out[p] = 0 if int(round(float(out[p]))) else 1
                except Exception:
                    out[p] = 1
            return out
        if seg_encoding in {'int_vector', 'integer_vector'} or 'int' in seg_skill:
            count = max(1, min(len(out), 1 + len(out) // 12))
            for step_idx in range(count):
                p = (pos + step_idx * 7) % len(out)
                lo = int(lower[p]) if p < len(lower) else 0
                hi = int(upper[p]) if p < len(upper) else max(lo + 1, 1)
                if hi > lo:
                    try:
                        current = int(round(float(out[p])))
                    except Exception:
                        current = lo
                    span = hi - lo + 1
                    candidate = lo + int(_unit(local_seed, local_index, p + step_idx) * span)
                    if candidate > hi:
                        candidate = hi
                    if span > 1 and candidate == current:
                        candidate = lo + ((candidate - lo + 1) % span)
                    out[p] = candidate
                else:
                    out[p] = lo
            return out
        count = max(1, min(len(out), 1 + len(out) // 8))
        eta_m = 20.0
        for step_idx in range(count):
            p = (pos + step_idx * 11) % len(out)
            lo = float(lower[p]) if p < len(lower) else 0.0
            hi = float(upper[p]) if p < len(upper) else 1.0
            try:
                current = float(out[p])
            except Exception:
                current = lo
            span = hi - lo
            if span <= 0:
                out[p] = lo
                continue
            u = _unit(local_seed, local_index, p + step_idx * 17)
            delta1 = (current - lo) / span
            delta2 = (hi - current) / span
            mut_pow = 1.0 / (eta_m + 1.0)
            if u <= 0.5:
                xy = 1.0 - delta1
                val = 2.0 * u + (1.0 - 2.0 * u) * (xy ** (eta_m + 1.0))
                delta_q = (val ** mut_pow) - 1.0
            else:
                xy = 1.0 - delta2
                val = 2.0 * (1.0 - u) + 2.0 * (u - 0.5) * (xy ** (eta_m + 1.0))
                delta_q = 1.0 - (val ** mut_pow)
            out[p] = min(hi, max(lo, current + delta_q * span))
        return out

    segments = spec.get('segments') if isinstance(spec.get('segments'), list) else []
    if encoding in {'composite', 'typed_composite', 'typed_compositional'} or segments:
        parent = genome if isinstance(genome, dict) else {}
        out = {}
        for seg_idx, segment in enumerate(segments):
            if not isinstance(segment, dict):
                continue
            name = _segment_name(segment, seg_idx)
            out[name] = _mutate_segment(parent.get(name), segment, seg_idx)
        return out

    is_order = encoding in {'order_permutation', 'permutation', 'order', 'order_encoding', 'permutation_order', 'sequence'} or 'permutation' in skill_id or 'order' in skill_id
    if is_order:
        raw_values = spec.get('values')
        values = []
        if isinstance(raw_values, list):
            for item in raw_values:
                if item not in values:
                    values.append(item)
        if not values:
            values = []
            if isinstance(genome, list):
                for item in genome:
                    if item not in values:
                        values.append(item)
            dimension = int(spec.get('dimension', spec.get('dim', 0)) or 0)
            if not values and dimension:
                values = list(range(dimension))
        raw = list(genome) if isinstance(genome, list) else []
        out = []
        for item in raw:
            if item in values and item not in out:
                out.append(item)
        for item in values:
            if item not in out:
                out.append(item)
        if len(out) > 2:
            i = int(_unit(operator_seed, mutation_index, 313) * len(out))
            j = int(_unit(operator_seed + 17, mutation_index, 719) * len(out))
            if i == j:
                j = (i + max(1, len(out) // 2)) % len(out)
            lo, hi = sorted([i, j])
            op = int(_unit(operator_seed + 31, mutation_index, 991) * 3)
            if op == 0:
                out[i], out[j] = out[j], out[i]
            elif op == 1:
                out[lo:hi + 1] = list(reversed(out[lo:hi + 1]))
            else:
                item = out.pop(i)
                insert_at = j if j < len(out) else len(out)
                out.insert(insert_at, item)
        elif len(out) > 1:
            out[0], out[1] = out[1], out[0]
        return out

    raw = list(genome) if isinstance(genome, list) else []
    dimension = int(spec.get('dimension', spec.get('dim', len(raw))) or len(raw))
    lower = spec.get('lower_bounds', spec.get('lb', spec.get('lower', 0)))
    upper = spec.get('upper_bounds', spec.get('ub', spec.get('upper', 1)))
    if not isinstance(lower, list):
        lower = [lower] * max(1, dimension)
    if not isinstance(upper, list):
        upper = [upper] * max(1, dimension)
    out = []
    for i in range(dimension):
        if i < len(raw):
            out.append(raw[i])
        elif i < len(lower):
            out.append(lower[i])
        else:
            out.append(0)
    if not out:
        return out
    pos = (mutation_index + operator_seed) % len(out)
    if encoding == 'binary' or 'binary' in skill_id:
        count = max(1, min(len(out), 1 + len(out) // 20))
        for step_idx in range(count):
            p = (pos + step_idx * 7) % len(out)
            try:
                out[p] = 0 if int(round(float(out[p]))) else 1
            except Exception:
                out[p] = 1
        return out
    if encoding in {'int_vector', 'integer_vector'} or 'int' in skill_id:
        count = max(1, min(len(out), 1 + len(out) // 12))
        for step_idx in range(count):
            p = (pos + step_idx * 7) % len(out)
            lo = int(lower[p]) if p < len(lower) else 0
            hi = int(upper[p]) if p < len(upper) else max(lo + 1, 1)
            if hi > lo:
                try:
                    current = int(round(float(out[p])))
                except Exception:
                    current = lo
                span = hi - lo + 1
                candidate = lo + int(_unit(operator_seed, mutation_index, p + step_idx) * span)
                if candidate > hi:
                    candidate = hi
                if span > 1 and candidate == current:
                    candidate = lo + ((candidate - lo + 1) % span)
                out[p] = candidate
            else:
                out[p] = lo
        return out

    eta_m = 20.0
    count = max(1, min(len(out), 1 + len(out) // 8))
    for step_idx in range(count):
        p = (pos + step_idx * 11) % len(out)
        lo = float(lower[p]) if p < len(lower) else 0.0
        hi = float(upper[p]) if p < len(upper) else 1.0
        try:
            current = float(out[p])
        except Exception:
            current = lo
        span = hi - lo
        if span <= 0:
            out[p] = lo
            continue
        u = _unit(operator_seed, mutation_index, p + step_idx * 17)
        delta1 = (current - lo) / span
        delta2 = (hi - current) / span
        mut_pow = 1.0 / (eta_m + 1.0)
        if u <= 0.5:
            xy = 1.0 - delta1
            val = 2.0 * u + (1.0 - 2.0 * u) * (xy ** (eta_m + 1.0))
            delta_q = (val ** mut_pow) - 1.0
        else:
            xy = 1.0 - delta2
            val = 2.0 * (1.0 - u) + 2.0 * (u - 0.5) * (xy ** (eta_m + 1.0))
            delta_q = 1.0 - (val ** mut_pow)
        candidate = current + delta_q * span
        out[p] = min(hi, max(lo, candidate))
    return out
""".strip()


STANDARD_CROSSOVER_OPERATOR_CODE = """
def crossover_operator(parent_a_genome, parent_b_genome, contract, memory):
    def _unit(seed, index, salt):
        raw = (abs(int(seed)) * 1103515245 + abs(int(index)) * 12345 + (salt + 1) * 2654435761) % 1000003
        return raw / 1000002.0

    spec = encoding_spec(contract, memory)
    if not isinstance(spec, dict):
        spec = {}
    encoding = str(spec.get('encoding', spec.get('type', ''))).lower()
    metadata = spec.get('metadata', {})
    skill_id = str(metadata.get('operator_skill_id', '')) if isinstance(metadata, dict) else ''
    skill_id = skill_id.lower()
    mem = memory if isinstance(memory, dict) else {}
    try:
        operator_index = int(mem.get('operator_index', 0) or 0)
    except Exception:
        operator_index = 0
    try:
        operator_seed = int(mem.get('operator_seed', operator_index) or 0)
    except Exception:
        operator_seed = operator_index

    def _segment_name(segment, idx):
        if isinstance(segment, dict):
            return str(segment.get('name') or segment.get('role') or ('segment_' + str(idx)))
        return 'segment_' + str(idx)

    def _segment_encoding(segment):
        return str(segment.get('encoding', segment.get('type', 'real_vector')) if isinstance(segment, dict) else 'real_vector').lower()

    def _segment_values(segment, genome_a, genome_b):
        values = []
        if isinstance(segment, dict) and isinstance(segment.get('values'), list):
            for item in segment.get('values'):
                if item not in values:
                    values.append(item)
        if not values:
            for raw_genome in [genome_a, genome_b]:
                if isinstance(raw_genome, list):
                    for item in raw_genome:
                        if item not in values:
                            values.append(item)
        if not values:
            try:
                values = list(range(int(segment.get('dimension', segment.get('dim', 0)) or 0))) if isinstance(segment, dict) else []
            except Exception:
                values = []
        return values

    def _normalize_order(raw_genome, values):
        raw = list(raw_genome) if isinstance(raw_genome, list) else []
        out = []
        for item in raw:
            if item in values and item not in out:
                out.append(item)
        for item in values:
            if item not in out:
                out.append(item)
        return out

    def _bounds(segment, dimension):
        lower = segment.get('lower_bounds', segment.get('lb', segment.get('lower', 0))) if isinstance(segment, dict) else 0
        upper = segment.get('upper_bounds', segment.get('ub', segment.get('upper', 1))) if isinstance(segment, dict) else 1
        if not isinstance(lower, list):
            lower = [lower] * max(1, dimension)
        if not isinstance(upper, list):
            upper = [upper] * max(1, dimension)
        return lower, upper

    def _normalize_vector(raw_genome, segment):
        raw = list(raw_genome) if isinstance(raw_genome, list) else []
        try:
            dimension = int(segment.get('dimension', segment.get('dim', len(raw))) or len(raw)) if isinstance(segment, dict) else len(raw)
        except Exception:
            dimension = len(raw)
        lower, _upper = _bounds(segment if isinstance(segment, dict) else {}, dimension)
        out = []
        for i in range(dimension):
            if i < len(raw):
                out.append(raw[i])
            elif i < len(lower):
                out.append(lower[i])
            else:
                out.append(0)
        return out

    def _crossover_segment(raw_a, raw_b, segment, seg_idx):
        seg_encoding = _segment_encoding(segment)
        seg_skill = str(segment.get('operator_skill_id', segment.get('skill_id', '')) if isinstance(segment, dict) else '').lower()
        is_seg_order = seg_encoding in {'order_permutation', 'permutation', 'order', 'order_encoding', 'permutation_order', 'sequence'} or 'permutation' in seg_skill or 'order' in seg_skill
        local_seed = operator_seed + (seg_idx + 1) * 104729
        local_index = operator_index + seg_idx * 7919
        if is_seg_order:
            values = _segment_values(segment, raw_a, raw_b)
            a = _normalize_order(raw_a, values)
            b = _normalize_order(raw_b, values)
            n = len(values)
            if n <= 1:
                return list(a)
            cut_a = int(_unit(local_seed, local_index, 101) * n)
            cut_b = int(_unit(local_seed + 17, local_index, 211) * n)
            if cut_a == cut_b:
                cut_b = (cut_a + max(1, n // 2)) % n
            start, end = sorted([cut_a, cut_b])
            if start == end:
                end = min(n, start + 1)
            segment_values = a[start:end]
            child = [None] * n
            for i in range(start, end):
                child[i] = a[i]
            cursor = 0
            for item in b:
                if item in segment_values:
                    continue
                while cursor < n and child[cursor] is not None:
                    cursor += 1
                if cursor < n:
                    child[cursor] = item
            for item in values:
                if item in child:
                    continue
                while cursor < n and child[cursor] is not None:
                    cursor += 1
                if cursor < n:
                    child[cursor] = item
            return child
        a = _normalize_vector(raw_a, segment)
        b = _normalize_vector(raw_b, segment)
        dimension = max(len(a), len(b))
        lower, upper = _bounds(segment if isinstance(segment, dict) else {}, dimension)
        while len(a) < dimension:
            a.append(lower[len(a)] if len(a) < len(lower) else 0)
        while len(b) < dimension:
            b.append(lower[len(b)] if len(b) < len(lower) else 0)
        if dimension <= 0:
            return []
        child = []
        if seg_encoding == 'real_vector' or 'real' in seg_skill:
            eta_c = 15.0
            for i in range(dimension):
                lo = float(lower[i]) if i < len(lower) else 0.0
                hi = float(upper[i]) if i < len(upper) else 1.0
                try:
                    av = float(a[i])
                    bv = float(b[i])
                except Exception:
                    av = lo
                    bv = lo
                if hi <= lo or abs(av - bv) <= 1e-14:
                    child.append(min(hi, max(lo, av)))
                    continue
                x1 = min(av, bv)
                x2 = max(av, bv)
                rand = min(1.0 - 1e-12, max(1e-12, _unit(local_seed, local_index, i)))
                beta = 1.0 + (2.0 * (x1 - lo) / (x2 - x1))
                alpha = 2.0 - (beta ** (-(eta_c + 1.0)))
                if rand <= 1.0 / alpha:
                    betaq = (rand * alpha) ** (1.0 / (eta_c + 1.0))
                else:
                    betaq = (1.0 / (2.0 - rand * alpha)) ** (1.0 / (eta_c + 1.0))
                c1 = 0.5 * ((x1 + x2) - betaq * (x2 - x1))
                beta = 1.0 + (2.0 * (hi - x2) / (x2 - x1))
                alpha = 2.0 - (beta ** (-(eta_c + 1.0)))
                if rand <= 1.0 / alpha:
                    betaq = (rand * alpha) ** (1.0 / (eta_c + 1.0))
                else:
                    betaq = (1.0 / (2.0 - rand * alpha)) ** (1.0 / (eta_c + 1.0))
                c2 = 0.5 * ((x1 + x2) + betaq * (x2 - x1))
                value = c1 if _unit(local_seed + 29, local_index, i) < 0.5 else c2
                child.append(min(hi, max(lo, value)))
            return child
        for i in range(dimension):
            value = a[i] if _unit(local_seed, local_index, i) < 0.5 else b[i]
            if seg_encoding == 'binary' or 'binary' in seg_skill:
                try:
                    value = 1 if int(round(float(value))) else 0
                except Exception:
                    value = 0
            elif seg_encoding in {'int_vector', 'integer_vector'} or 'int' in seg_skill:
                lo = int(lower[i]) if i < len(lower) else 0
                hi = int(upper[i]) if i < len(upper) else lo
                try:
                    value = int(round(float(value)))
                except Exception:
                    value = lo
                if hi >= lo:
                    value = min(hi, max(lo, value))
            child.append(value)
        return child

    segments = spec.get('segments') if isinstance(spec.get('segments'), list) else []
    if encoding in {'composite', 'typed_composite', 'typed_compositional'} or segments:
        parent_a = parent_a_genome if isinstance(parent_a_genome, dict) else {}
        parent_b = parent_b_genome if isinstance(parent_b_genome, dict) else {}
        out = {}
        for seg_idx, segment in enumerate(segments):
            if not isinstance(segment, dict):
                continue
            name = _segment_name(segment, seg_idx)
            out[name] = _crossover_segment(parent_a.get(name), parent_b.get(name), segment, seg_idx)
        return out

    is_order = encoding in {'order_permutation', 'permutation', 'order', 'order_encoding', 'permutation_order', 'sequence'} or 'permutation' in skill_id or 'order' in skill_id
    if is_order:
        raw_values = spec.get('values')
        values = []
        if isinstance(raw_values, list):
            for item in raw_values:
                if item not in values:
                    values.append(item)
        if not values:
            values = []
            for genome in [parent_a_genome, parent_b_genome]:
                if isinstance(genome, list):
                    for item in genome:
                        if item not in values:
                            values.append(item)
            dimension = int(spec.get('dimension', spec.get('dim', 0)) or 0)
            if not values and dimension:
                values = list(range(dimension))
        parents = []
        for genome in [parent_a_genome, parent_b_genome]:
            raw = list(genome) if isinstance(genome, list) else []
            out = []
            for item in raw:
                if item in values and item not in out:
                    out.append(item)
            for item in values:
                if item not in out:
                    out.append(item)
            parents.append(out)
        a = parents[0]
        b = parents[1]
        n = len(values)
        if n <= 1:
            return list(a)
        cut_a = int(_unit(operator_seed, operator_index, 101) * n)
        cut_b = int(_unit(operator_seed + 17, operator_index, 211) * n)
        if cut_a == cut_b:
            cut_b = (cut_a + max(1, n // 2)) % n
        start, end = sorted([cut_a, cut_b])
        if start == end:
            end = min(n, start + 1)
        segment = a[start:end]
        child = [None] * n
        for i in range(start, end):
            child[i] = a[i]
        cursor = 0
        for item in b:
            if item in segment:
                continue
            while cursor < n and child[cursor] is not None:
                cursor += 1
            if cursor < n:
                child[cursor] = item
        for item in values:
            if item in child:
                continue
            while cursor < n and child[cursor] is not None:
                cursor += 1
            if cursor < n:
                child[cursor] = item
        return child

    a = list(parent_a_genome) if isinstance(parent_a_genome, list) else []
    b = list(parent_b_genome) if isinstance(parent_b_genome, list) else []
    dimension = int(spec.get('dimension', spec.get('dim', max(len(a), len(b)))) or max(len(a), len(b)))
    lower = spec.get('lower_bounds', spec.get('lb', spec.get('lower', 0)))
    upper = spec.get('upper_bounds', spec.get('ub', spec.get('upper', 1)))
    if not isinstance(lower, list):
        lower = [lower] * max(1, dimension)
    if not isinstance(upper, list):
        upper = [upper] * max(1, dimension)
    while len(a) < dimension:
        a.append(lower[len(a)] if len(a) < len(lower) else 0)
    while len(b) < dimension:
        b.append(lower[len(b)] if len(b) < len(lower) else 0)
    if dimension <= 0:
        return []
    child = []
    if encoding == 'real_vector' or 'real' in skill_id:
        eta_c = 15.0
        for i in range(dimension):
            lo = float(lower[i]) if i < len(lower) else 0.0
            hi = float(upper[i]) if i < len(upper) else 1.0
            try:
                av = float(a[i])
                bv = float(b[i])
            except Exception:
                av = lo
                bv = lo
            if hi <= lo:
                child.append(lo)
                continue
            if abs(av - bv) <= 1e-14:
                child.append(min(hi, max(lo, av)))
                continue
            x1 = min(av, bv)
            x2 = max(av, bv)
            rand = min(1.0 - 1e-12, max(1e-12, _unit(operator_seed, operator_index, i)))
            beta = 1.0 + (2.0 * (x1 - lo) / (x2 - x1))
            alpha = 2.0 - (beta ** (-(eta_c + 1.0)))
            if rand <= 1.0 / alpha:
                betaq = (rand * alpha) ** (1.0 / (eta_c + 1.0))
            else:
                betaq = (1.0 / (2.0 - rand * alpha)) ** (1.0 / (eta_c + 1.0))
            c1 = 0.5 * ((x1 + x2) - betaq * (x2 - x1))
            beta = 1.0 + (2.0 * (hi - x2) / (x2 - x1))
            alpha = 2.0 - (beta ** (-(eta_c + 1.0)))
            if rand <= 1.0 / alpha:
                betaq = (rand * alpha) ** (1.0 / (eta_c + 1.0))
            else:
                betaq = (1.0 / (2.0 - rand * alpha)) ** (1.0 / (eta_c + 1.0))
            c2 = 0.5 * ((x1 + x2) + betaq * (x2 - x1))
            value = c1 if _unit(operator_seed + 29, operator_index, i) < 0.5 else c2
            child.append(min(hi, max(lo, value)))
        return child
    for i in range(dimension):
        value = a[i] if _unit(operator_seed, operator_index, i) < 0.5 else b[i]
        if encoding == 'binary' or 'binary' in skill_id:
            try:
                value = 1 if int(round(float(value))) else 0
            except Exception:
                value = 0
        elif encoding in {'int_vector', 'integer_vector'} or 'int' in skill_id:
            lo = int(lower[i]) if i < len(lower) else 0
            hi = int(upper[i]) if i < len(upper) else lo
            try:
                value = int(round(float(value)))
            except Exception:
                value = lo
            if hi >= lo:
                value = min(hi, max(lo, value))
        child.append(value)
    return child
""".strip()


def standard_operator_artifacts(task_id: str, prompt_version: str = "standard_ea_operator_registry", selected_skills: dict[str, Any] | None = None) -> dict[str, GeneratedArtifact]:
    selected_skills = selected_skills if isinstance(selected_skills, dict) else {}
    mutation_skill_id = str(selected_skills.get("mutation_skill_id") or "auto_standard_mutation")
    crossover_skill_id = str(selected_skills.get("crossover_skill_id") or "auto_standard_crossover")
    return {
        "mutation_operator": GeneratedArtifact(
            artifact_id=f"{task_id}_standard_mutation_operator",
            artifact_type="mutation_operator",
            code=STANDARD_MUTATION_OPERATOR_CODE,
            function_name="mutation_operator",
            prompt_version=prompt_version,
            metadata={"source": "standard_ea_operator_registry", "skill_id": mutation_skill_id},
        ),
        "crossover_operator": GeneratedArtifact(
            artifact_id=f"{task_id}_standard_crossover_operator",
            artifact_type="crossover_operator",
            code=STANDARD_CROSSOVER_OPERATOR_CODE,
            function_name="crossover_operator",
            prompt_version=prompt_version,
            metadata={"source": "standard_ea_operator_registry", "skill_id": crossover_skill_id},
        ),
    }


@dataclass
class ArtifactBundle:
    contract: OptimizationContract
    artifacts: dict[str, GeneratedArtifact] = field(default_factory=dict)
    linear_program_spec: dict[str, Any] | None = None
    solver_recommendation: dict[str, Any] = field(default_factory=dict)
    tests: list[dict[str, Any]] = field(default_factory=list)
    generation_trace: dict[str, Any] = field(default_factory=dict)

    def get(self, artifact_type: str) -> GeneratedArtifact:
        if artifact_type not in self.artifacts:
            raise KeyError(f"missing artifact: {artifact_type}")
        return self.artifacts[artifact_type]


@dataclass
class UniversalOptimizationArtifact:
    """Loaded executable contract used by generic search skills."""

    bundle: ArtifactBundle
    functions: dict[str, Any]

    @property
    def contract(self) -> dict[str, Any]:
        return self.bundle.contract.__dict__

    def precompute(self, memory: dict[str, Any] | None = None) -> dict[str, Any]:
        fn = self.functions.get("precompute")
        if fn is None:
            return {}
        value = fn(self.contract, memory or {})
        return value if isinstance(value, dict) else {"value": value}

    def verifier(self, solution: dict[str, Any], memory: dict[str, Any] | None = None) -> dict[str, Any]:
        if _is_genome_only(solution) and "decode" in self.functions:
            solution = self.decode(solution["genome"], memory)
        return self.functions["verifier"](solution, self.contract, memory or {})

    def objective(self, solution: dict[str, Any], memory: dict[str, Any] | None = None) -> Any:
        if _is_genome_only(solution) and "decode" in self.functions:
            solution = self.decode(solution["genome"], memory)
        return self.functions["objective"](solution, self.contract, memory or {})

    def repair(self, solution: dict[str, Any], memory: dict[str, Any] | None = None) -> dict[str, Any]:
        original_genome = solution.get("genome") if isinstance(solution, dict) else None
        repaired = self.functions["repair_operator"](solution, self.contract, memory or {})
        if isinstance(repaired, dict) and "genome" not in repaired and original_genome is not None:
            repaired["genome"] = original_genome
        return repaired

    def mutate(self, solution: dict[str, Any], memory: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(solution, dict) or "genome" not in solution:
            raise ValueError("EA mutation requires decoded solution with genome")
        genome = self.functions["mutation_operator"](solution["genome"], self.contract, memory or {})
        return self.decode(genome, memory)

    def crossover(self, parent_a: dict[str, Any], parent_b: dict[str, Any], memory: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(parent_a, dict) or not isinstance(parent_b, dict) or "genome" not in parent_a or "genome" not in parent_b:
            raise ValueError("EA crossover requires decoded parent solutions with genome")
        genome = self.functions["crossover_operator"](parent_a["genome"], parent_b["genome"], self.contract, memory or {})
        return self.decode(genome, memory)

    def encoding_spec(self, memory: dict[str, Any] | None = None) -> dict[str, Any]:
        fn = self.functions.get("encoding_spec")
        if fn is None:
            return {}
        value = fn(self.contract, memory or {})
        return value if isinstance(value, dict) else {}

    def genome_at(self, memory: dict[str, Any] | None = None, index: int = 0) -> Any:
        memory = memory or {}
        spec = self.encoding_spec(memory)
        seed = memory.get("operator_seed", memory.get("candidate_seed", memory.get("seed", 0)))
        return deterministic_genome_from_spec(spec, index, seed=seed)

    def decode(self, genome: Any, memory: dict[str, Any] | None = None) -> dict[str, Any]:
        if "decode" not in self.functions:
            if isinstance(genome, dict):
                return genome
            return {"genome": genome}
        solution = self.functions["decode"](genome, self.contract, memory or {})
        if isinstance(solution, dict):
            solution.setdefault("genome", genome)
            return solution
        return {"solution": solution, "genome": genome}


def deterministic_genome_from_spec(spec: dict[str, Any], index: int = 0, seed: int | float | str | None = 0) -> Any:
    encoding = str(spec.get("encoding", spec.get("type", "real_vector"))).lower()
    segments = spec.get("segments") if isinstance(spec.get("segments"), list) else []
    if encoding in COMPOSITE_ENCODINGS or segments:
        try:
            seed_value = int(seed or 0)
        except Exception:
            seed_value = 0
        genome: dict[str, Any] = {}
        for seg_idx, raw_segment in enumerate(segments):
            if not isinstance(raw_segment, dict):
                continue
            name = _segment_name(raw_segment, seg_idx)
            segment = _segment_as_spec(raw_segment)
            genome[name] = deterministic_genome_from_spec(
                segment,
                index=index + seg_idx * 7919,
                seed=seed_value + (seg_idx + 1) * 104729,
            )
        return genome
    dimension = int(spec.get("dimension", spec.get("dim", 0)) or 0)
    lower = spec.get("lower_bounds", spec.get("lb", spec.get("lower", 0)))
    upper = spec.get("upper_bounds", spec.get("ub", spec.get("upper", 1)))
    try:
        seed_value = int(seed or 0)
    except Exception:
        seed_value = 0
    if encoding in PERMUTATION_ENCODINGS:
        values = []
        for item in list(spec.get("values") or range(dimension)):
            if item not in values:
                values.append(item)
        if values:
            if seed_value:
                decorated = []
                for pos, item in enumerate(values):
                    raw = ((seed_value + 1) * 1103515245 + (index + 1) * 12345 + (pos + 1) * 2654435761) % 1000003
                    decorated.append((raw, pos, item))
                return [item for _, _, item in sorted(decorated)]
            shift = index % len(values)
            return values[shift:] + values[:shift]
        return []
    if not isinstance(lower, list):
        lower = [lower] * dimension
    if not isinstance(upper, list):
        upper = [upper] * dimension
    genome = []
    fractions = [0.1, 0.25, 0.5, 0.6, 0.65, 0.75, 0.9]
    all_fraction_start = 3
    sweep_start = all_fraction_start + len(fractions)
    structured = index <= 2 or (dimension > 0 and index < sweep_start + dimension * len(fractions))
    for i in range(dimension):
        lo = float(lower[i])
        hi = float(upper[i])
        if index == 0:
            frac = 0.5
        elif index == 1:
            frac = 0.0
        elif index == 2:
            frac = 1.0
        elif structured and index < sweep_start:
            frac = fractions[index - all_fraction_start]
        elif structured:
            sweep_index = index - sweep_start
            sweep_pos = (sweep_index // len(fractions)) % max(1, dimension)
            frac = fractions[sweep_index % len(fractions)] if i == sweep_pos else 0.0
        elif seed_value:
            raw = (
                (abs(seed_value) + 1) * 1103515245
                + (index + 1) * 12345
                + (i + 1) * 2654435761
                + (abs(seed_value) + 1) * (index + 1) * (i + 1) * 97
            ) % 1000003
            frac = raw / 1000002.0
        else:
            raw = ((index + 1) * 1103515245 + (i + 1) * 2654435761 + (index + 1) * (i + 1) * 12345) % 1000003
            frac = raw / 1000002.0
        value = lo + (hi - lo) * frac
        if encoding in {"int_vector", "integer_vector", "binary"}:
            value = int(round(value))
        genome.append(value)
    return genome


def default_crossover_from_spec(parent_a: Any, parent_b: Any, spec: dict[str, Any]) -> Any:
    encoding = str(spec.get("encoding", spec.get("type", ""))).lower()
    segments = spec.get("segments") if isinstance(spec.get("segments"), list) else []
    if encoding in COMPOSITE_ENCODINGS or segments:
        a = parent_a if isinstance(parent_a, dict) else {}
        b = parent_b if isinstance(parent_b, dict) else {}
        child: dict[str, Any] = {}
        for seg_idx, raw_segment in enumerate(segments):
            if not isinstance(raw_segment, dict):
                continue
            name = _segment_name(raw_segment, seg_idx)
            child[name] = default_crossover_from_spec(a.get(name), b.get(name), _segment_as_spec(raw_segment))
        return child
    if encoding in PERMUTATION_ENCODINGS:
        values = _spec_values(spec, parent_a, parent_b)
        a = _normalize_permutation(parent_a, values)
        b = _normalize_permutation(parent_b, values)
        if len(a) <= 1:
            return a
        start = len(a) // 3
        end = max(start + 1, (len(a) * 2) // 3)
        segment = a[start:end]
        child: list[Any] = [None] * len(a)
        child[start:end] = segment
        cursor = 0
        for item in b:
            if item in segment:
                continue
            while cursor < len(child) and child[cursor] is not None:
                cursor += 1
            if cursor < len(child):
                child[cursor] = item
        return [item if item is not None else values[idx] for idx, item in enumerate(child)]
    a = list(parent_a) if isinstance(parent_a, list) else []
    b = list(parent_b) if isinstance(parent_b, list) else []
    n = max(len(a), len(b), int(spec.get("dimension", spec.get("dim", 0)) or 0))
    if n <= 0:
        return []
    if len(a) < n:
        a = list(deterministic_genome_from_spec(spec, 0))[:n]
    if len(b) < n:
        b = list(deterministic_genome_from_spec(spec, 1))[:n]
    lower = spec.get("lower_bounds", spec.get("lb", spec.get("lower", 0)))
    upper = spec.get("upper_bounds", spec.get("ub", spec.get("upper", 1)))
    if not isinstance(lower, list):
        lower = [lower] * n
    if not isinstance(upper, list):
        upper = [upper] * n
    if encoding == "real_vector":
        eta_c = 15.0
        child = []
        for i in range(n):
            lo = float(lower[i])
            hi = float(upper[i])
            av = float(a[i])
            bv = float(b[i])
            if hi <= lo or abs(av - bv) <= 1e-14:
                child.append(min(hi, max(lo, av)))
                continue
            x1, x2 = sorted([av, bv])
            rand = min(1.0 - 1e-12, max(1e-12, _deterministic_unit(n, i, 17)))
            beta = 1.0 + (2.0 * (x1 - lo) / (x2 - x1))
            alpha = 2.0 - beta ** (-(eta_c + 1.0))
            betaq = (rand * alpha) ** (1.0 / (eta_c + 1.0)) if rand <= 1.0 / alpha else (1.0 / (2.0 - rand * alpha)) ** (1.0 / (eta_c + 1.0))
            c1 = 0.5 * ((x1 + x2) - betaq * (x2 - x1))
            beta = 1.0 + (2.0 * (hi - x2) / (x2 - x1))
            alpha = 2.0 - beta ** (-(eta_c + 1.0))
            betaq = (rand * alpha) ** (1.0 / (eta_c + 1.0)) if rand <= 1.0 / alpha else (1.0 / (2.0 - rand * alpha)) ** (1.0 / (eta_c + 1.0))
            c2 = 0.5 * ((x1 + x2) + betaq * (x2 - x1))
            value = c1 if _deterministic_unit(n, i, 29) < 0.5 else c2
            child.append(min(hi, max(lo, value)))
        return child
    child = []
    for i in range(n):
        value = a[i] if _deterministic_unit(n, i, 43) < 0.5 else b[i]
        if encoding == "binary":
            value = 1 if int(round(float(value))) else 0
        elif encoding in {"int_vector", "integer_vector"}:
            value = min(int(upper[i]), max(int(lower[i]), int(round(float(value)))))
        child.append(value)
    return child


def default_mutation_from_spec(genome: Any, spec: dict[str, Any], index: int = 0) -> Any:
    encoding = str(spec.get("encoding", spec.get("type", ""))).lower()
    segments = spec.get("segments") if isinstance(spec.get("segments"), list) else []
    if encoding in COMPOSITE_ENCODINGS or segments:
        parent = genome if isinstance(genome, dict) else {}
        mutated: dict[str, Any] = {}
        for seg_idx, raw_segment in enumerate(segments):
            if not isinstance(raw_segment, dict):
                continue
            name = _segment_name(raw_segment, seg_idx)
            mutated[name] = default_mutation_from_spec(parent.get(name), _segment_as_spec(raw_segment), index + seg_idx * 7919)
        return mutated
    if encoding in PERMUTATION_ENCODINGS:
        values = _spec_values(spec, genome, [])
        out = _normalize_permutation(genome, values)
        if len(out) > 2:
            i = index % len(out)
            j = (index * 7 + 3) % len(out)
            if i == j:
                j = (i + max(1, len(out) // 2)) % len(out)
            lo, hi = sorted([i, j])
            op = index % 3
            if op == 0:
                out[i], out[j] = out[j], out[i]
            elif op == 1:
                out[lo:hi + 1] = list(reversed(out[lo:hi + 1]))
            else:
                item = out.pop(i)
                out.insert(j if j < len(out) else len(out), item)
        elif len(out) > 1:
            out[0], out[1] = out[1], out[0]
        return out
    out = list(genome) if isinstance(genome, list) else list(deterministic_genome_from_spec(spec, index))
    if not out:
        return out
    lower = spec.get("lower_bounds", spec.get("lb", spec.get("lower", 0)))
    upper = spec.get("upper_bounds", spec.get("ub", spec.get("upper", 1)))
    if not isinstance(lower, list):
        lower = [lower] * len(out)
    if not isinstance(upper, list):
        upper = [upper] * len(out)
    pos = index % len(out)
    if encoding == "binary":
        out[pos] = 0 if int(out[pos]) else 1
    elif encoding in {"int_vector", "integer_vector"}:
        lo = int(lower[pos])
        hi = int(upper[pos])
        span = max(1, hi - lo + 1)
        candidate = lo + int(_deterministic_unit(index, pos, 59) * span)
        if candidate > hi:
            candidate = hi
        if span > 1 and candidate == int(round(float(out[pos]))):
            candidate = lo + ((candidate - lo + 1) % span)
        out[pos] = candidate
    else:
        lo = float(lower[pos])
        hi = float(upper[pos])
        span = hi - lo
        if span <= 0:
            out[pos] = lo
        else:
            current = float(out[pos])
            eta_m = 20.0
            u = _deterministic_unit(index, pos, 71)
            delta1 = (current - lo) / span
            delta2 = (hi - current) / span
            mut_pow = 1.0 / (eta_m + 1.0)
            if u <= 0.5:
                xy = 1.0 - delta1
                val = 2.0 * u + (1.0 - 2.0 * u) * (xy ** (eta_m + 1.0))
                delta_q = (val ** mut_pow) - 1.0
            else:
                xy = 1.0 - delta2
                val = 2.0 * (1.0 - u) + 2.0 * (u - 0.5) * (xy ** (eta_m + 1.0))
                delta_q = 1.0 - (val ** mut_pow)
            out[pos] = min(hi, max(lo, current + delta_q * span))
    return out


def _deterministic_unit(seed: int, index: int, salt: int) -> float:
    raw = (abs(int(seed)) * 1103515245 + abs(int(index)) * 12345 + (salt + 1) * 2654435761) % 1000003
    return raw / 1000002.0


def _segment_name(segment: dict[str, Any], index: int) -> str:
    value = segment.get("name") or segment.get("role") or f"segment_{index}"
    return str(value)


def _segment_as_spec(segment: dict[str, Any]) -> dict[str, Any]:
    spec = dict(segment)
    encoding = spec.get("encoding", spec.get("type"))
    if encoding is None:
        encoding = spec.get("primitive", "real_vector")
    spec["encoding"] = str(encoding)
    return spec


def _spec_values(spec: dict[str, Any], parent_a: Any, parent_b: Any) -> list[Any]:
    values = spec.get("values")
    if isinstance(values, list) and values:
        unique = []
        for item in values:
            if item not in unique:
                unique.append(item)
        return unique
    inferred = []
    for genome in [parent_a, parent_b]:
        if isinstance(genome, list):
            for item in genome:
                if item not in inferred:
                    inferred.append(item)
    dimension = int(spec.get("dimension", spec.get("dim", 0)) or 0)
    return inferred or list(range(dimension))


def _normalize_permutation(genome: Any, values: list[Any]) -> list[Any]:
    raw = list(genome) if isinstance(genome, list) else []
    out = []
    for item in raw:
        if item in values and item not in out:
            out.append(item)
    out.extend(item for item in values if item not in out)
    return out


def _is_genome_only(solution: Any) -> bool:
    return isinstance(solution, dict) and set(solution.keys()) <= {"genome"} and "genome" in solution
