"""Initialize EPIOT offline from the compact country snapshots.

For supplier refreshes use scripts/update_charger_data.py after initialization.
"""
from scripts.bootstrap_database import main


if __name__ == "__main__":
    main()
