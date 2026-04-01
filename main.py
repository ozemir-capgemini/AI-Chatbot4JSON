"""AI Chatbot4JSON – Single-page application entry point.

Walks the user through a guided wizard that builds a text-to-SQL
configuration and exports it as a JSON file.
"""

from bot.state import BotState
from bot.engine import StepRunner
from bot.steps import ALL_STEPS
from bot.utils import ask, confirm, display_section

OUTPUT_FILE = "output.json"


def main() -> None:
    display_section("AI Chatbot4JSON", "Configure your text-to-SQL bot step by step.\n")

    # Resume from existing JSON if present
    state = BotState.load(OUTPUT_FILE)
    if state.domain:
        print(f"Found existing config for domain '{state.domain}'.")
        if not confirm("Resume and overwrite with new answers?"):
            state = BotState()

    runner = StepRunner(ALL_STEPS)
    state = runner.run_all(state)

    # Final save
    path = state.save(OUTPUT_FILE)
    display_section("Done!", f"Configuration saved to {path}")
    print(state.to_dict())


if __name__ == "__main__":
    main()
