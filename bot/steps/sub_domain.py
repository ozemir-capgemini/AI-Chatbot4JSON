"""Step 4 – Choose which sub-domain to target."""

from bot.engine import BaseStep
from bot.state import BotState
from bot.utils import ask, confirm


class SubDomainStep(BaseStep):
    name = "Select Sub-Domain"

    def run(self, state: BotState) -> BotState:
        while True:
            sub = ask(
                f"Which sub-domain under '{state.domain}' should this target?\n"
                "(e.g., 'returns', 'order tracking', 'revenue reporting')"
            )
            if confirm(f"Confirm sub-domain: '{sub}'?"):
                state.sub_domain = sub
                return state
            print("Let's try again.")
