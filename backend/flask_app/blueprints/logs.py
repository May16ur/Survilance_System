from flask import Blueprint, jsonify, request

from core.common import CAMERA_NAME_MAP, build_tcp_report_rows, fetch_recent_logs
from flask_app.blueprints.route_utils import (
    RTSP_PIPELINE_ERROR,
    VIDEO_PIPELINE_ERROR,
    get_stream_logs_by_camera,
    save_stream_logs_to_database,
    get_upload_logs,
    cache_get,
    cache_set,
    pipeline_unavailable_response,
)

bp = Blueprint("logs", __name__)

@bp.route("/api/upload_logs")
def api_upload_logs():
    if VIDEO_PIPELINE_ERROR is not None:
        return jsonify({"logs": [], "success": False, "message": str(VIDEO_PIPELINE_ERROR)})

    return jsonify({"logs": get_upload_logs()})


@bp.route("/api/stream_logs")
def api_stream_logs():
    if RTSP_PIPELINE_ERROR is not None:
        return jsonify({"success": False, "message": str(RTSP_PIPELINE_ERROR)})

    return jsonify(get_stream_logs_by_camera())


@bp.route("/api/camera_logs/<int:camera_id>")
def api_camera_logs(camera_id):
    if camera_id not in CAMERA_NAME_MAP:
        return jsonify({"logs": []}), 400

    camera_name = CAMERA_NAME_MAP[camera_id]
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    vehicle_type = (request.args.get('vehicle_type') or 'all').lower()

    limit = request.args.get('limit', default=200, type=int)
    limit = max(20, min(int(limit or 200), 1000))
    cache_key = f"camera_logs:{camera_id}:{limit}:{start_date or ''}:{end_date or ''}:{vehicle_type}"
    cached = cache_get(cache_key, 5)
    if cached is not None:
        return jsonify(cached)

    rows = fetch_recent_logs(camera_name=camera_name, camera_id=camera_id, limit=limit, start_date=start_date, end_date=end_date)
    if vehicle_type == 'mil':
        rows = [r for r in rows if str(r.get('class_id')) == '0' or 'mil' in str(r.get('class_name', '')).lower()]
    elif vehicle_type == 'civil':
        rows = [r for r in rows if str(r.get('class_id')) == '1' or 'civil' in str(r.get('class_name', '')).lower()]

    logs = []

    for row in rows:
        time_value = row.get("time")

        if hasattr(time_value, "strftime"):
            time_value = time_value.strftime("%Y-%m-%d %H:%M:%S")
        else:
            time_value = str(time_value or "")

        logs.append({
            "id": row.get("id"),
            "track_id": row.get("track_id"),
            "Track ID": row.get("track_id"),

            "class_name": row.get("class_name"),
            "Class Name": row.get("class_name"),

            "avg_speed": row.get("avg_speed"),
            "Avg Speed": row.get("avg_speed"),

            "license": row.get("license"),
            "License": row.get("license"),
            "unit": row.get("unit"),
            "vehicle_type_master": row.get("vehicle_type_master"),
            "make_model": row.get("make_model"),
            "driver_name": row.get("driver_name"),
            "vehicle_remarks": row.get("vehicle_remarks"),
            "vehicle_master_match": row.get("vehicle_master_match"),

            "time": time_value,
            "Time": time_value,

            "class_id": row.get("class_id"),
            "Class ID": row.get("class_id"),

            "camera_name": row.get("camera_name"),
            "license_img": row.get("license_img"),
            "veh_img": row.get("veh_img"),

            "plate": row.get("license_img"),
            "vehicle": row.get("veh_img"),

            "source_type": row.get("source_type"),
            "source_table": row.get("source_table"),
            "Source Table": row.get("source_table"),
        })

    return jsonify(cache_set(cache_key, {"logs": logs}))


@bp.route("/api/tcp_table/<tcp_name>")
def api_tcp_table(tcp_name):
    try:
        tcp_name = (tcp_name or "all").strip().lower()
        start_date = (request.args.get("start_date") or "").strip()
        end_date = (request.args.get("end_date") or "").strip()
        limit = request.args.get("limit", default=300, type=int)
        limit = max(50, min(int(limit or 300), 2000))

        cache_key = f"tcp_table:{tcp_name}:{start_date}:{end_date}:{limit}"
        cached = cache_get(cache_key, 30)
        if cached is not None:
            return jsonify(cached)

        report = build_tcp_report_rows(
            tcp_name=tcp_name,
            limit=limit,
            start_date=start_date or None,
            end_date=end_date or None,
        )
        cache_set(cache_key, report)
        status = 200 if report.get("success") else 400
        return jsonify(report), status
    except Exception as e:
        print("TCP TABLE API ERROR:", e)
        return jsonify({"success": False, "message": str(e), "rows": []}), 500


@bp.route("/save_logs", methods=["POST"])
def save_logs():
    if RTSP_PIPELINE_ERROR is not None:
        return pipeline_unavailable_response("RTSP YOLO", RTSP_PIPELINE_ERROR)

    count = save_stream_logs_to_database()
    return jsonify({"saved": count, "message": f"{count} logs saved to database"})
