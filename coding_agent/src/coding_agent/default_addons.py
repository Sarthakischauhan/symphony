"""The addons every product coding agent mounts, in order.

Why: the parent agent and its spawned children share one list, so the product
defaults live in one place. Children pass no learning loop and no evaluation
config, so they skip learning and Jev (a child's run is judged by its parent).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from core_harness import HarnessConfig, Persistence
from core_harness.addons.persistence import PersistenceAddon
from core_harness.addons.subagent import SubagentAddon

from coding_agent.compaction import ai_compaction_from_config
from coding_agent.config import CompactionConfig, EvaluationConfig, LangfuseConfig
from coding_agent.evaluation import jev_from_config
from coding_agent.langfuse import langfuse_from_config
from coding_agent.learning import LearningAddon, LearningLoop
from coding_agent.plan import PlanStore
from coding_agent.plan_mode import PlanModeState


def default_addons(
    *,
    persistence: Persistence,
    harness_config: HarnessConfig,
    compaction: Optional[CompactionConfig] = None,
    spawn_configure: Any = None,
    include_subagent: bool = True,
    langfuse: Optional[LangfuseConfig] = None,
    evaluation: Optional[EvaluationConfig] = None,
    plan_store: Optional[PlanStore] = None,
    plan_mode: Optional[PlanModeState] = None,
    learning: Optional[LearningLoop] = None,
    should_review: Optional[Callable[[], bool]] = None,
) -> list:
    """Product defaults: persistence, AI compaction, spawn_agent, Langfuse, Jev, learning.

    Compaction is always ``AiCompactionAddon`` (``InferenceCompactor``); the
    harness template compactor is not mounted by coding_agent. Langfuse is
    mounted when enabled in config; the add-on stays silent without keys.
    Jev critic mode mounts only when ``evaluation.enabled`` is true.
    Learning mounts only when a ``LearningLoop`` is passed; omit it so children
    skip (matches ``LearningAddon.fork_for_child`` → ``None``).
    """
    compaction = compaction or CompactionConfig()
    addons: list = [
        PersistenceAddon(persistence),
        ai_compaction_from_config(harness_config, compaction),
    ]
    if include_subagent:
        addons.append(SubagentAddon(configure=spawn_configure, background=True))
    langfuse_addon = langfuse_from_config(langfuse or LangfuseConfig())
    if langfuse_addon is not None:
        addons.append(langfuse_addon)
    jev_addon = jev_from_config(
        evaluation or EvaluationConfig(),
        plan_store=plan_store,
        plan_mode=plan_mode,
    )
    if jev_addon is not None:
        addons.append(jev_addon)
    if learning is not None:
        addons.append(LearningAddon(learning, should_review=should_review))
    return addons


__all__ = ["default_addons"]
