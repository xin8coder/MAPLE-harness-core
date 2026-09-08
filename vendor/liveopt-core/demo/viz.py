"""Render optimization results to PNG images (matplotlib, Agg backend).

Every committed LiveOpt state gets a result image card: a Pareto scatter for
multi-objective runs (3+ objectives are projected onto the first two axes and
labeled), a scalar summary otherwise, plus a small table rendering of the
accepted plan. If matplotlib is unavailable the cards are skipped gracefully.
"""

from __future__ import annotations

import base64
import importlib.util
import io
from typing import Any

NAVY = "#12335D"
TEAL = "#2A9D9F"


def matplotlib_available() -> bool:
    return importlib.util.find_spec("matplotlib") is not None


def _pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _to_data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _figure_to_png(fig: Any) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight", facecolor="white")
    buffer.seek(0)
    return buffer.read()


def render_pareto_png(points: list[dict[str, Any]], objective_names: list[str]) -> tuple[bytes, str]:
    """Scatter of the accepted front; 3+ objectives project onto the first two."""

    plt = _pyplot()
    vectors = [p["objectives"] for p in points if isinstance(p.get("objectives"), list) and len(p["objectives"]) >= 2]
    dim = len(vectors[0])
    xs = [v[0] for v in vectors]
    ys = [v[1] for v in vectors]
    fig, ax = plt.subplots(figsize=(4.6, 3.2))
    ax.scatter(xs, ys, c=TEAL, edgecolors=NAVY, s=42, zorder=3)
    name_x = objective_names[0] if len(objective_names) > 0 else "objective 0"
    name_y = objective_names[1] if len(objective_names) > 1 else "objective 1"
    ax.set_xlabel(name_x, fontsize=9)
    ax.set_ylabel(name_y, fontsize=9)
    caption = f"Pareto front: {name_x} vs {name_y} ({len(vectors)} points)"
    if dim > 2:
        caption += f" — projected from {dim} objectives"
        ax.set_title(f"projection of {dim} objectives", fontsize=8, color="#6b7686")
    ax.grid(alpha=0.3)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    png = _figure_to_png(fig)
    plt.close(fig)
    return png, caption


def render_scalar_summary_png(best: dict[str, Any], objective_names: list[str]) -> tuple[bytes, str]:
    """Headline figure for scalar results: objective value + feasibility."""

    plt = _pyplot()
    scalar = best.get("scalar")
    feasible = best.get("feasible")
    name = objective_names[0] if objective_names else "objective"
    fig, ax = plt.subplots(figsize=(4.2, 1.9))
    color = TEAL if feasible else "#B91C1C"
    ax.barh([0], [1], color="#eef0f3", height=0.55)
    ax.barh([0], [1], color=color, height=0.22)
    label = f"{name} = {scalar:.4g}" if isinstance(scalar, (int, float)) else f"{name} = {scalar}"
    ax.text(0.5, 0.62, label, ha="center", va="bottom", fontsize=13, fontweight="bold", color=NAVY)
    ax.text(0.5, -0.42, "feasible" if feasible else "infeasible", ha="center", va="top", fontsize=9, color=color)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.7, 1.1)
    ax.axis("off")
    png = _figure_to_png(fig)
    plt.close(fig)
    return png, f"{label} ({'feasible' if feasible else 'infeasible'})"


def render_plan_table_png(solution: dict[str, Any], *, max_rows: int = 12) -> tuple[bytes, str]:
    """Render the accepted plan (flat key -> scalar/short-list) as a table image."""

    plt = _pyplot()
    rows = []
    for key, value in list((solution or {}).items())[:max_rows]:
        text = value if isinstance(value, str) else _compact(value)
        rows.append([str(key), text])
    if not rows:
        rows = [["plan", "(empty)"]]
    fig, ax = plt.subplots(figsize=(4.6, 0.42 * (len(rows) + 1) + 0.5))
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=["field", "value"], loc="center", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    for (row, _col), cell in table.get_celld().items():
        cell.set_edgecolor("#e2e5ea")
        if row == 0:
            cell.set_facecolor(NAVY)
            cell.set_text_props(color="white", fontweight="bold")
    png = _figure_to_png(fig)
    plt.close(fig)
    return png, "Accepted plan"


def _compact(value: Any, limit: int = 60) -> str:
    import json

    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def result_image_cards(
    accepted: dict[str, Any],
    objective_names: list[str],
) -> list[dict[str, Any]]:
    """Build image cards for one committed state; [] when matplotlib is absent."""

    if not matplotlib_available():
        return []
    cards = []
    best = accepted.get("best") or {}
    points = [p for p in (accepted.get("archive") or []) if isinstance(p.get("objectives"), list)]
    try:
        if points and all(len(p["objectives"]) >= 2 for p in points):
            png, caption = render_pareto_png(points, objective_names)
        else:
            png, caption = render_scalar_summary_png(best, objective_names)
        cards.append({"type": "image", "title": "Result", "data": {"image": _to_data_url(png), "caption": caption}})
    except Exception:  # noqa: BLE001 - a rendering failure must not break the turn
        return []
    try:
        solution = best.get("solution") or {}
        if solution:
            png, caption = render_plan_table_png(solution)
            cards.append({"type": "image", "title": "Accepted plan", "data": {"image": _to_data_url(png), "caption": caption}})
    except Exception:  # noqa: BLE001
        pass
    return cards
