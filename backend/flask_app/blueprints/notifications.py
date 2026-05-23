import datetime
import json
import os

from flask import Blueprint, Response, jsonify, request
from werkzeug.utils import secure_filename

from flask_app.blueprints.route_utils import RECEIVED_FOLDER, clear_api_cache
from flask_app.services.cp_plus import decode_event_images, normalize_event, store_event_in_db
from flask_app.services.cp_plus import ANPR_IMAGE_FOLDER

bp = Blueprint("notifications", __name__)

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
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    data = _parse_camera_payload()

    event_data = {
        "received_at": datetime.datetime.now().isoformat(),
        "content_type": request.content_type,
        "data": data,
        "files": [],
    }

    normalized = normalize_event(data)
    veh_img, license_img, _image_bytes = decode_event_images(data, timestamp)
    normalized["veh_img"] = veh_img
    normalized["vehicle"] = veh_img
    normalized["license_img"] = license_img
    normalized["plate"] = license_img
    normalized["event_file"] = f"{timestamp}_event.json"
    db_result = store_event_in_db(normalized)
    event_data["parsed"] = normalized
    event_data["db_result"] = db_result

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

    json_filename = f"{timestamp}_event.json"
    json_filepath = os.path.join(RECEIVED_FOLDER, json_filename)
    with open(json_filepath, "w", encoding="utf-8") as json_file:
        json.dump(event_data, json_file, indent=4, ensure_ascii=False)

    clear_api_cache()

    return _camera_ok_response({
        "success": True,
        "message": "OK",
        "event_file": json_filename,
        "parsed": normalized,
        "db_result": db_result,
    })


@bp.route("/NotificationInfo/KeepAlive", methods=["POST"])
@bp.route("/api/notifications/keepalive", methods=["POST", "GET"])
def notification_keepalive():
    if request.path.startswith("/NotificationInfo/"):
        return Response("OK", status=200, mimetype="text/plain")
    return jsonify({"success": True, "message": "OK"})


@bp.route("/api/notifications/recent")
def api_recent_notifications():
    limit = max(1, min(request.args.get("limit", default=50, type=int), 200))
    files = sorted(
        [name for name in os.listdir(RECEIVED_FOLDER) if name.endswith("_event.json")],
        reverse=True,
    )[:limit]

    events = []
    for filename in files:
        path = os.path.join(RECEIVED_FOLDER, filename)
        try:
            with open(path, "r", encoding="utf-8") as event_file:
                event = json.load(event_file)
            event["event_file"] = filename
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
