"""Step runner – walks through an ordered list of steps, managing state."""

from __future__ import annotations
from abc import ABC, abstractmethod
from bot.state import BotState
from bot.utils import display_section


class BaseStep(ABC):
    """Every step must implement these two hooks."""

    name: str = "Unnamed Step"

    @abstractmethod
    def run(self, state: BotState) -> BotState:
        """Execute the step, mutate state, return it.

        The step is responsible for:
          - collecting user input
          - confirming changes
          - appending confirmed data to state
        If the user declines confirmation, the step should retry or skip.
        """
        ...


class StepRunner:
    """Sequentially executes a list of step *classes*."""

    def __init__(self, step_classes: list[type[BaseStep]]):
        self.step_classes = step_classes

    def run_all(self, state: BotState | None = None) -> BotState:
        state = state or BotState()

        for i, cls in enumerate(self.step_classes, 1):
            step = cls()
            display_section(
                f"Step {i}/{len(self.step_classes)}: {step.name}", ""
            )
            state = step.run(state)

        return state
