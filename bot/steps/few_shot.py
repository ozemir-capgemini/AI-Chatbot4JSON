"""Step 6 – Collect few-shot examples (input Q → query SQL)."""

from bot.engine import BaseStep
from bot.state import BotState, FewShotExample
from bot.utils import ask, confirm


class FewShotStep(BaseStep):
    name = "Few-Shot Examples"

    def run(self, state: BotState) -> BotState:
        print("\nProvide few-shot examples.  Format: a natural-language question → SQL query.")
        print("Type 'done' when finished.\n")

        if state.few_shot_examples:
            print("Existing examples:")
            for i, ex in enumerate(state.few_shot_examples, 1):
                print(f"  {i}. input{{  {ex.input}  }} -> query{{  {ex.query}  }}")
            print()

        while True:
            question = ask("Question (or 'done' to finish):")
            if question.lower() == "done":
                return state

            sql = ask("SQL query for that question:")
            preview = f"input{{ {question} }} -> query{{ {sql} }}"
            print(f"\n  {preview}")

            if confirm("Is this example correct and consistent?"):
                state.few_shot_examples.append(
                    FewShotExample(input=question, query=sql)
                )
                print("Example added.")
            else:
                print("Discarded. Try again.")
