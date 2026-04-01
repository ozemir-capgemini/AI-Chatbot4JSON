"""Step 5 – Optionally add/edit sub-domain-level prompt."""

from bot.engine import BaseStep
from bot.state import BotState
from bot.utils import ask, confirm


class SubDomainPromptStep(BaseStep):
    name = "Sub-Domain Prompt"

    def run(self, state: BotState) -> BotState:
        current = state.sub_domain_prompt or ""
        if current:
            print(f"\nCurrent sub-domain prompt:\n  \"{current}\"")
        else:
            print("\nNo sub-domain prompt set yet.")

        while True:
            wants_change = ask("Do you want to add/change the sub-domain prompt? (y/n)")
            if wants_change.lower() not in ("y", "yes"):
                return state

            new_prompt = ask("Enter the sub-domain prompt:")
            if confirm(f"Confirm sub-domain prompt:\n  \"{new_prompt}\""):
                state.sub_domain_prompt = new_prompt
                return state
            print("Let's try again.")
