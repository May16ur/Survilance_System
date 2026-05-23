import datetime
import hashlib
import json
import os
import threading
import time
from collections import deque

from flask import Blueprint, Response, jsonify, request
from werkzeug.utils import secure_filename

from flask_app.blueprints.route_utils import RECEIVED_FOLDER, clear_api_cache
from flask_app.services.cp_plus import decode_event_images, normalize_event, store_event_in_db
from flask_app.services.cp_plus import ANPR_IMAGE_FOLDER

bp = Blueprint("notifications", __name__)

RECENT_EVENTS_FILE = os.path.join(RECEIVED_FOLDER, "recent_events.json")
DUPLICATE_WINDOW_SEC = 3
PLATE_DUPLICATE_WINDOW_SEC = int(os.getenv("CP_PLUS_DUPLICATE_PLATE_WINDOW_SEC", "300"))
MAX_CAMERA_EVENT_AGE_SEC = int(os.getenv("CP_PLUS_MAX_EVENT_AGE_SEC", "120"))
receiver_lock = threading.Lock()
recent_receiver_events = deque(maxlen=200)
recent_event_fingerprints = {}
recent_plate_events = {}


def _log_receiver_hit(name):
    print(f"[CAMERA] {name} hit from {request.remote_addr} content-type={request.content_type}")


def _event_fingerprint(data, normalized):
    picture = (data or {}).get("Picture") or {}
    snap = picture.get("SnapInfo") or {}
    plate = picture.get("Plate") or {}
    parts = [
        str(normalized.get("license") or plate.get("PlateNumber") or ""),
        str(normalized.get("time") or snap.get("SnapTime") or snap.get("AccurateTime") or ""),
        str(normalized.get("device_id") or snap.get("DeviceID") or request.remote_addr or ""),
        str(normalized.get("lane") or snap.get("LanNo") or ""),
    ]
    raw = "|".join(parts)
    if raw.strip("|"):
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()
    return hashlib.sha1(json.dumps(data or {}, sort_keys=True, default=str).encode("utf-8", errors="ignore")).hexdigest()


def _plate_duplicate_key(normalized):
    plate = str(normalized.get("plate_number") or normalized.get("license") or "").strip().upper()
    if not plate or plate in ("UNKNOWN", "UNRECOGNISE", "UNRECOGNIZED"):
        return ""
    return "|".join([
        plate,
        str(normalized.get("camera_id") or ""),
        str(normalized.get("lane") or ""),
    ])


def _event_label(normalized):
    plate = str(normalized.get("plate_number") or normalized.get("license") or "UNKNOWN").strip().upper()
    camera = normalized.get("camera_name") or normalized.get("camera_id") or "camera"
    lane = normalized.get("lane") or ""
    return f"plate={plate} camera={camera} lane={lane}"


def _parse_camera_time(value):
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _stale_event_reason(normalized):
    if MAX_CAMERA_EVENT_AGE_SEC <= 0:
        return ""
    camera_time = _parse_camera_time(normalized.get("time"))
    if not camera_time:
        return ""
    age_sec = (datetime.datetime.now() - camera_time).total_seconds()
    if age_sec > MAX_CAMERA_EVENT_AGE_SEC:
        return f"camera event is {int(age_sec)}s old; max allowed is {MAX_CAMERA_EVENT_AGE_SEC}s"
    if age_sec < -MAX_CAMERA_EVENT_AGE_SEC:
        return f"camera event is {abs(int(age_sec))}s in the future; check camera clock"
    return ""


def _prune_duplicate_trackers(now):
    stale_fingerprints = [
        key for key, value in recent_event_fingerprints.items()
        if now - value.get("time", 0) > max(DUPLICATE_WINDOW_SEC, PLATE_DUPLICATE_WINDOW_SEC)
    ]
    for key in stale_fingerprints:
        recent_event_fingerprints.pop(key, None)

    stale_plates = [
        key for key, value in recent_plate_events.items()
        if now - value.get("time", 0) > PLATE_DUPLICATE_WINDOW_SEC
    ]
    for key in stale_plates:
        recent_plate_events.pop(key, None)


def _save_recent_events_locked():
    os.makedirs(RECEIVED_FOLDER, exist_ok=True)
    with open(RECENT_EVENTS_FILE, "w", encoding="utf-8") as event_file:
        json.dump(list(recent_receiver_events), event_file, indent=2, ensure_ascii=False)


def _load_recent_events():
    if recent_receiver_events or not os.path.exists(RECENT_EVENTS_FILE):
        return
    try:
        with open(RECENT_EVENTS_FILE, "r", encoding="utf-8") as event_file:
            rows = json.load(event_file)
        with receiver_lock:
            recent_receiver_events.clear()
            recent_receiver_events.extend(rows if isinstance(rows, list) else [])
    except Exception as e:
        print("[CAMERA] recent event load skipped:", e)


