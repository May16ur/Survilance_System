"""Interactive stress test for military/civil plate classification rules.

Run:
    python test/test_mil_plate.py

Commands inside the prompt:
    run       - execute built-in stress cases
    file PATH - test one plate per line from a text file
    quit      - exit

Any other input is tested as a plate string. Comma-separated input is also
supported, for example:
    24B141317E,124B141317E,24B141317E1,LA02A7555
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.common import (  # noqa: E402
    class_from_license_rule,
    classify_vehicle_from_anpr,
    correct_plate_with_master_or_military_format,
    is_valid_license_text,
    military_plate_from_partial,
    normalize_match_license,
    normalize_plate_for_storage,
)


CASES = [
    "24B141317E",
    "124B141317E",
    "24B141317E1",
    "124B141317E1",
    "14C00HM",
    "14C0HM",
    "19B131092M",
    "119B131092M",
    "19B131092M1",
    "2D189806Y",
    "12D189806Y",
    "2D189806Y1",
    "LA02A7555",
    "UP14C00HM",
    "MH25B1453W",
    "JK14C00HM",
    "1LA02A7555",
    "LA02A75551",
    "JK10A3931",
    "MH01EJ8131",
    "UNKNOWN",
    "",
]


def result_for(plate: str) -> dict:
    stored = normalize_plate_for_storage(plate)
    corrected, correction_reason, correction_score = correct_plate_with_master_or_military_format(plate)
    match_key = normalize_match_license(plate)
    rule_class = class_from_license_rule(stored or plate)
    anpr_class = classify_vehicle_from_anpr(plate)
    return {
        "input": plate,
        "stored": stored or "UNKNOWN",
        "corrected": corrected or "UNKNOWN",
        "mil_fallback": military_plate_from_partial(plate) or "",
        "correction": correction_reason,
        "score": correction_score,
        "match_key": match_key or "NO_MATCH",
        "valid": is_valid_license_text(plate),
        "rule_class": rule_class[1] if rule_class[1] else "Unknown Veh",
        "anpr_class": anpr_class[1],
        "reason": anpr_class[2],
    }


def print_rows(plates):
    rows = [result_for(str(plate).strip()) for plate in plates]
    headers = ["input", "stored", "corrected", "mil_fallback", "correction", "score", "match_key", "valid", "rule_class", "anpr_class", "reason"]
    widths = {header: max(len(header), *(len(str(row[header])) for row in rows)) for header in headers}
    print(" | ".join(header.ljust(widths[header]) for header in headers))
    print("-+-".join("-" * widths[header] for header in headers))
    for row in rows:
        print(" | ".join(str(row[header]).ljust(widths[header]) for header in headers))


def plates_from_text(text: str):
    return [part.strip() for part in text.split(",") if part.strip()]


def main() -> int:
    print("Military plate rule stress tester. Type 'run', 'file PATH', a plate, comma-separated plates, or 'quit'.")
    while True:
        try:
            value = input("plate> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not value:
            continue
        if value.lower() in {"quit", "exit", "q"}:
            return 0
        if value.lower() == "run":
            print_rows(CASES)
            continue
        if value.lower().startswith("file "):
            path = Path(value[5:].strip().strip('"'))
            if not path.is_absolute():
                path = ROOT / path
            if not path.exists():
                print(f"File not found: {path}")
                continue
            print_rows([line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
            continue

        print_rows(plates_from_text(value))


if __name__ == "__main__":
    raise SystemExit(main())
