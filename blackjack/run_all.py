"""
One-command runner: rebuilds the DB schema, then runs all test files.

Run from the project root:
    python -m blackjack.run_all                 # rebuild schema + run ALL tests (db, deck, game)
    python -m blackjack.run_all schema          # only rebuild DB schema
    python -m blackjack.run_all tests           # run ALL tests, in folder order
    python -m blackjack.run_all tests db        # run only the db folder tests
    python -m blackjack.run_all tests deck      # run only the deck folder tests
    python -m blackjack.run_all tests game      # run only the game folder tests
"""

import subprocess
import sys

# Windows consoles default to cp1252, which can't print some characters (e.g. the
# checkmark below). Force UTF-8 so output never crashes on encoding.
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Run order matters:
#  - card_schema.py has a FK into the blackjack table, so blackjack must exist first.
#  - schema files DROP/recreate tables, so they must run before the tests.
SCHEMA_FILES = [
    "blackjack.db.blackjack_schema",
    "blackjack.db.card_schema",
]

# Tests grouped by folder. FOLDER_ORDER controls the sequence when running all:
# db tests first, then deck, then game.
FOLDER_ORDER = ["db", "deck", "game"]

TEST_FILES_BY_FOLDER = {
    "db": [
        "blackjack.db.test_card_data_access",
        "blackjack.db.test_blackjack_data_access",
    ],
    "deck": [
        "blackjack.deck.test_deck",
    ],
    "game": [
        "blackjack.game.test_blackjack_utils",
    ],
}


def run(module: str) -> bool:
    """Run a module via `python -m <module>`. Returns True if it succeeded."""
    print(f"\n[run] python -m {module}")
    print("-" * 60)
    result = subprocess.run([sys.executable, "-m", module])
    print("-" * 60)
    return result.returncode == 0


def collect_tests(target_folder=None):
    """Flatten the test list in folder order, optionally limited to one folder."""
    folders = [target_folder] if target_folder else FOLDER_ORDER
    unknown = [f for f in folders if f not in TEST_FILES_BY_FOLDER]
    if unknown:
        print(f"Unknown folder(s): {', '.join(unknown)}")
        print(f"Known folders: {', '.join(FOLDER_ORDER)}")
        sys.exit(2)
    steps = []
    for folder in folders:
        steps += [(name, folder) for name in TEST_FILES_BY_FOLDER[folder]]
    return steps


def main():
    args = sys.argv[1:]
    target = args[0] if args else "all"

    if target not in ("all", "schema", "tests"):
        print(f"Unknown target: {target!r}. Use: all | schema | tests [folder]")
        sys.exit(2)

    steps = []
    if target in ("all", "schema"):
        steps += [(name, "schema") for name in SCHEMA_FILES]
    if target in ("all", "tests"):
        folder = args[1] if len(args) > 1 else None
        steps += collect_tests(folder)

    if not steps:
        print("Nothing to run.")
        return

    print("=" * 60)
    where = "all folders" if (target == "tests" and len(args) <= 1) else (args[1] if len(args) > 1 else target)
    print(f"Running {len(steps)} step(s): {where}")
    print("=" * 60)

    failed = []
    for module, kind in steps:
        ok = run(module)
        if not ok:
            failed.append(module)
            print(f"\n[x] FAILED: {module}")
            print("Stopping — fix this before continuing.")
            break

    print("\n" + "=" * 60)
    if failed:
        print(f"DONE with errors: {', '.join(failed)}")
        sys.exit(1)
    else:
        print(f"All {len(steps)} step(s) passed ✓")


if __name__ == "__main__":
    main()
