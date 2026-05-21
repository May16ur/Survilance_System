import os
import time
import datetime
import json
from io import BytesIO


from flask import Blueprint, Response, request, jsonify, send_file
from werkzeug.utils import secure_filename

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A3
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

try:
    from rtsp_pipeline import (
        start_rtsp_streams,
        start_rtsp_camera,
        generate_frames,
        get_latest_frame_jpeg,
        get_stream_logs_by_camera,
        save_stream_logs_to_database,
    )
    RTSP_PIPELINE_ERROR = None
except Exception as e:
    RTSP_PIPELINE_ERROR = e
    start_rtsp_streams = start_rtsp_camera = generate_frames = get_latest_frame_jpeg = None
    get_stream_logs_by_camera = save_stream_logs_to_database = None

try:
    from video_pipeline import start_uploaded_video, generate_uploaded_video_frames, get_upload_logs
    VIDEO_PIPELINE_ERROR = None
except Exception as e:
    VIDEO_PIPELINE_ERROR = e
    start_uploaded_video = generate_uploaded_video_frames = get_upload_logs = None

from core.common import (
    CAMERA_NAME_MAP,
    get_dashboard_stats,
    get_last_7_days_report_rows,
    get_camera_comparison_stats,
    get_remaining_vehicle_rows,
    update_vehicle_log_row,
    delete_vehicle_log_row,
    fetch_recent_logs,
    add_or_update_vehicle_master,
    get_vehicle_master_rows,
    get_vehicle_master_info,
    enrich_rows_with_vehicle_master,
    TABLE_NAME,
    _get_connection,
    ensure_database,
    ensure_table,
    build_tcp_report_rows,
    get_camera_today_db_stats,
    _build_union_logs_query,
    get_camera_sum_vs_dashboard,
)

from flask_app.services.cp_plus import decode_event_images, normalize_event, store_event_in_db
from preview_pipeline import (
    register_preview_urls,
    start_preview_camera,
    stop_preview_camera,
    get_preview_snapshot,
    generate_preview_frames,
)

main = Blueprint("main", __name__)


# Small route cache to stop many browser tabs / hover popups from hammering MySQL.
_API_CACHE = {}

def _cache_get(key, ttl_sec):
    item = _API_CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if time.time() - ts > ttl_sec:
        _API_CACHE.pop(key, None)
        return None
    return value

def _cache_set(key, value):
    _API_CACHE[key] = (time.time(), value)
    if len(_API_CACHE) > 200:
        for old_key in list(_API_CACHE.keys())[:50]:
            _API_CACHE.pop(old_key, None)
    return value

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
RECEIVED_FOLDER = os.path.join(BASE_DIR, "received")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RECEIVED_FOLDER, exist_ok=True)


def _pipeline_unavailable_response(name, error):
    return jsonify({
        "success": False,
        "message": f"{name} pipeline unavailable. CP Plus ANPR receiver still works.",
        "error": str(error),
    }), 503


@main.route("/api/health")
def api_health():
    return jsonify({
        "success": True,
        "service": "e-TCP Surveillance API",
        "time": datetime.datetime.now().isoformat(),
        "cp_plus_anpr": "ready",
        "plate_extract": "embedded_jpeg",
        "rtsp_yolo": "ready" if RTSP_PIPELINE_ERROR is None else f"unavailable: {RTSP_PIPELINE_ERROR}",
        "upload_yolo": "ready" if VIDEO_PIPELINE_ERROR is None else f"unavailable: {VIDEO_PIPELINE_ERROR}",
    })


@main.route("/api/cameras")
def api_cameras():
    return jsonify({
        "success": True,
        "cameras": [
            {"id": camera_id, "name": camera_name}
            for camera_id, camera_name in CAMERA_NAME_MAP.items()
        ],
    })


@main.route("/NotificationInfo/TollgateInfo", methods=["POST"])
@main.route("/api/notifications/tollgate", methods=["POST"])
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

    _API_CACHE.clear()

    return jsonify({
        "success": True,
        "message": "OK",
        "event_file": json_filename,
        "parsed": normalized,
        "db_result": db_result,
    })


