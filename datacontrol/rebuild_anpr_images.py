"""Rebuild ANPR image files from saved received JSON payloads.

Run manually when old received JSON has base64 image data but the UI shows
"No image" because the static image files or parsed image paths are missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
RECEIVED = BACKEND / "received"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.common import _get_connection  # noqa: E402
from flask_app.services.cp_plus import decode_event_images, image_content_status, normalize_event  # noqa: E402


def sync_db_images(event: dict, parsed: dict) -> int:
    if not parsed.get("veh_img") and not parsed.get("license_img"):
        return 0

    db_id = ((event.get("db_result") or {}).get("id")) or parsed.get("id")
    params = [
        parsed.get("veh_img", ""),
        parsed.get("veh_img", ""),
        parsed.get("veh_img", ""),
        parsed.get("veh_img", ""),
        parsed.get("license_img", ""),
        parsed.get("license_img", ""),
        parsed.get("license_img", ""),
        parsed.get("license_img", ""),
    ]

    where_sql = ""
    where_params = []
    if db_id:
        where_sql = "id = %s"
        where_params = [int(db_id)]
    else:
        where_sql = """
            camera_name = %s
            AND track_id = %s
            AND license = %s
            AND ABS(TIMESTAMPDIFF(SECOND, time, %s)) <= 2
        """
        where_params = [
            parsed.get("camera_name", ""),
            int(parsed.get("track_id") or 0),
            parsed.get("license", "UNKNOWN"),
            parsed.get("time"),
        ]

    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE vehicle_logs
        SET
            vehicle_img = CASE WHEN (vehicle_img IS NULL OR vehicle_img = '') AND %s <> '' THEN %s ELSE vehicle_img END,
            veh_img = CASE WHEN (veh_img IS NULL OR veh_img = '') AND %s <> '' THEN %s ELSE veh_img END,
            plate_img = CASE WHEN (plate_img IS NULL OR plate_img = '') AND %s <> '' THEN %s ELSE plate_img END,
            license_img = CASE WHEN (license_img IS NULL OR license_img = '') AND %s <> '' THEN %s ELSE license_img END
        WHERE {where_sql}
        """,
        tuple(params + where_params),
    )
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return updated


def rebuild_file(path: Path, write: bool, sync_db: bool) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        event = json.load(handle)

    timestamp = path.name.replace("_event.json", "")
    data = event.get("data") or {}
    parsed = event.get("parsed") or normalize_event(data, event_file=path.name)

    veh_img, license_img, _ = decode_event_images(data, timestamp)
    parsed["veh_img"] = veh_img or parsed.get("veh_img", "")
    parsed["vehicle"] = parsed["veh_img"]
    parsed["license_img"] = license_img or parsed.get("license_img", "")
    parsed["plate"] = parsed["license_img"]
    parsed["image_sources"] = image_content_status(data)
    if not parsed["veh_img"]:
        parsed["vehicle_image_missing_reason"] = "No vehicle image content found in received JSON"
    if not parsed["license_img"]:
        parsed["plate_image_missing_reason"] = "No plate image content found in received JSON"

    event["parsed"] = parsed
    db_updated = 0
    if sync_db and write:
        db_updated = sync_db_images(event, parsed)

    if write:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(event, handle, indent=4, ensure_ascii=False)

    return {
        "file": path.name,
        "vehicle": parsed["veh_img"] or "missing",
        "plate": parsed["license_img"] or "missing",
        "vehicle_sources": parsed["image_sources"]["vehicle_sources"],
        "plate_sources": parsed["image_sources"]["plate_sources"],
        "db_updated": db_updated,
        "written": write,
    }


def iter_files(pattern: str):
    if pattern.endswith(".json"):
        candidate = RECEIVED / pattern
        if candidate.exists():
            yield candidate
        return
    yield from sorted(RECEIVED.glob(pattern))


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild /static/anpr images from received JSON files.")
    parser.add_argument("pattern", nargs="?", default="*_event.json", help="File name or glob inside backend/received")
    parser.add_argument("--dry-run", action="store_true", help="Decode and report without updating JSON")
    parser.add_argument("--no-db", action="store_true", help="Do not sync recovered image paths into MySQL vehicle_logs")
    args = parser.parse_args()

    files = list(iter_files(args.pattern))
    if not files:
        print(f"No matching files in {RECEIVED}: {args.pattern}")
        return 1

    for path in files:
        try:
            print(json.dumps(rebuild_file(path, write=not args.dry_run, sync_db=not args.no_db), ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"file": path.name, "error": str(exc)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
