"""
base.py — Base Domain Simulator Interface
=========================================
Hermetic action-effect simulator evaluating candidate agent actions against
canonical initial state E0 and tracking state transition E0 -> E1.
"""

from __future__ import annotations

import copy
import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any
from research_harness.decision_fidelity.models import ActionOutcome, DownstreamTask, SimulationResult


class BaseDomainSimulator(ABC):
    """Abstract base class for domain action simulators."""

    def __init__(self, name: str, initial_state: dict[str, Any]):
        self.name = name
        self.initial_state = initial_state
        self.state = copy.deepcopy(initial_state)

    def reset(self):
        """Resets the simulator state back to initial_state."""
        self.state = copy.deepcopy(self.initial_state)

    def state_hash(self) -> str:
        """Computes SHA-256 hash of the current state."""
        return hashlib.sha256(json.dumps(self.state, sort_keys=True).encode("utf-8")).hexdigest()

    @abstractmethod
    def execute(self, action: dict[str, Any], task: DownstreamTask, gold_action: dict[str, Any], valid_alternatives: list[dict[str, Any]]) -> SimulationResult:
        """
        Executes action, checks pre/post conditions, and evaluates outcome.
        """
        pass