def _remember_event(event_data, fingerprint):
    event_data["fingerprint"] = fingerprint
    with receiver_lock:
        recent_receiver_events.appendleft(event_data)
        _save_recent_events_locked()


def _write_received_json(filename, payload):
    os.makedirs(RECEIVED_FOLDER, exist_ok=True)
    filepath = os.path.join(RECEIVED_FOLDER, filename)
    with open(filepath, "w", encoding="utf-8") as json_file:
        json.dump(payload, json_file, indent=4, ensure_ascii=False)
    print(f"[CAMERA] saved received payload: {filepath}")
    return filepath


def _assign_nested(target, dotted_key, value):
    parts = [part for part in str(dotted_key).replace("[", ".").replace("]", "").split(".") if part]
    if not parts:
        return
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _parse_camera_payload():
    if request.is_json:
        return request.get_json(silent=True) or {}

    form = request.form.to_dict(flat=False)
    parsed = {}

    for key, values in form.items():
        value = values[0] if isinstance(values, list) and len(values) == 1 else values
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    candidate = json.loads(stripped)
                    if isinstance(candidate, dict):
                        if "Picture" in candidate:
                            parsed.update(candidate)
                        else:
                            parsed[key] = candidate
                        continue
                except Exception:
                    pass
        if "." in key:
            _assign_nested(parsed, key, value)
        else:
            parsed[key] = value

    for key in ("Info", "Data", "data", "json", "event", "ANPR"):
        candidate = parsed.get(key)
        if isinstance(candidate, dict) and "Picture" in candidate:
            return candidate

    return parsed


def _save_camera_file(file, field, timestamp):
    date_folder = datetime.datetime.now().strftime("%Y%m%d")
    image_dir = os.path.join(ANPR_IMAGE_FOLDER, date_folder)
    os.makedirs(image_dir, exist_ok=True)

    raw_name = secure_filename(file.filename or field or "camera_image.jpg")
    field_name = secure_filename(field or "image")
    lower = f"{field_name}_{raw_name}".lower()
    kind = "plate" if "plate" in lower or "cutout" in lower else "vehicle"
    filename = f"{timestamp}_{kind}_{raw_name}"
    filepath = os.path.join(image_dir, filename)
    file.save(filepath)
    return {
        "field": field,
        "filename": file.filename,
        "saved_as": filepath,
        "url": f"/static/anpr/{date_folder}/{filename}",
        "kind": kind,
    }


def _camera_ok_response(api_payload):
    if request.path.startswith("/NotificationInfo/"):
        return Response("OK", status=200, mimetype="text/plain")
    return jsonify(api_payload)


@bp.route("/NotificationInfo/TollgateInfo", methods=["POST"])
@bp.route("/api/notifications/tollgate", methods=["POST"])
def tollgate_notification():
    _log_receiver_hit("TollgateInfo")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    json_filename = f"{timestamp}_event.json"

    data = _parse_camera_payload()

    event_data = {
        "received_at": datetime.datetime.now().isoformat(),
        "content_type": request.content_type,
        "remote_addr": request.remote_addr,
        "path": request.path,
        "method": request.method,
        "data": data,
        "files": [],
    }

    normalized = normalize_event(data)
    fingerprint = _event_fingerprint(data, normalized)
    plate_key = _plate_duplicate_key(normalized)
    stale_reason = _stale_event_reason(normalized)
    if stale_reason:
        print(f"[CAMERA] stale event skipped: {_event_label(normalized)} reason={stale_reason}")
        clear_api_cache()
        return _camera_ok_response({"success": True, "message": "OK", "stale": True, "reason": stale_reason})

    now = time.time()
    with receiver_lock:
        _prune_duplicate_trackers(now)
        previous = recent_event_fingerprints.get(fingerprint)
        if previous and now - previous["time"] < DUPLICATE_WINDOW_SEC:
            previous["time"] = now
            previous["count"] += 1
            print(f"[CAMERA] exact duplicate skipped: {_event_label(normalized)} count={previous['count']}")
            for event in recent_receiver_events:
                if event.get("fingerprint") == fingerprint:
                    event["duplicate_count"] = previous["count"]
                    _save_recent_events_locked()
                    break
            clear_api_cache()
            return _camera_ok_response({"success": True, "message": "OK", "duplicate": True})
        previous_plate = recent_plate_events.get(plate_key) if plate_key else None
        if previous_plate and now - previous_plate["time"] < PLATE_DUPLICATE_WINDOW_SEC:
            previous_plate["time"] = now
            previous_plate["count"] += 1
            print(f"[CAMERA] duplicate plate skipped: {_event_label(normalized)} count={previous_plate['count']}")
            clear_api_cache()
            return _camera_ok_response({"success": True, "message": "OK", "duplicate_plate": True})
        recent_event_fingerprints[fingerprint] = {"time": now, "count": 0}
        if plate_key:
            recent_plate_events[plate_key] = {"time": now, "count": 0}

    _write_received_json(json_filename, event_data)

    veh_img, license_img, _image_bytes = decode_event_images(data, timestamp)
    normalized["veh_img"] = veh_img
    normalized["vehicle"] = veh_img
    normalized["license_img"] = license_img
    normalized["plate"] = license_img
    normalized["event_file"] = json_filename
    db_result = store_event_in_db(normalized)
    event_data["parsed"] = normalized
    event_data["db_result"] = db_result
    event_data["event_file"] = json_filename
    event_data["duplicate_count"] = 0

    for key in request.files:
        for file in request.files.getlist(key):
            saved = _save_camera_file(file, key, timestamp)
            event_data["files"].append(saved)
            if saved["kind"] == "plate" and not normalized.get("license_img"):
                normalized["license_img"] = saved["url"]
                normalized["plate"] = saved["url"]
            elif saved["kind"] == "vehicle" and not normalized.get("veh_img"):
                normalized["veh_img"] = saved["url"]
                normalized["vehicle"] = saved["url"]

    if event_data["files"]:
        db_result = store_event_in_db(normalized)
        event_data["parsed"] = normalized
        event_data["db_result"] = db_result

    _write_received_json(json_filename, event_data)

    _remember_event(event_data, fingerprint)
    clear_api_cache()

    return _camera_ok_response({
        "success": True,
        "message": "OK",
        "event_file": json_filename,
        "parsed": normalized,
        "db_result": db_result,
    })


