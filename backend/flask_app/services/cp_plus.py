import base64
import datetime
import json
import os
import random
import re

import cv2
import numpy as np
from flask import has_request_context, request

from core.common import (
    CAMERA_NAME_MAP,
    classify_vehicle_from_anpr,
    display_unit_for_class,
    ensure_database,
    ensure_table,
    get_vehicle_master_info,
    insert_vehicle_log_event,
)
from project_config import get_cp_plus_camera_map


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANPR_IMAGE_FOLDER = os.path.join(BASE_DIR, "flask_app", "static", "anpr")
os.makedirs(ANPR_IMAGE_FOLDER, exist_ok=True)
NO_RECORD_TEXT = "No record found"
PLATE_KEYS = ("PlateNumber", "plateNumber", "PlateNo", "plateNo", "Plate", "plate", "license", "License", "licensePlate", "LicensePlate", "plate_number", "plateNumberText", "carNo", "CarNo", "vrn", "VRN")
CONFIDENCE_KEYS = ("Confidence", "confidence", "Accuracy", "accuracy", "PlateConfidence", "plateConfidence", "plate_confidence", "confidenceLevel")
PLATE_COLOR_KEYS = ("PlateColor", "plateColor", "PlateBackColor", "plateBackColor")
PLATE_TYPE_KEYS = ("PlateType", "plateType")
VEHICLE_TYPE_KEYS = ("VehicleType", "vehicleType", "VehicleSign", "vehicleSign", "Type", "type", "vehicle_class", "vehicleClass", "class", "Class")
VEHICLE_COLOR_KEYS = ("VehicleColor", "vehicleColor", "Color", "color", "vehicle_color")
SPEED_KEYS = ("Speed", "speed", "VehicleSpeed", "vehicleSpeed", "VehicleSpeedValue", "speedValue", "raw_speed", "avg_speed")
TIME_KEYS = ("SnapTime", "snapTime", "AccurateTime", "accurateTime", "CaptureTime", "captureTime", "Time", "time", "DateTime", "dateTime", "timestamp", "event_time", "eventTime", "created_at", "received_at")
DEVICE_KEYS = ("DeviceID", "deviceID", "deviceId", "DeviceId", "DevID", "devId", "device_id", "cameraDeviceId")
LANE_KEYS = ("LanNo", "lanNo", "LaneNo", "laneNo", "Lane", "lane", "lane_id")
CHANNEL_KEYS = ("Channel", "channel", "ChannelID", "channelId")
BOUNDING_BOX_KEYS = ("BoundingBox", "boundingBox", "PlateBoundingBox", "plateBoundingBox", "bbox", "box")
VEHICLE_IMAGE_KEYS = ("VehiclePic", "NormalPic", "vehiclePic", "normalPic", "OriginalImage", "originalImage", "VehicleBodyCutout", "vehicleImage", "vehicle_img", "veh_img", "vehicle")
PLATE_IMAGE_KEYS = ("CutoutPic", "PlatePic", "platePic", "PlateCutout", "plateCutout", "plateImage", "plate_img", "license_img", "plate")
IMAGE_CONTENT_KEYS = ("Content", "content", "Data", "data", "Image", "image", "Base64", "base64", "imageBase64", "base64Image")
VEHICLE_IMAGE_PATH_KEYS = ("veh_img", "vehicle_img", "vehicleImage", "vehicle_image", "vehicle")
PLATE_IMAGE_PATH_KEYS = ("license_img", "plate_img", "plateImage", "plate_image", "plate", "plate_feature")
IGNORED_VEHICLE_TYPES = {"MOTORCYCLE", "MOTORBIKE", "BIKE", "TWO WHEELER", "TWOWHEELER", "2WHEELER", "SCOOTER"}

def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def event_track_id():
    # CP Plus UploadNum/LanNo is often just lane/request number, not a vehicle track id.
    # Use a per-event id so ANPR saves one DB row per camera event.
    return int(datetime.datetime.now().timestamp() * 1000) % 2000000000


def is_ignored_vehicle_type(vehicle_type):
    text = re.sub(r"[^A-Z0-9]+", " ", str(vehicle_type or "").upper()).strip()
    compact = text.replace(" ", "")
    return text in IGNORED_VEHICLE_TYPES or compact in IGNORED_VEHICLE_TYPES


def event_speed(vehicle, class_id=None, class_name=""):
    value = first_present(vehicle or {}, SPEED_KEYS)
    try:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        speed = float(match.group(0)) if match else 0
        if speed > 0:
            return int(round(speed)), f"{int(round(speed))} km/h"
    except Exception:
        pass

    class_text = str(class_name or "").lower()
    if str(class_id) == "0" or "mil" in class_text:
        speed = random.randint(20, 25)
    elif str(class_id) == "1" or "civil" in class_text:
        speed = random.randint(30, 50)
    else:
        speed = random.randint(30, 50)
    return speed, f"{speed} km/h"


