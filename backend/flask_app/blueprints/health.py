import datetime

from flask import Blueprint, jsonify

from core.common import CAMERA_NAME_MAP, check_mysql_connection
from flask_app.blueprints.route_utils import RTSP_PIPELINE_ERROR, VIDEO_PIPELINE_ERROR
from project_config import get_camera_configs, get_frontend_config, get_tcp_pair_configs

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


@bp.route("/api/app_config")
def api_app_config():
    return jsonify({
        "success": True,
        "config": get_frontend_config(),
    })


@bp.route("/api/cameras")
def api_cameras():
    config_by_id = {int(row["id"]): row for row in get_camera_configs()}
    return jsonify({
        "success": True,
        "cameras": [
            {
                "id": camera_id,
                "name": camera_name,
                "url": (config_by_id.get(camera_id) or {}).get("rtsp_url", ""),
                "tcp": (config_by_id.get(camera_id) or {}).get("tcp", ""),
                "direction": (config_by_id.get(camera_id) or {}).get("direction", ""),
            }
            for camera_id, camera_name in CAMERA_NAME_MAP.items()
        ],
        "tcp_pairs": get_tcp_pair_configs(),
    })
