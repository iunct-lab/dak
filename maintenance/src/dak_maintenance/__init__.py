"""dak-maintenance: DAK self-maintenance toolkit.

Public API mirrors the plan's tiered engine:
  Tier 0 (deterministic): classify_update, decide
  Tier 1/2 (LLM/heuristic): assess_risk
"""

from .semver import BumpLevel, classify_update
from .risk import RiskLevel, RiskVerdict, assess_risk, HeuristicAssessor, LLMAssessor
from .decide import Action, Decision, decide
from .proposals import Proposal, dedupe
from .watch import propose_technologies
from .feature import propose_feature_adoptions
from .charter import review_charter

__all__ = [
    "BumpLevel",
    "classify_update",
    "RiskLevel",
    "RiskVerdict",
    "assess_risk",
    "HeuristicAssessor",
    "LLMAssessor",
    "Action",
    "Decision",
    "decide",
    "Proposal",
    "dedupe",
    "propose_technologies",
    "propose_feature_adoptions",
    "review_charter",
]
