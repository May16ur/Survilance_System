import datetime
import json
import os

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from flask_app.blueprints.route_utils import RECEIVED_FOLDER, clear_api_cache
from flask_app.services.cp_plus import decode_event_images, normalize_event, store_event_in_db

bp = Blueprint("notifications", __name__)

@bp.route("/NotificationInfo/TollgateInfo", methods=["POST"])
@bp.route("/api/notifications/tollgate", methods=["POST"])
def tollgate_notification():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict(flat=False)

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
        file = request.files[key]
        filename = secure_filename(f"{timestamp}_{file.filename}")
        filepath = os.path.join(RECEIVED_FOLDER, filename)
        file.save(filepath)
        event_data["files"].append({
            "field": key,
            "filename": file.filename,
            "saved_as": filepath,
        })

    json_filename = f"{timestamp}_event.json"
    json_filepath = os.path.join(RECEIVED_FOLDER, json_filename)
    with open(json_filepath, "w", encoding="utf-8") as json_file:
        json.dump(event_data, json_file, indent=4, ensure_ascii=False)

    clear_api_cache()

    return jsonify({
        "success": True,
        "message": "OK",
        "event_file": json_filename,
        "parsed": normalized,
        "db_result": db_result,
    })


@bp.route("/NotificationInfo/KeepAlive", methods=["POST"])
@bp.route("/api/notifications/keepalive", methods=["POST", "GET"])
def notification_keepalive():
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
