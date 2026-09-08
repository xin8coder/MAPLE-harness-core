from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RestartSelectionInput:
    change_summary: dict
    impact_summary: dict
    population_summary: dict
    budget: dict
    candidate_skills: list
    strategy_memory: list


class RestartSelector:
    def select(self, change_summary, impact_summary, population_summary, candidate_skills, budget=None, strategy_memory=None):
        available = {getattr(s, "skill_id", s) for s in candidate_skills}
        impact = impact_summary.get("impact_level", change_summary.get("impact_level", "medium"))
        diversity = population_summary.get("diversity_level", "medium")
        requested = []
        change_events = change_summary.get("change_events", []) if isinstance(change_summary, dict) else []
        event_text = " ".join(str(event.get("type", "")) + " " + str(event.get("description", "")) for event in change_events if isinstance(event, dict)).lower()
        hard_constraint_update = any(
            cue in event_text
            for cue in [
                "constraint",
                "capacity",
                "unavailable",
                "maintenance",
                "budget",
                "deadline",
                "sla",
                "resource",
            ]
        )
        if hard_constraint_update and "feasibility_preserving_restart_v1" in available:
            requested.append("feasibility_preserving_restart_v1")
        if impact == "large":
            requested.extend(["population_transfer_v1", "warm_restart_v1", "full_restart_v1"])
        elif impact == "small":
            requested.extend(["warm_restart_v1"])
        elif diversity == "low":
            requested.extend(["elite_immigrant_restart_v1", "diversity_restart_v1"])
        else:
            requested.extend(["warm_restart_v1", "elite_immigrant_restart_v1"])
        selected = [sid for sid in requested if sid in available]
        return selected or list(available)[:1]
