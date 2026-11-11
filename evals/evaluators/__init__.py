"""Code-based evaluators for the triage agent.

These are deliberately deterministic: no model acts as judge, so a gate
result is reproducible and a failure is explainable to a customer. The
LLM-judge and safety evaluators from the Microsoft Foundry evaluation SDK are
layered on top when a project endpoint is configured -- see
evals/cloud_evaluators.py.
"""
from .routing import RoutingCorrectnessEvaluator
from .priority import PriorityAccuracyEvaluator
from .output_contract import OutputContractEvaluator

__all__ = [
    "RoutingCorrectnessEvaluator",
    "PriorityAccuracyEvaluator",
    "OutputContractEvaluator",
]
