import base64
import datetime
import json
import os
import re

import cv2
import numpy as np
from flask import request

from core.common import (
    CAMERA_NAME_MAP,
    classify_vehicle_from_anpr,
    ensure_database,
    ensure_table,
    get_vehicle_master_info,
    insert_vehicle_log_event,
)
from project_config import get_cp_plus_camera_map


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANPR_IMAGE_FOLDER = os.path.join(BASE_DIR, "flask_app", "static", "anpr")
os.makedirs(ANPR_IMAGE_FOLDER, exist_ok=True)

def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def event_track_id():
    # CP Plus UploadNum/LanNo is often just lane/request number, not a vehicle track id.
    # Use a per-event id so ANPR saves one DB row per camera event.
    return int(datetime.datetime.now().timestamp() * 1000) % 2000000000


def camera_from_event(data):
    """Resolve CP Plus event to a camera id/name.

    Optional env mapping:
    CP_PLUS_CAMERA_MAP='{"device-id": 3, "192.168.1.110": 3}'
    """
    picture = (data or {}).get("Picture") or {}
    snap = picture.get("SnapInfo") or {}
    plate = picture.get("Plate") or {}

    mapping = get_cp_plus_camera_map()
    mapping_raw = os.getenv("CP_PLUS_CAMERA_MAP", "").strip()
    if mapping_raw:
        try:
            mapping.update(json.loads(mapping_raw))
        except Exception:
            pass

    keys = [
        str(snap.get("DeviceID") or ""),
        str(request.remote_addr or ""),
        str(snap.get("LanNo") or ""),
        str(plate.get("Channel") or ""),
    ]
    for key in keys:
        if key and key in mapping:
            camera_id = safe_int(mapping[key], 1)
            return camera_id, CAMERA_NAME_MAP.get(camera_id, f"CP Plus Camera {camera_id}")

    camera_id = safe_int(request.args.get("camera_id") or (data or {}).get("camera_id"), 1)
    if camera_id not in CAMERA_NAME_MAP:
        camera_id = 1
    return camera_id, CAMERA_NAME_MAP.get(camera_id, f"CP Plus Camera {camera_id}")


def _jpeg_start_positions(image_bytes):
    positions = []
    start = 0
    while True:
        pos = image_bytes.find(b"\xff\xd8", start)
        if pos < 0:
            break
        positions.append(pos)
        start = pos + 2
    return positions


def decode_event_images(data, timestamp):
    """Decode vehicle/plate images from CP Plus base64 content.

    CP Plus may concatenate two JPEGs in VehiclePic.Content:
    first = vehicle image, second = clean plate crop.
    """
    date_folder = datetime.datetime.now().strftime("%Y%m%d")
    image_dir = os.path.join(ANPR_IMAGE_FOLDER, date_folder)
    os.makedirs(image_dir, exist_ok=True)

    picture = (data or {}).get("Picture") or {}
    vehicle_content = (
        (picture.get("VehiclePic") or {}).get("Content")
        or (picture.get("NormalPic") or {}).get("Content")
        or ""
    )
    plate_content = (picture.get("CutoutPic") or {}).get("Content") or ""
    if not vehicle_content and not plate_content:
        return "", "", None

    vehicle_bytes = _decode_base64_image(vehicle_content)
    plate_bytes = _decode_base64_image(plate_content)
    image_bytes = vehicle_bytes or plate_bytes

    vehicle_rel = ""
    if vehicle_bytes:
        starts = _jpeg_start_positions(vehicle_bytes)
        clean_vehicle_bytes = vehicle_bytes[starts[0]:] if starts else vehicle_bytes
        vehicle_filename = f"{timestamp}_vehicle.jpg"
        with open(os.path.join(image_dir, vehicle_filename), "wb") as image_file:
            image_file.write(clean_vehicle_bytes)
        vehicle_rel = f"/static/anpr/{date_folder}/{vehicle_filename}"

        if len(starts) > 1 and not plate_bytes:
            plate_bytes = vehicle_bytes[starts[1]:]

    if plate_bytes:
        plate_filename = f"{timestamp}_plate.jpg"
        with open(os.path.join(image_dir, plate_filename), "wb") as plate_file:
            plate_file.write(plate_bytes)
        return vehicle_rel, f"/static/anpr/{date_folder}/{plate_filename}", image_bytes

    return vehicle_rel, _crop_plate_from_box(data, image_bytes, image_dir, date_folder, timestamp), image_bytes


def _decode_base64_image(content):
    if not content:
        return None
    if "," in content[:80]:
        content = content.split(",", 1)[1]
    try:
        return base64.b64decode(content, validate=False)
    except Exception:
        return None


