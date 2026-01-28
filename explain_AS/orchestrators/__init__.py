from __future__ import annotations

from typing import Dict, Type

from .base import OrchestratorBase
from .orch_v1_four_agents import OrchestratorV1FourAgents
from .orch_v2_two_stage import OrchestratorV2TwoStage

ORCHESTRATORS: Dict[str, Type[OrchestratorBase]] = {
    "v1_four_agents": OrchestratorV1FourAgents,
    "v2_two_stage": OrchestratorV2TwoStage,
    # add more here, e.g. "v3_cycle_first": OrchestratorV3CycleFirst
}