@bp.route("/NotificationInfo/KeepAlive", methods=["POST", "GET"])
@bp.route("/api/notifications/keepalive", methods=["POST", "GET"])
def notification_keepalive():
    _log_receiver_hit("KeepAlive")
    if request.path.startswith("/NotificationInfo/"):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        _write_received_json(f"{timestamp}_keepalive.json", {
            "received_at": datetime.datetime.now().isoformat(),
            "content_type": request.content_type,
            "remote_addr": request.remote_addr,
            "path": request.path,
            "method": request.method,
            "data": _parse_camera_payload() if request.method == "POST" else {},
        })
        return Response("OK", status=200, mimetype="text/plain")
    return jsonify({"success": True, "message": "OK"})


@bp.route("/NotificationInfo/<path:interface_name>", methods=["POST", "GET"])
def notification_unknown_interface(interface_name):
    _log_receiver_hit(interface_name)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    data = _parse_camera_payload() if request.method == "POST" else {}
    filename = f"{timestamp}_unknown_{secure_filename(interface_name) or 'notification'}.json"
    _write_received_json(filename, {
        "received_at": datetime.datetime.now().isoformat(),
        "content_type": request.content_type,
        "remote_addr": request.remote_addr,
        "path": request.path,
        "method": request.method,
        "interface": interface_name,
        "data": data,
        "note": "Camera used an unregistered NotificationInfo interface. Configure ANPR to /NotificationInfo/TollgateInfo or add a parser for this interface.",
    })
    return Response("OK", status=200, mimetype="text/plain")


@bp.route("/api/notifications/recent")
def api_recent_notifications():
    limit = max(1, min(request.args.get("limit", default=50, type=int), 200))
    files = sorted(
        [name for name in os.listdir(RECEIVED_FOLDER) if name.endswith("_event.json")],
        key=lambda name: os.path.getmtime(os.path.join(RECEIVED_FOLDER, name)),
        reverse=True,
    )[:limit]

    events = []
    for filename in files:
        path = os.path.join(RECEIVED_FOLDER, filename)
        try:
            with open(path, "r", encoding="utf-8") as event_file:
                event = json.load(event_file)
            event["event_file"] = filename
            event["saved_at"] = datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
            parsed = event.get("parsed")
            if not parsed:
                parsed = normalize_event(event.get("data") or {}, event_file=filename)
                event["parsed"] = parsed
            if parsed:
                timestamp = filename.replace("_event.json", "")
                veh_img, license_img, _image_bytes = decode_event_images(event.get("data") or {}, timestamp)
                parsed["veh_img"] = veh_img or parsed.get("veh_img", "")
                parsed["vehicle"] = parsed["veh_img"]
                parsed["license_img"] = license_img or parsed.get("license_img", "")
                parsed["plate"] = parsed["license_img"]
            events.append(event)
        except Exception as e:
            events.append({"event_file": filename, "error": str(e)})

    return jsonify({"success": True, "events": events})
