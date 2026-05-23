import os

from flask import Blueprint, Response, jsonify, request
from werkzeug.utils import secure_filename

from core.common import CAMERA_NAME_MAP
from preview_pipeline import (
    register_preview_urls,
    start_preview_camera,
    stop_preview_camera,
    get_preview_logs,
    get_preview_snapshot,
    generate_preview_frames,
)
from flask_app.blueprints.route_utils import (
    UPLOAD_FOLDER,
    RTSP_PIPELINE_ERROR,
    VIDEO_PIPELINE_ERROR,
    start_rtsp_camera,
    generate_frames,
    get_latest_frame_jpeg,
    start_uploaded_video,
    generate_uploaded_video_frames,
    pipeline_unavailable_response,
)

bp = Blueprint("streams", __name__)

@bp.route("/upload_video", methods=["POST"])
def upload_video():
    if VIDEO_PIPELINE_ERROR is not None:
        return pipeline_unavailable_response("Uploaded video YOLO", VIDEO_PIPELINE_ERROR)

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


@bp.route("/video_feed")
def video_feed():
    if VIDEO_PIPELINE_ERROR is not None:
        return pipeline_unavailable_response("Uploaded video YOLO", VIDEO_PIPELINE_ERROR)

    return Response(
        generate_uploaded_video_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@bp.route("/start_streams", methods=["POST"])
def start_streams():
    data = request.get_json(silent=True) or {}
    urls = data.get("urls", [])
    register_preview_urls(urls)
    return jsonify({
        "success": True,
        "message": "RTSP preview URLs registered. No background YOLO processing was started.",
    })


@bp.route("/start_camera", methods=["POST"])
def start_camera():
    return preview_start_camera()


@bp.route("/preview/start_camera", methods=["POST"])
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


@bp.route("/preview/stop_camera", methods=["POST"])
def preview_stop_camera():
    data = request.get_json(silent=True) or {}
    camera_id = data.get("camera_id")
    if not isinstance(camera_id, int) or camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id."}), 400
    stop_preview_camera(camera_id)
    return jsonify({"success": True, "message": f"Camera {camera_id} preview stopped."})


@bp.route("/api/preview_logs")
def api_preview_logs():
    camera_id = request.args.get("camera_id", type=int)
    limit = request.args.get("limit", default=100, type=int)
    if camera_id is not None and camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "logs": [], "message": "Invalid camera id"}), 400
    return jsonify({"success": True, "logs": get_preview_logs(limit=limit, camera_id=camera_id)})


@bp.route("/yolo/start_camera", methods=["POST"])
def yolo_start_camera():
    if RTSP_PIPELINE_ERROR is not None:
        return pipeline_unavailable_response("RTSP YOLO", RTSP_PIPELINE_ERROR)

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


@bp.route("/camera_feed/<int:camera_id>")
def camera_feed(camera_id):
    if camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id"}), 400

    return Response(
        generate_preview_frames(camera_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@bp.route("/yolo/camera_feed/<int:camera_id>")
def yolo_camera_feed(camera_id):
    if RTSP_PIPELINE_ERROR is not None:
        return pipeline_unavailable_response("RTSP YOLO", RTSP_PIPELINE_ERROR)

    if camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id"}), 400

    return Response(
        generate_frames(camera_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@bp.route("/camera_snapshot/<int:camera_id>")
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


@bp.route("/preview/snapshot/<int:camera_id>")
def preview_snapshot(camera_id):
    return camera_snapshot(camera_id)


@bp.route("/preview/feed/<int:camera_id>")
def preview_feed(camera_id):
    return camera_feed(camera_id)


@bp.route("/yolo/camera_snapshot/<int:camera_id>")
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
