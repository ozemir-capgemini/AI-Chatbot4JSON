"""Step 1 – Choose the domain (sales, inventory, account)."""

from bot.engine import BaseStep
from bot.state import BotState
from bot.utils import ask_choice, confirm

DOMAINS = ["sales", "inventory", "account"]


class DomainStep(BaseStep):
    name = "Select Domain"

    def run(self, state: BotState) -> BotState:
        while True:
            domain = ask_choice("Which domain is this bot for?", DOMAINS)
            if confirm(f"Confirm domain: '{domain}'?"):
                state.domain = domain
                return state
            print("Let's try again.")
