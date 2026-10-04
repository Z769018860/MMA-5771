"""Glue between a real game connection and the Engine.

Implement GameAdapter for MaaFramework (screenshot -> Observation, Action -> clicks) and call run().
"""

from abc import ABC, abstractmethod

from .contract import Action, Do, Observation
from .engine import Engine


class GameAdapter(ABC):
    @abstractmethod
    def observe(self) -> Observation:
        """Capture the screen and classify it. Text fields may be None when OCR is unavailable."""

    @abstractmethod
    def perform(self, action: Action) -> None:
        """Execute one action (tap, wait, back, ...)."""


def run(adapter: GameAdapter, engine: Engine, max_actions=5000, on_step=None):
    """Drive the game until the engine stops. Returns the final STOP action ('completed' = objective reached)."""
    last = None
    for _ in range(max_actions):
        action = engine.step(adapter.observe())
        last = action
        if on_step:
            on_step(action)
        if action.kind == Do.STOP:
            return action
        adapter.perform(action)
    return last or Action(Do.STOP, "budget", "max_actions reached")
