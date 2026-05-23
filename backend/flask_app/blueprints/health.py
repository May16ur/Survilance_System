import datetime

from flask import Blueprint, jsonify

from core.common import CAMERA_NAME_MAP, check_mysql_connection
from flask_app.blueprints.route_utils import RTSP_PIPELINE_ERROR, VIDEO_PIPELINE_ERROR

bp = Blueprint("health", __name__)

@bp.route("/api/health")
def api_health():
    mysql = check_mysql_connection(log=False)
    return jsonify({
        "success": True,
        "service": "e-TCP Surveillance API",
        "time": datetime.datetime.now().isoformat(),
        "mysql": mysql,
        "cp_plus_anpr": "ready",
        "plate_extract": "embedded_jpeg",
        "rtsp_yolo": "ready" if RTSP_PIPELINE_ERROR is None else f"unavailable: {RTSP_PIPELINE_ERROR}",
        "upload_yolo": "ready" if VIDEO_PIPELINE_ERROR is None else f"unavailable: {VIDEO_PIPELINE_ERROR}",
    })


@bp.route("/api/cameras")
def api_cameras():
    return jsonify({
        "success": True,
        "cameras": [
            {"id": camera_id, "name": camera_name}
            for camera_id, camera_name in CAMERA_NAME_MAP.items()
        ],
    })