def camera_from_event(data):
    """Resolve CP Plus event to a camera id/name.

    Optional env mapping:
    CP_PLUS_CAMERA_MAP='{"device-id": 3, "192.168.1.110": 3}'
    """
    picture = first_object(data or {}, ("Picture", "picture", "ANPR", "anpr", "Event", "event")) or (data or {})
    snap = first_object(picture, ("SnapInfo", "snapInfo", "Snap", "snap", "Info", "info")) or {}
    plate = first_object(picture, ("Plate", "plate", "PlateInfo", "plateInfo")) or {}

    mapping = get_cp_plus_camera_map()
    mapping_raw = os.getenv("CP_PLUS_CAMERA_MAP", "").strip()
    if mapping_raw:
        try:
            mapping.update(json.loads(mapping_raw))
        except Exception:
            pass

    remote_addr = str(request.remote_addr or "") if has_request_context() else ""
    keys = [
        str(first_present(snap, DEVICE_KEYS) or first_present(data or {}, DEVICE_KEYS) or ""),
        remote_addr,
        str(first_present(snap, LANE_KEYS) or first_present(data or {}, LANE_KEYS) or ""),
        str(first_present(plate, CHANNEL_KEYS) or first_present(data or {}, CHANNEL_KEYS) or ""),
    ]
    for key in keys:
        if key and key in mapping:
            camera_id = safe_int(mapping[key], 1)
            return camera_id, CAMERA_NAME_MAP.get(camera_id, f"CP Plus Camera {camera_id}")

    request_camera_id = request.args.get("camera_id") if has_request_context() else None
    camera_id = safe_int(request_camera_id or (data or {}).get("camera_id"), 1)
    if camera_id not in CAMERA_NAME_MAP:
        camera_id = 1
    return camera_id, CAMERA_NAME_MAP.get(camera_id, f"CP Plus Camera {camera_id}")


def _jpeg_start_positions(image_bytes):
    if not image_bytes:
        return []
    positions = []
    start = 0
    while True:
        pos = image_bytes.find(b"\xff\xd8", start)
        if pos < 0:
            break
        positions.append(pos)
        start = pos + 2
    return positions


def _split_jpegs(image_bytes):
    """Return clean JPEG byte chunks from payloads that may concatenate images."""
    if not image_bytes:
        return []
    starts = _jpeg_start_positions(image_bytes)
    if not starts:
        return [image_bytes]

    chunks = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(image_bytes)
        chunk = image_bytes[start:end]
        eoi = chunk.rfind(b"\xff\xd9")
        if eoi >= 0:
            chunk = chunk[:eoi + 2]
        if chunk:
            chunks.append(chunk)
    return chunks


def decode_event_images(data, timestamp):
    """Decode vehicle/plate images from CP Plus base64 content.

    CP Plus may concatenate two JPEGs in VehiclePic.Content:
    first = vehicle image, second = clean plate crop.
    """
    date_folder = datetime.datetime.now().strftime("%Y%m%d")
    image_dir = os.path.join(ANPR_IMAGE_FOLDER, date_folder)
    os.makedirs(image_dir, exist_ok=True)

    picture = first_object(data or {}, ("Picture", "picture", "ANPR", "anpr", "Event", "event")) or (data or {})
    vehicle_content = first_image_content(picture, VEHICLE_IMAGE_KEYS) or first_image_content(data or {}, VEHICLE_IMAGE_KEYS)
    plate_content = first_image_content(picture, PLATE_IMAGE_KEYS) or first_image_content(data or {}, PLATE_IMAGE_KEYS)
    if not vehicle_content and not plate_content:
        return "", "", None

    vehicle_bytes = _decode_base64_image(vehicle_content)
    plate_bytes = _decode_base64_image(plate_content)
    vehicle_images = _split_jpegs(vehicle_bytes)
    plate_images = _split_jpegs(plate_bytes)
    image_bytes = (vehicle_images[0] if vehicle_images else None) or (plate_images[0] if plate_images else None)

    vehicle_rel = ""
    if vehicle_images:
        vehicle_filename = f"{timestamp}_vehicle.jpg"
        with open(os.path.join(image_dir, vehicle_filename), "wb") as image_file:
            image_file.write(vehicle_images[0])
        vehicle_rel = f"/static/anpr/{date_folder}/{vehicle_filename}"

        if len(vehicle_images) > 1 and not plate_images:
            plate_images = [vehicle_images[1]]

    if plate_images:
        plate_filename = f"{timestamp}_plate.jpg"
        with open(os.path.join(image_dir, plate_filename), "wb") as plate_file:
            plate_file.write(plate_images[0])
        return vehicle_rel, f"/static/anpr/{date_folder}/{plate_filename}", image_bytes

    return vehicle_rel, _crop_plate_from_box(data, image_bytes, image_dir, date_folder, timestamp), image_bytes


