"""Shared helpers for user interaction (confirmation, input, display)."""


def ask(prompt: str) -> str:
    """Get free-text input from the user."""
    return input(f"\n{prompt}\n> ").strip()


def ask_choice(prompt: str, choices: list[str]) -> str:
    """Present numbered choices and return the selected value."""
    print(f"\n{prompt}")
    for i, c in enumerate(choices, 1):
        print(f"  {i}. {c}")
    while True:
        raw = input("> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        # Also allow typing the value directly
        if raw.lower() in [c.lower() for c in choices]:
            return next(c for c in choices if c.lower() == raw.lower())
        print(f"Please enter a number 1-{len(choices)} or type one of: {', '.join(choices)}")


def confirm(message: str) -> bool:
    """Ask a yes/no confirmation. Returns True on 'y'."""
    resp = input(f"\n{message} (y/n): ").strip().lower()
    return resp in ("y", "yes")


def display_section(title: str, body: str) -> None:
    """Pretty-print a section header + body."""
    width = max(len(title) + 4, 40)
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")
    if body:
        print(body)