@main.route("/NotificationInfo/KeepAlive", methods=["POST"])
@main.route("/api/notifications/keepalive", methods=["POST", "GET"])
def notification_keepalive():
    return jsonify({"success": True, "message": "OK"})


@main.route("/api/notifications/recent")
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


@main.route("/upload_video", methods=["POST"])
def upload_video():
    if VIDEO_PIPELINE_ERROR is not None:
        return _pipeline_unavailable_response("Uploaded video YOLO", VIDEO_PIPELINE_ERROR)

    if "video" not in request.files:
        return jsonify({"success": False, "message": "No video file uploaded"})

    file = request.files["video"]

    if file.filename == "":
        return jsonify({"success": False, "message": "No selected file"})

    filename = secure_filename(file.filename)
    path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(path)

    start_uploaded_video(path)

    return jsonify({"success": True, "message": "Video processing started"})


@main.route("/video_feed")
def video_feed():
    if VIDEO_PIPELINE_ERROR is not None:
        return _pipeline_unavailable_response("Uploaded video YOLO", VIDEO_PIPELINE_ERROR)

    return Response(
        generate_uploaded_video_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@main.route("/start_streams", methods=["POST"])
def start_streams():
    data = request.get_json(silent=True) or {}
    urls = data.get("urls", [])
    register_preview_urls(urls)
    if RTSP_PIPELINE_ERROR is None:
        start_rtsp_streams(urls)
    return jsonify({"success": True, "message": "RTSP preview URLs registered. Live preview does not use YOLO."})


@main.route("/start_camera", methods=["POST"])
def start_camera():
    return preview_start_camera()


@main.route("/preview/start_camera", methods=["POST"])
def preview_start_camera():
    data = request.get_json(silent=True) or {}
    camera_id = data.get("camera_id")
    url = data.get("url", "")

    if not isinstance(camera_id, int) or camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id."}), 400

    if not url or not isinstance(url, str):
        return jsonify({"success": False, "message": "RTSP URL is required to start camera."}), 400

    try:
        start_preview_camera(camera_id, url=url)
        return jsonify({"success": True, "message": f"Camera {camera_id} preview is starting without YOLO."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@main.route("/preview/stop_camera", methods=["POST"])
def preview_stop_camera():
    data = request.get_json(silent=True) or {}
    camera_id = data.get("camera_id")
    if not isinstance(camera_id, int) or camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id."}), 400
    stop_preview_camera(camera_id)
    return jsonify({"success": True, "message": f"Camera {camera_id} preview stopped."})


@main.route("/yolo/start_camera", methods=["POST"])
def yolo_start_camera():
    if RTSP_PIPELINE_ERROR is not None:
        return _pipeline_unavailable_response("RTSP YOLO", RTSP_PIPELINE_ERROR)

    data = request.get_json(silent=True) or {}
    camera_id = data.get("camera_id")
    url = data.get("url", "")

    if not isinstance(camera_id, int) or camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id."}), 400

    if not url or not isinstance(url, str):
        return jsonify({"success": False, "message": "RTSP URL is required to start camera."}), 400

    try:
        start_rtsp_camera(camera_id, url=url)
        return jsonify({"success": True, "message": f"Camera {camera_id} is starting."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@main.route("/camera_feed/<int:camera_id>")
def camera_feed(camera_id):
    if camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id"}), 400

    return Response(
        generate_preview_frames(camera_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@main.route("/yolo/camera_feed/<int:camera_id>")
def yolo_camera_feed(camera_id):
    if RTSP_PIPELINE_ERROR is not None:
        return _pipeline_unavailable_response("RTSP YOLO", RTSP_PIPELINE_ERROR)

    if camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id"}), 400

    return Response(
        generate_frames(camera_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@main.route("/camera_snapshot/<int:camera_id>")
def camera_snapshot(camera_id):
    if camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id"}), 400

    jpg = get_preview_snapshot(camera_id)
    return Response(
        jpg,
        mimetype="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@main.route("/preview/snapshot/<int:camera_id>")
def preview_snapshot(camera_id):
    return camera_snapshot(camera_id)


@main.route("/preview/feed/<int:camera_id>")
def preview_feed(camera_id):
    return camera_feed(camera_id)


@main.route("/yolo/camera_snapshot/<int:camera_id>")
def yolo_camera_snapshot(camera_id):
    if RTSP_PIPELINE_ERROR is not None:
        return jsonify({"success": False, "message": "RTSP YOLO pipeline unavailable"}), 503

    if camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id"}), 400

    jpg = get_latest_frame_jpeg(camera_id)
    return Response(
        jpg,
        mimetype="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@main.route("/api/upload_logs")
def api_upload_logs():
    if VIDEO_PIPELINE_ERROR is not None:
        return jsonify({"logs": [], "success": False, "message": str(VIDEO_PIPELINE_ERROR)})

    return jsonify({"logs": get_upload_logs()})


@main.route("/api/stream_logs")
def api_stream_logs():
    if RTSP_PIPELINE_ERROR is not None:
        return jsonify({"success": False, "message": str(RTSP_PIPELINE_ERROR)})

    return jsonify(get_stream_logs_by_camera())


@main.route("/api/camera_logs/<int:camera_id>")
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
    cached = _cache_get(cache_key, 5)
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

    return jsonify(_cache_set(cache_key, {"logs": logs}))


@main.route("/api/tcp_table/<tcp_name>")
def api_tcp_table(tcp_name):
    try:
        tcp_name = (tcp_name or "all").strip().lower()
        start_date = (request.args.get("start_date") or "").strip()
        end_date = (request.args.get("end_date") or "").strip()
        limit = request.args.get("limit", default=300, type=int)
        limit = max(50, min(int(limit or 300), 2000))

        cache_key = f"tcp_table:{tcp_name}:{start_date}:{end_date}:{limit}"
        cached = _cache_get(cache_key, 30)
        if cached is not None:
            return jsonify(cached)

        report = build_tcp_report_rows(
            tcp_name=tcp_name,
            limit=limit,
            start_date=start_date or None,
            end_date=end_date or None,
        )
        _cache_set(cache_key, report)
        status = 200 if report.get("success") else 400
        return jsonify(report), status
    except Exception as e:
        print("TCP TABLE API ERROR:", e)
        return jsonify({"success": False, "message": str(e), "rows": []}), 500


@main.route("/save_logs", methods=["POST"])
def save_logs():
    if RTSP_PIPELINE_ERROR is not None:
        return _pipeline_unavailable_response("RTSP YOLO", RTSP_PIPELINE_ERROR)

    count = save_stream_logs_to_database()
    return jsonify({"saved": count, "message": f"{count} logs saved to database"})


@main.route("/dashboard_full")
def dashboard_full():
    camera_id = request.args.get("camera_id", type=int)
    camera_name = CAMERA_NAME_MAP.get(camera_id) if camera_id in CAMERA_NAME_MAP else None
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    cache_key = f"dashboard_full:{camera_name or 'all'}:{start_date or ''}:{end_date or ''}"
    cached = _cache_get(cache_key, 15)
    if cached is not None:
        return jsonify(cached)
    data = get_dashboard_stats(
        camera_name=camera_name,
        start_date=start_date,
        end_date=end_date,
    )
    return jsonify(_cache_set(cache_key, data))


@main.route("/api/camera_dashboard/<int:camera_id>")
def api_camera_dashboard(camera_id):
    if camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id"}), 400

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    cache_key = f"camera_dashboard:{camera_id}:{start_date or ''}:{end_date or ''}"
    cached = _cache_get(cache_key, 20)
    if cached is not None:
        return jsonify(cached)

    data = get_dashboard_stats(
        camera_name=CAMERA_NAME_MAP[camera_id],
        start_date=start_date,
        end_date=end_date,
    )
    return jsonify(_cache_set(cache_key, data))


@main.route("/api/camera_today_stats/<int:camera_id>")
def api_camera_today_stats(camera_id):
    """Camera popup counter from DB. Uses requested date, or latest DB date for that camera."""
    if camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id", "today_mil": 0, "today_civil": 0, "today_total": 0}), 400

    date_value = request.args.get("date") or request.args.get("start_date")
    cache_key = f"camera_today:{camera_id}:{date_value or 'latest'}"
    cached = _cache_get(cache_key, 10)
    if cached is not None:
        return jsonify(cached)

    data = get_camera_today_db_stats(
        camera_id=camera_id,
        camera_name=CAMERA_NAME_MAP[camera_id],
        date_value=date_value,
    )
    return jsonify(_cache_set(cache_key, data))


@main.route("/api/last_7_days_report")
def api_last_7_days_report():
    vehicle_type = request.args.get("vehicle_type", "all")
    camera_id = request.args.get("camera_id", type=int)
    camera_name = CAMERA_NAME_MAP.get(camera_id) if camera_id in CAMERA_NAME_MAP else None
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    limit = max(50, min(int(request.args.get("limit", 2000)), 3000))
    cache_key = f"report:{camera_name or 'all'}:{vehicle_type}:{start_date or ''}:{end_date or ''}:{limit}"
    cached = _cache_get(cache_key, 20)
    if cached is not None:
        return jsonify(cached)

    rows = get_last_7_days_report_rows(
        camera_name=camera_name,
        vehicle_type=vehicle_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

    return jsonify(_cache_set(cache_key, {
        "vehicle_type": vehicle_type,
        "camera_name": camera_name or "All Cameras",
        "total": len(rows),
        "rows": rows,
    }))


def _build_report_pdf(rows, vehicle_type, camera_name):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A3),
        leftMargin=24,
        rightMargin=24,
        topMargin=24,
        bottomMargin=24,
    )

    styles = getSampleStyleSheet()
    story = []

    title_text = f"Last 7 Days Vehicle Report - {vehicle_type.title()} - {camera_name}"

    story.append(Paragraph(title_text, styles["Title"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(f"Total records: {len(rows)}", styles["Normal"]))
    story.append(Spacer(1, 0.15 * inch))

    table_data = [[
        "Camera",
        "Track ID",
        "Class",
        "Class ID",
        "Avg Speed",
        "License",
        "Time",
        "Log Date",
        "Plate Image",
        "Vehicle Image",
        "Source Type",
        "Source Table",
    ]]

    for row in rows:
        table_data.append([
            str(row.get("camera_name", "")),
            str(row.get("track_id", "")),
            str(row.get("class_name", "")),
            str(row.get("class_id", "")),
            str(row.get("avg_speed", "")),
            str(row.get("license", "")),
            str(row.get("time", "")),
            str(row.get("log_date", "")),
            str(row.get("plate", "")),
            str(row.get("vehicle", "")),
            str(row.get("source_type", "")),
            str(row.get("source_table", "")),
        ])

    col_widths = [
        1.25 * inch,
        0.60 * inch,
        0.80 * inch,
        0.55 * inch,
        0.75 * inch,
        1.05 * inch,
        1.35 * inch,
        0.90 * inch,
        1.65 * inch,
        1.65 * inch,
        0.75 * inch,
        1.00 * inch,
    ]

    table = Table(table_data, colWidths=col_widths, repeatRows=1)

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#198754")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("LEADING", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (4, -1), "CENTER"),
        ("ALIGN", (6, 1), (7, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
            colors.whitesmoke,
            colors.HexColor("#edf8f1"),
        ]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))

    story.append(table)

    doc.build(story)
    buffer.seek(0)

    return buffer


@main.route("/download_last_7_days_report")
def download_last_7_days_report():
    vehicle_type = request.args.get("vehicle_type", "all").strip().lower()

    if vehicle_type not in {"all", "mil", "civil"}:
        vehicle_type = "all"

    camera_id = request.args.get("camera_id", type=int)
    camera_name = CAMERA_NAME_MAP.get(camera_id) if camera_id in CAMERA_NAME_MAP else "All Cameras"

    rows = get_last_7_days_report_rows(
        camera_name=None if camera_name == "All Cameras" else camera_name,
        vehicle_type=vehicle_type,
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
        limit=int(request.args.get("limit", 2000)),
    )

    pdf_buffer = _build_report_pdf(rows, vehicle_type, camera_name)

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"last_7_days_{vehicle_type}_report.pdf",
    )


@main.route("/api/camera_comparison")
def api_camera_comparison():
    cached = _cache_get("camera_comparison", 5)
    if cached is not None:
        return jsonify(cached)
    return jsonify(_cache_set("camera_comparison", get_camera_comparison_stats()))


@main.route("/api/count_diagnostic")
def api_count_diagnostic():
    """Diagnostic endpoint to compare dashboard total vs. sum of all cameras."""
    date_value = request.args.get("date")
    cache_key = f"count_diagnostic:{date_value or 'today'}"
    cached = _cache_get(cache_key, 5)
    if cached is not None:
        return jsonify(cached)
    data = get_camera_sum_vs_dashboard(date_value=date_value)
    return jsonify(_cache_set(cache_key, data))


@main.route("/api/remaining_vehicles")
def api_remaining_vehicles():
    group = request.args.get("group", "kiari")
    return jsonify(get_remaining_vehicle_rows(group=group))


@main.route("/api/vehicle_master", methods=["GET"])
def api_vehicle_master_rows():
    return jsonify({"success": True, "rows": get_vehicle_master_rows()})


@main.route("/api/vehicle_master", methods=["POST"])
def api_vehicle_master_save():
    data = request.get_json(silent=True) or {}
    result = add_or_update_vehicle_master(data)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@main.route("/api/vehicle_info/<license_plate>")
def api_vehicle_info(license_plate):
    info = get_vehicle_master_info(license_plate)
    return jsonify({"success": bool(info), "info": info or {}})


@main.route("/api/update_log", methods=["POST"])
def api_update_log():
    data = request.get_json(silent=True) or {}
    result = update_vehicle_log_row(data)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@main.route("/api/delete_log", methods=["POST"])
def api_delete_log():
    data = request.get_json(silent=True) or {}
    result = delete_vehicle_log_row(data.get("source_table"), data.get("id"))
    status = 200 if result.get("success") else 400
    return jsonify(result), status


# ============================================================
# LICENSE SEARCH + BLACKLIST VEHICLE ALERT ROUTES - FIXED
# ============================================================
# Reason for previous 500 error:
# _build_union_logs_query returns license_img and veh_img columns.
# It does NOT return plate and vehicle directly.

def _norm_plate_for_search(v):
    return "".join(ch for ch in str(v or "").upper().strip() if ch.isalnum())


def _ensure_blacklist_table():
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blacklisted_vehicles (
            id SERIAL PRIMARY KEY,
            license_plate VARCHAR(64) NOT NULL UNIQUE,
            remarks VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


@main.route("/api/search_license")
@main.route("/search_license")
def search_license():
    query = _norm_plate_for_search(request.args.get("query", ""))
    if not query:
        return jsonify([])

    conn = None
    cur = None
    try:
        ensure_database()
        ensure_table()

        conn = _get_connection()
        union_sql = _build_union_logs_query(conn)
        cur = conn.cursor(dictionary=True)

        sql = f"""
            SELECT
                source_table,
                camera_name,
                track_id,
                class_name,
                class_id,
                avg_speed,
                license,
                time,
                log_date,
                license_img,
                veh_img,
                source_type
            FROM ({union_sql}) AS logs
            WHERE REPLACE(REPLACE(REPLACE(UPPER(COALESCE(license,'')), ' ', ''), '-', ''), '/', '') LIKE %s
            ORDER BY log_date DESC, time DESC
            LIMIT 100
        """

        cur.execute(sql, (f"%{query}%",))
        rows = cur.fetchall()

        results = []
        for r in rows:
            time_value = r.get("time")
            if hasattr(time_value, "strftime"):
                time_value = time_value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                time_value = str(time_value or "")

            results.append({
                "source_table": r.get("source_table", ""),
                "source_type": r.get("source_type", ""),
                "plate_no": r.get("license", ""),
                "license": r.get("license", ""),
                "type": r.get("class_name", ""),
                "class_name": r.get("class_name", ""),
                "class_id": r.get("class_id", ""),
                "avg_speed": r.get("avg_speed", ""),
                "speed": r.get("avg_speed", ""),
                "camera_name": r.get("camera_name", ""),
                "timestamp": time_value,
                "time": time_value,
                "log_date": str(r.get("log_date", "")),
                "plate_feature": r.get("license_img", ""),
                "vehicle_body_matting": r.get("veh_img", ""),
                "plate": r.get("license_img", ""),
                "vehicle": r.get("veh_img", ""),
                "license_img": r.get("license_img", ""),
                "veh_img": r.get("veh_img", ""),
                "color": "",
                "logo": "",
                "region": "",
            })

        return jsonify(results)

    except Exception as e:
        print("search_license error:", e)
        return jsonify({"success": False, "message": str(e), "rows": []}), 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@main.route("/api/blacklist", methods=["GET", "POST"])
def api_blacklist():
    _ensure_blacklist_table()

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        plate = _norm_plate_for_search(data.get("license_plate", ""))
        remarks = str(data.get("remarks", "")).strip()

        if not plate:
            return jsonify({"success": False, "message": "License plate required"}), 400

        conn = _get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO blacklisted_vehicles (license_plate, remarks)
            VALUES (%s, %s)
            ON CONFLICT (license_plate) DO UPDATE SET remarks = EXCLUDED.remarks
        """, (plate, remarks))
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True})

    conn = _get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT license_plate, remarks, created_at
        FROM blacklisted_vehicles
        ORDER BY created_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    for r in rows:
        r["created_at"] = str(r.get("created_at", ""))

    return jsonify({"success": True, "rows": rows})


@main.route("/api/blacklist/<plate>", methods=["DELETE"])
def api_delete_blacklist(plate):
    _ensure_blacklist_table()
    plate = _norm_plate_for_search(plate)

    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM blacklisted_vehicles WHERE license_plate = %s", (plate,))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"success": True})


@main.route("/api/blacklist_alerts")
def api_blacklist_alerts():
    """
    Dashboard polls this route.
    If any blacklisted plate is found in any camera DB logs,
    frontend plays /static/siren.mp3.
    """
    _ensure_blacklist_table()

    conn = None
    cur = None
    try:
        ensure_database()
        ensure_table()

        conn = _get_connection()
        union_sql = _build_union_logs_query(conn)
        cur = conn.cursor(dictionary=True)

        sql = f"""
            SELECT
                b.license_plate,
                b.remarks,
                logs.camera_name,
                logs.license,
                logs.time,
                logs.log_date,
                logs.license_img,
                logs.veh_img,
                logs.source_table
            FROM blacklisted_vehicles b
            JOIN ({union_sql}) AS logs
              ON REPLACE(REPLACE(REPLACE(UPPER(COALESCE(logs.license,'')), ' ', ''), '-', ''), '/', '') = b.license_plate
            WHERE logs.log_date >= CURRENT_DATE - INTERVAL '1 day'
            ORDER BY logs.log_date DESC, logs.time DESC
            LIMIT 20
        """

        cur.execute(sql)
        rows = cur.fetchall()

        alerts = []
        for r in rows:
            time_value = r.get("time")
            if hasattr(time_value, "strftime"):
                time_value = time_value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                time_value = str(time_value or "")

            alerts.append({
                "license_plate": r.get("license_plate", ""),
                "remarks": r.get("remarks", ""),
                "camera_name": r.get("camera_name", ""),
                "license": r.get("license", ""),
                "time": time_value,
                "log_date": str(r.get("log_date", "")),
                "plate": r.get("license_img", ""),
                "vehicle": r.get("veh_img", ""),
                "license_img": r.get("license_img", ""),
                "veh_img": r.get("veh_img", ""),
                "source_table": r.get("source_table", ""),
            })

        return jsonify({"success": True, "alerts": alerts})

    except Exception as e:
        print("blacklist_alerts error:", e)
        return jsonify({"success": False, "alerts": [], "message": str(e)}), 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
