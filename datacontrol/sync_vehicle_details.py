import argparse
import os
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from env_loader import load_project_env

load_project_env()

from core.common import (
    VEH_DETAILS_PATH,
    check_mysql_connection,
    ensure_database,
    ensure_table,
    import_vehicle_details_from_excel,
)


def main():
    parser = argparse.ArgumentParser(
        description="Manually sync VEH DETAILS.xlsx entries into MySQL vehicle_master."
    )
    parser.add_argument(
        "--path",
        default=None,
        help="Optional Excel path. Defaults to VEH_DETAILS_PATH from .env or project VEH DETAILS.xlsx.",
    )
    parser.add_argument(
        "--skip-schema-check",
        action="store_true",
        help="Skip database/table creation checks before import.",
    )
    args = parser.parse_args()

    excel_path = args.path or VEH_DETAILS_PATH
    print(f"[DATA SYNC] Excel: {excel_path}")

    mysql = check_mysql_connection(log=True)
    if not mysql.get("connected"):
        print("[DATA SYNC] MySQL is not connected. Fix .env MySQL settings and try again.")
        return 1

    if not args.skip_schema_check:
        if not ensure_database():
            print("[DATA SYNC] Database setup failed.")
            return 1
        if not ensure_table():
            print("[DATA SYNC] Table setup failed.")
            return 1

    result = import_vehicle_details_from_excel(excel_path)
    print(f"[DATA SYNC] {result.get('message')}")
    print(f"[DATA SYNC] imported={result.get('imported', 0)} skipped={result.get('skipped', 0)}")
    if result.get("path"):
        print(f"[DATA SYNC] path={result.get('path')}")

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
