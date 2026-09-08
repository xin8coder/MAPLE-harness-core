from __future__ import annotations

from evo2.skills.base import Skill, SkillContext, SkillResult
from evo2.skills.restart._utils import operator_memory, repair_individual, solution_to_individual, universal_decoder


class EliteImmigrantRestartSkill(Skill):
    skill_id = "elite_immigrant_restart_v1"
    skill_type = "restart"
    description = "Mix repaired elites, diverse representatives, targeted immigrants, and random individuals."
    suitable_change_scale = "medium-to-large"
    handles = ["population drift", "medium-to-large changes", "need for exploration while retaining good historical solutions"]
    limitations = ["requires previous population", "less stable than warm restart"]
    planner_tags = ["elite_reuse", "immigrants", "exploration", "medium_change"]

    def __init__(self, elite_ratio=0.3, immigrant_ratio=0.2, random_ratio=0.3, diverse_ratio=0.2):
        self.elite_ratio = elite_ratio
        self.immigrant_ratio = immigrant_ratio
        self.random_ratio = random_ratio
        self.diverse_ratio = diverse_ratio

    def applicable(self, context: SkillContext) -> bool:
        return context.previous_population is not None

    def run(self, context: SkillContext) -> SkillResult:
        pop = context.previous_population
        target_size = int(context.budget.get("population_size", len(pop.individuals) or 10))
        n_elite = max(1, int(target_size * self.elite_ratio))
        n_diverse = max(1, int(target_size * self.diverse_ratio))
        n_immigrant = max(1, int(target_size * self.immigrant_ratio))
        n_random = max(0, target_size - n_elite - n_diverse - n_immigrant)

        individuals = []
        individuals.extend(repair_individual(ind, context) for ind in pop.elites(n_elite))
        individuals.extend(repair_individual(ind, context) for ind in pop.diverse_representatives(n_diverse))
        individuals.extend(self._make_targeted_immigrants(n_immigrant, context))
        individuals.extend(self._make_random_individuals(n_random, context))
        return SkillResult(True, individuals[:target_size], {"restart": self.skill_id, "elite": n_elite, "diverse": n_diverse, "immigrant": n_immigrant, "random": n_random})

    def _make_targeted_immigrants(self, n, context):
        decoder = universal_decoder(context)
        inds = []
        base = context.previous_solution
        for idx in range(n):
            sol = decoder.mutate_solution(base, operator_memory(context)) if base else decoder.candidate_at(idx, operator_memory(context))
            inds.append(solution_to_individual(sol, f"immigrant_{idx}"))
        return inds

    def _make_random_individuals(self, n, context):
        decoder = universal_decoder(context)
        return [solution_to_individual(decoder.candidate_at(idx, operator_memory(context)), f"candidate_{idx}") for idx in range(n)]
