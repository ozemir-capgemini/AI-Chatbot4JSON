"""DMACO – CLI chat entry point.

Terminal-based chat interface that mirrors the Streamlit app.
Run with: python main.py
"""

from dotenv import load_dotenv
from bot.state import BotMemory, FSMState
from bot.engine import process_user_input

load_dotenv()


def main() -> None:
    memory = BotMemory()
    state = FSMState.INIT

    # Kick off with the INIT greeting
    reply, state = process_user_input(state, memory, "")
    print(f"\n🤖  {reply}")

    while state != FSMState.COMPLETE:
        user_input = input("\nYou> ").strip()
        if not user_input:
            continue

        reply, state = process_user_input(state, memory, user_input)
        print(f"\n🤖  {reply}")

        # Auto-trigger final assembly (no user input needed)
        if state == FSMState.FINAL_ASSEMBLY:
            reply, state = process_user_input(state, memory, "")
            print(f"\n🤖  {reply}")

    print("\nSession complete.")


if __name__ == "__main__":
    main()
