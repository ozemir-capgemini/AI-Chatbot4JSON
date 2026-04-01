"""Step 2 – Optionally edit the general / system prompt."""

from bot.engine import BaseStep
from bot.state import BotState
from bot.utils import ask, confirm

DEFAULT_GENERAL_PROMPT = (
    "You are a helpful assistant that converts natural-language questions "
    "into SQL queries for the {domain} domain."
)


class GeneralPromptStep(BaseStep):
    name = "General Prompt"

    def run(self, state: BotState) -> BotState:
        current = state.general_prompt or DEFAULT_GENERAL_PROMPT.format(
            domain=state.domain
        )
        print(f"\nCurrent general prompt:\n  \"{current}\"")

        while True:
            wants_change = ask("Do you want to change the general prompt? (y/n)")
            if wants_change.lower() not in ("y", "yes"):
                state.general_prompt = current
                return state

            new_prompt = ask("Enter the new general prompt:")
            if confirm(f"Confirm new prompt:\n  \"{new_prompt}\""):
                state.general_prompt = new_prompt
                return state
            print("Let's try again.")