def _crop_plate_from_box(data, image_bytes, image_dir, date_folder, timestamp):
    """Fallback only: crop using the camera bounding box if no embedded plate JPEG exists."""
    try:
        frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        plate_box = (((data or {}).get("Picture") or {}).get("Plate") or {}).get("BoundingBox") or []
        if frame is None or len(plate_box) != 4:
            return ""

        x1, y1, x2, y2 = [safe_int(v) for v in plate_box]
        h, w = frame.shape[:2]
        x1, x2 = max(0, min(x1, w - 1)), max(0, min(x2, w))
        y1, y2 = max(0, min(y1, h - 1)), max(0, min(y2, h))
        if x2 <= x1 or y2 <= y1:
            return ""

        plate_filename = f"{timestamp}_plate.jpg"
        if cv2.imwrite(os.path.join(image_dir, plate_filename), frame[y1:y2, x1:x2]):
            return f"/static/anpr/{date_folder}/{plate_filename}"
    except Exception as e:
        print("[CP PLUS] Plate crop skipped:", e)
    return ""


def normalize_event(data, event_file=None):
    """Convert a raw CP Plus payload to the row shape used by DB and React."""
    picture = (data or {}).get("Picture") or {}
    plate = picture.get("Plate") or {}
    vehicle = picture.get("Vehicle") or {}
    snap = picture.get("SnapInfo") or {}
    normal_pic = picture.get("NormalPic") or {}
    cutout_pic = picture.get("CutoutPic") or {}
    camera_id, camera_name = camera_from_event(data or {})

    plate_number = str(
        plate.get("PlateNumber")
        or _find_text_in_picture_headers(picture, ["UnRecognise", "Unknown"])
        or ""
    ).strip().upper()
    snap_time = snap.get("SnapTime") or snap.get("AccurateTime") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    class_id, class_name, class_reason = classify_vehicle_from_anpr(
        plate_number,
        plate_color=plate.get("PlateColor") or "",
        plate_type=plate.get("PlateType") or "",
        vehicle_type=vehicle.get("VehicleType") or "",
    )

    master = get_vehicle_master_info(plate_number) if plate_number else None

    return {
        "event_file": event_file or "",
        "source_type": "cp_plus_anpr",
        "camera_id": camera_id,
        "camera_name": camera_name,
        "track_id": event_track_id(),
        "license": plate_number or "UNKNOWN",
        "plate_number": plate_number,
        "plate_confidence": plate.get("Confidence"),
        "plate_color": plate.get("PlateColor") or "",
        "plate_type": plate.get("PlateType") or "",
        "vehicle_type": vehicle.get("VehicleType") or "",
        "vehicle_type_master": (master or {}).get("vehicle_type", ""),
        "unit": (master or {}).get("unit", ""),
        "driver_name": (master or {}).get("driver_name", ""),
        "make_model": (master or {}).get("make_model", ""),
        "vehicle_remarks": (master or {}).get("remarks", ""),
        "vehicle_master_match": bool(master),
        "vehicle_color": vehicle.get("VehicleColor") or "",
        "speed": f"{vehicle.get('Speed', 0)} km/h",
        "raw_speed": vehicle.get("Speed", 0),
        "time": snap_time,
        "class_id": class_id,
        "class_name": class_name,
        "classification_reason": class_reason,
        "device_id": snap.get("DeviceID") or "",
        "lane": snap.get("LanNo"),
        "channel": plate.get("Channel"),
        "normal_pic_name": normal_pic.get("PicName") or "",
        "cutout_pic_name": cutout_pic.get("PicName") or "",
        "direction": "South to North",
        "license_img": "",
        "veh_img": "",
        "is_detection_event": bool(picture),
    }


def _find_text_in_picture_headers(picture, ignored_values):
    """Some CP Plus payloads place text in the binary-like image header, not Plate."""
    ignored = {str(value).upper() for value in ignored_values}
    for key in ("NormalPic", "CutoutPic"):
        content = str(((picture or {}).get(key) or {}).get("Content") or "")
        for match in re.findall(r"[A-Z]{1,3}[0-9]{1,4}[A-Z]{0,3}[0-9]{0,4}", content.upper()):
            if match not in ignored and len(match) >= 5:
                return match
    return ""


def store_event_in_db(normalized):
    """Persist a parsed CP Plus event into the shared vehicle log table."""
    if not normalized.get("is_detection_event"):
        return {"success": True, "skipped": True, "message": "No vehicle/plate detection data in payload"}

    try:
        ensure_database()
        ensure_table()
        result = insert_vehicle_log_event(
            track_id=normalized["track_id"],
            class_name=normalized["class_name"],
            avg_speed=normalized["speed"],
            license_text=normalized["license"],
            time_value=normalized["time"],
            class_id=normalized["class_id"],
            camera_name=normalized["camera_name"],
            source_type="cp_plus_anpr",
            license_img=normalized.get("license_img", ""),
            veh_img=normalized.get("veh_img", ""),
        )
        return result
    except Exception as e:
        print("[CP PLUS] DB insert skipped:", e)
        return {"success": False, "message": str(e)}
