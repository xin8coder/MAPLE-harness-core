from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UpdateEventSpec:
    update_id: str
    time_index: int
    natural_language_update: str
    expected_event_types: list[str] = field(default_factory=list)
    expected_patch_types: list[str] = field(default_factory=list)
    recommended_restart_skills: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkEpisode:
    episode_id: str
    base_benchmark: str
    domain: str
    base_instance_id: str
    initial_natural_language_task: str
    structured_data_path: str | None = None
    initial_budget: dict[str, Any] = field(default_factory=dict)
    update_stream: list[UpdateEventSpec] = field(default_factory=list)
    evaluation_focus: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenUsage:
    initial_parse_tokens: int = 0
    initial_model_tokens: int = 0
    initial_fitness_tokens: int = 0
    update_parse_tokens: int = 0
    patch_generation_tokens: int = 0
    restart_selection_tokens: int = 0
    verifier_feedback_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    provider_prompt_cache_hit_tokens: int = 0
    provider_prompt_cache_miss_tokens: int = 0
    local_cache_hits: int = 0
    local_cache_saved_tokens: int = 0
    mode: str = "estimated_rule_based"

    def add(self, field_name: str, text: str, completion_text: str = "") -> None:
        prompt = estimate_tokens(text)
        completion = estimate_tokens(completion_text)
        setattr(self, field_name, getattr(self, field_name) + prompt + completion)
        self.total_prompt_tokens += prompt
        self.total_completion_tokens += completion
        self.total_tokens += prompt + completion


@dataclass
class EpisodeMetrics:
    episode_id: str
    update_count: int
    all_updates_feasible: bool
    final_feasible: bool
    initial_objective: float
    final_objective: float
    cumulative_objective: float
    cumulative_disruption: float
    cumulative_latency_seconds: float
    cumulative_token_cost: int
    average_token_per_update: float
    memory_reuse_ratio: float
    patch_success_rate: float
    restart_skill_history: list[str]
    verifier_failure_count: int
    hidden_evaluation_available: bool = False
    hidden_true_pass_count: int = 0
    hidden_true_update_pass_ratio: float | None = None
    hidden_retry_count: int = 0
    terminated_early: bool = False


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    # Rough multilingual estimate: ASCII ~4 chars/token, CJK closer to 1.5 chars/token.
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = max(0, len(text) - cjk)
    return max(1, int(cjk / 1.5 + other / 4))