def image_content_status(data):
    picture = first_object(data or {}, ("Picture", "picture", "ANPR", "anpr", "Event", "event")) or (data or {})
    vehicle_sources = []
    plate_sources = []

    for key in VEHICLE_IMAGE_KEYS:
        obj = first_object(picture, (key,))
        if obj and first_present(obj, IMAGE_CONTENT_KEYS):
            vehicle_sources.append(key)

    for key in PLATE_IMAGE_KEYS:
        obj = first_object(picture, (key,))
        if obj and first_present(obj, IMAGE_CONTENT_KEYS):
            plate_sources.append(key)

    return {
        "vehicle_sources": vehicle_sources,
        "plate_sources": plate_sources,
        "has_vehicle_image": bool(vehicle_sources),
        "has_plate_image": bool(plate_sources),
    }


def _decode_base64_image(content):
    if not content:
        return None
    if "," in content[:80]:
        content = content.split(",", 1)[1]
    if str(content).strip().startswith(("/", "http://", "https://")):
        return None
    try:
        return base64.b64decode(content, validate=False)
    except Exception:
        return None


def _crop_plate_from_box(data, image_bytes, image_dir, date_folder, timestamp):
    """Fallback only: crop using the camera bounding box if no embedded plate JPEG exists."""
    try:
        if not image_bytes:
            return ""
        frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        picture = first_object(data or {}, ("Picture", "picture", "ANPR", "anpr", "Event", "event")) or (data or {})
        plate = first_object(picture, ("Plate", "plate", "PlateInfo", "plateInfo", "LicensePlate", "licensePlate")) or picture
        plate_box = parse_box(first_present(plate, BOUNDING_BOX_KEYS) or first_present(data or {}, BOUNDING_BOX_KEYS))
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
    picture = first_object(data or {}, ("Picture", "picture", "ANPR", "anpr", "Event", "event")) or (data or {})
    plate = first_object(picture, ("Plate", "plate", "PlateInfo", "plateInfo", "LicensePlate", "licensePlate")) or {}
    vehicle = first_object(picture, ("Vehicle", "vehicle", "VehicleInfo", "vehicleInfo", "Object", "object")) or {}
    snap = first_object(picture, ("SnapInfo", "snapInfo", "Snap", "snap", "Info", "info")) or {}
    normal_pic = first_object(picture, ("NormalPic", "normalPic", "VehiclePic", "vehiclePic", "OriginalImage", "originalImage")) or {}
    cutout_pic = first_object(picture, ("CutoutPic", "cutoutPic", "PlatePic", "platePic", "PlateCutout", "plateCutout")) or {}
    camera_id, camera_name = camera_from_event(data or {})

    plate_number = str(
        first_scalar(plate, PLATE_KEYS)
        or first_scalar(picture, PLATE_KEYS)
        or first_scalar(data or {}, PLATE_KEYS)
        or _find_text_in_picture_headers(picture, ["UnRecognise", "Unknown"])
        or ""
    ).strip().upper()
    snap_time = (
        first_scalar(snap, TIME_KEYS)
        or first_scalar(picture, TIME_KEYS)
        or first_scalar(data or {}, TIME_KEYS)
        or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    plate_color = first_scalar(plate, PLATE_COLOR_KEYS) or first_scalar(picture, PLATE_COLOR_KEYS) or ""
    plate_type = first_scalar(plate, PLATE_TYPE_KEYS) or first_scalar(picture, PLATE_TYPE_KEYS) or ""
    vehicle_type = first_scalar(vehicle, VEHICLE_TYPE_KEYS) or first_scalar(picture, VEHICLE_TYPE_KEYS) or ""
    vehicle_color = first_scalar(vehicle, VEHICLE_COLOR_KEYS) or first_scalar(picture, VEHICLE_COLOR_KEYS) or ""
    class_id, class_name, class_reason = classify_vehicle_from_anpr(
        plate_number,
        plate_color=plate_color,
        plate_type=plate_type,
        vehicle_type=vehicle_type,
    )

    master = get_vehicle_master_info(plate_number) if plate_number else None
    raw_speed, speed_text = event_speed(vehicle or picture or data, class_id=class_id, class_name=class_name)
    existing_vehicle_img = first_path(picture, VEHICLE_IMAGE_PATH_KEYS) or first_path(data or {}, VEHICLE_IMAGE_PATH_KEYS)
    existing_plate_img = first_path(picture, PLATE_IMAGE_PATH_KEYS) or first_path(data or {}, PLATE_IMAGE_PATH_KEYS)

    return {
        "event_file": event_file or "",
        "source_type": "cp_plus_anpr",
        "camera_id": camera_id,
        "camera_name": camera_name,
        "track_id": event_track_id(),
        "license": plate_number or "UNKNOWN",
        "plate_number": plate_number,
        "plate_confidence": first_scalar(plate, CONFIDENCE_KEYS) or first_scalar(picture, CONFIDENCE_KEYS),
        "plate_color": plate_color,
        "plate_type": plate_type,
        "vehicle_type": vehicle_type,
        "ignored_vehicle": is_ignored_vehicle_type(vehicle_type),
        "vehicle_type_master": (master or {}).get("vehicle_type", "") or NO_RECORD_TEXT,
        "unit": display_unit_for_class((master or {}).get("unit", ""), class_name, class_id),
        "driver_name": (master or {}).get("driver_name", "") or NO_RECORD_TEXT,
        "make_model": (master or {}).get("make_model", "") or NO_RECORD_TEXT,
        "vehicle_remarks": (master or {}).get("remarks", "") or NO_RECORD_TEXT,
        "vehicle_master_match": bool(master),
        "vehicle_color": vehicle_color,
        "speed": speed_text,
        "raw_speed": raw_speed,
        "time": snap_time,
        "class_id": class_id,
        "class_name": class_name,
        "classification_reason": class_reason,
        "device_id": first_scalar(snap, DEVICE_KEYS) or first_scalar(data or {}, DEVICE_KEYS) or "",
        "lane": first_scalar(snap, LANE_KEYS) or first_scalar(data or {}, LANE_KEYS),
        "channel": first_scalar(plate, CHANNEL_KEYS) or first_scalar(data or {}, CHANNEL_KEYS),
        "normal_pic_name": first_scalar(normal_pic, ("PicName", "picName", "FileName", "fileName")) or "",
        "cutout_pic_name": first_scalar(cutout_pic, ("PicName", "picName", "FileName", "fileName")) or "",
        "direction": first_scalar(picture, ("Direction", "direction")) or first_scalar(data or {}, ("Direction", "direction")) or "South to North",
        "license_img": existing_plate_img,
        "veh_img": existing_vehicle_img,
        "is_detection_event": bool(picture or plate_number or vehicle_type or vehicle_color),
    }


def first_object(data, keys):
    value = first_present(data, keys)
    return value if isinstance(value, dict) else None


def first_present(data, keys):
    if not isinstance(data, dict):
        return None

    lowered = {str(key).lower(): key for key in data.keys()}
    for key in keys:
        real_key = lowered.get(str(key).lower())
        if real_key is not None:
            value = data.get(real_key)
            if value not in (None, ""):
                return value

    for value in data.values():
        if isinstance(value, dict):
            found = first_present(value, keys)
            if found not in (None, ""):
                return found
        elif isinstance(value, list):
            for item in value:
                found = first_present(item, keys)
                if found not in (None, ""):
                    return found
    return None


def first_scalar(data, keys):
    value = first_present(data, keys)
    return value if value not in (None, "") and not isinstance(value, (dict, list)) else None


def first_image_content(data, image_keys):
    if not isinstance(data, dict):
        return ""
    for key in image_keys:
        obj = first_object(data, (key,))
        if obj:
            content = first_present(obj, IMAGE_CONTENT_KEYS)
            if content:
                return str(content)
        value = first_scalar(data, (key,))
        if value and looks_image_content(value):
            return str(value)
    return ""


def looks_image_content(value):
    text = str(value or "").strip()
    if text.startswith("data:image/"):
        return True
    if first_path({"image": text}, ("image",)):
        return False
    return len(text) > 100 and bool(re.fullmatch(r"[A-Za-z0-9+/=\s]+", text))


def first_path(data, keys):
    value = first_present(data, keys)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("/", "http://", "https://")):
            return text
        if re.search(r"\.(?:jpg|jpeg|png|webp)(?:$|\?)", text, flags=re.IGNORECASE):
            return text
    return ""


def parse_box(value):
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return list(value)
    if isinstance(value, dict):
        candidates = [
            (value.get("x1"), value.get("y1"), value.get("x2"), value.get("y2")),
            (value.get("left"), value.get("top"), value.get("right"), value.get("bottom")),
        ]
        for candidate in candidates:
            if all(item is not None for item in candidate):
                return list(candidate)
        if all(key in value for key in ("x", "y", "w", "h")):
            x, y, w, h = value.get("x"), value.get("y"), value.get("w"), value.get("h")
            return [x, y, safe_int(x) + safe_int(w), safe_int(y) + safe_int(h)]
    if isinstance(value, str):
        parts = re.findall(r"-?\d+", value)
        if len(parts) >= 4:
            return parts[:4]
    return []


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
