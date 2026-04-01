"""Step 3 – Add or edit table definitions (DDL + context/description)."""

from bot.engine import BaseStep
from bot.state import BotState, TableInfo
from bot.utils import ask, ask_choice, confirm, display_section


class TableStep(BaseStep):
    name = "Table Definitions"

    def run(self, state: BotState) -> BotState:
        while True:
            self._show_tables(state)
            action = ask_choice(
                "What would you like to do?",
                ["new table", "edit table", "done"],
            )

            if action == "done":
                return state
            elif action == "new table":
                self._add_table(state)
            elif action == "edit table":
                if not state.tables:
                    print("No tables to edit yet. Add one first.")
                    continue
                self._edit_table(state)

    def _show_tables(self, state: BotState) -> None:
        if not state.tables:
            print("\nNo tables defined yet.")
            return
        print("\nCurrent tables:")
        for i, t in enumerate(state.tables, 1):
            print(f"  {i}. {t.name}")

    def _add_table(self, state: BotState) -> None:
        while True:
            name = ask("Table name:")
            ddl = ask("Enter the DDL (CREATE TABLE statement):")
            context = ask("Additional context / notes about this table:")
            description = f"Table: {name}\nDDL:\n{ddl}\nContext: {context}"

            display_section("Generated Table Description", description)

            if confirm("Does this description look good?"):
                state.tables.append(
                    TableInfo(name=name, ddl=ddl, context=context, description=description)
                )
                print(f"Table '{name}' added.")
                return
            print("Let's redo this table.")

    def _edit_table(self, state: BotState) -> None:
        self._show_tables(state)
        idx_str = ask("Which table number to edit?")
        if not idx_str.isdigit() or not (1 <= int(idx_str) <= len(state.tables)):
            print("Invalid selection.")
            return
        idx = int(idx_str) - 1
        table = state.tables[idx]

        while True:
            print(f"\nEditing table: {table.name}")
            name = ask(f"Table name [{table.name}]:") or table.name
            ddl = ask(f"DDL [{table.ddl[:40]}...]:") or table.ddl
            context = ask(f"Context [{table.context[:40]}...]:") or table.context
            description = f"Table: {name}\nDDL:\n{ddl}\nContext: {context}"

            display_section("Updated Table Description", description)

            if confirm("Confirm these changes?"):
                state.tables[idx] = TableInfo(
                    name=name, ddl=ddl, context=context, description=description
                )
                print(f"Table '{name}' updated.")
                return
            print("Let's redo the edit.")
