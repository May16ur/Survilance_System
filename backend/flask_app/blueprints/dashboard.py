from flask import Blueprint, jsonify, request

from core.common import (
    CAMERA_NAME_MAP,
    get_dashboard_stats,
    get_camera_comparison_stats,
    get_remaining_vehicle_rows,
    get_camera_today_db_stats,
    get_camera_sum_vs_dashboard,
)
from flask_app.blueprints.route_utils import cache_get, cache_set

bp = Blueprint("dashboard", __name__)

@bp.route("/dashboard_full")
def dashboard_full():
    camera_id = request.args.get("camera_id", type=int)
    camera_name = CAMERA_NAME_MAP.get(camera_id) if camera_id in CAMERA_NAME_MAP else None
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    cache_key = f"dashboard_full:{camera_name or 'all'}:{start_date or ''}:{end_date or ''}"
    cached = cache_get(cache_key, 15)
    if cached is not None:
        return jsonify(cached)
    data = get_dashboard_stats(
        camera_name=camera_name,
        start_date=start_date,
        end_date=end_date,
    )
    return jsonify(cache_set(cache_key, data))


@bp.route("/api/camera_dashboard/<int:camera_id>")
def api_camera_dashboard(camera_id):
    if camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id"}), 400

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    cache_key = f"camera_dashboard:{camera_id}:{start_date or ''}:{end_date or ''}"
    cached = cache_get(cache_key, 20)
    if cached is not None:
        return jsonify(cached)

    data = get_dashboard_stats(
        camera_name=CAMERA_NAME_MAP[camera_id],
        start_date=start_date,
        end_date=end_date,
    )
    return jsonify(cache_set(cache_key, data))


@bp.route("/api/camera_today_stats/<int:camera_id>")
def api_camera_today_stats(camera_id):
    """Camera popup counter from DB. Uses requested date, or latest DB date for that camera."""
    if camera_id not in CAMERA_NAME_MAP:
        return jsonify({"success": False, "message": "Invalid camera id", "today_mil": 0, "today_civil": 0, "today_total": 0}), 400

    date_value = request.args.get("date") or request.args.get("start_date")
    cache_key = f"camera_today:{camera_id}:{date_value or 'latest'}"
    cached = cache_get(cache_key, 10)
    if cached is not None:
        return jsonify(cached)

    data = get_camera_today_db_stats(
        camera_id=camera_id,
        camera_name=CAMERA_NAME_MAP[camera_id],
        date_value=date_value,
    )
    return jsonify(cache_set(cache_key, data))

@bp.route("/api/camera_comparison")
def api_camera_comparison():
    cached = cache_get("camera_comparison", 5)
    if cached is not None:
        return jsonify(cached)
    return jsonify(cache_set("camera_comparison", get_camera_comparison_stats()))


@bp.route("/api/count_diagnostic")
def api_count_diagnostic():
    """Diagnostic endpoint to compare dashboard total vs. sum of all cameras."""
    date_value = request.args.get("date")
    cache_key = f"count_diagnostic:{date_value or 'today'}"
    cached = cache_get(cache_key, 5)
    if cached is not None:
        return jsonify(cached)
    data = get_camera_sum_vs_dashboard(date_value=date_value)
    return jsonify(cache_set(cache_key, data))


@bp.route("/api/remaining_vehicles")
def api_remaining_vehicles():
    group = request.args.get("group", "kiari")
    return jsonify(get_remaining_vehicle_rows(group=group))
