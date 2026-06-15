import datetime

from flask import Blueprint, jsonify, request

from core.common import (
    CAMERA_NAME_MAP,
    get_dashboard_stats,
    get_camera_comparison_stats,
    get_remaining_vehicle_rows,
    get_camera_today_db_stats,
    get_all_camera_range_stats,
    get_camera_sum_vs_dashboard,
    get_sunday_military_report,
    TCP_PAIR_MAP,
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


@bp.route("/api/camera_range_stats")
def api_camera_range_stats():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    cache_key = f"camera_range_stats:{start_date or ''}:{end_date or ''}"
    cached = cache_get(cache_key, 20)
    if cached is not None:
        return jsonify(cached)
    return jsonify(cache_set(cache_key, get_all_camera_range_stats(start_date=start_date, end_date=end_date)))


@bp.route("/api/camera_comparison")
def api_camera_comparison():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    cache_key = f"camera_comparison:{start_date or ''}:{end_date or ''}"
    cached = cache_get(cache_key, 30)
    if cached is not None:
        return jsonify(cached)
    return jsonify(cache_set(cache_key, get_camera_comparison_stats(start_date=start_date, end_date=end_date)))


@bp.route("/api/count_diagnostic")
def api_count_diagnostic():
    """Diagnostic endpoint to compare dashboard total vs. sum of all cameras."""
    date_value = request.args.get("date")
    cache_key = f"count_diagnostic:{date_value or 'today'}"
    cached = cache_get(cache_key, 30)
    if cached is not None:
        return jsonify(cached)
    data = get_camera_sum_vs_dashboard(date_value=date_value)
    return jsonify(cache_set(cache_key, data))


@bp.route("/api/remaining_vehicles")
def api_remaining_vehicles():
    group = request.args.get("group", "kiari")
    return jsonify(get_remaining_vehicle_rows(
        group=group,
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
    ))


@bp.route("/api/tcp_dashboard/<tcp_name>")
def api_tcp_dashboard(tcp_name):
    key = str(tcp_name or "").strip().lower()
    if key not in TCP_PAIR_MAP:
        return jsonify({"success": False, "message": "Invalid TCP name"}), 400

    today = datetime.date.today()
    try:
        end = datetime.datetime.strptime(request.args.get("end_date"), "%Y-%m-%d").date() if request.args.get("end_date") else today
        start = datetime.datetime.strptime(request.args.get("start_date"), "%Y-%m-%d").date() if request.args.get("start_date") else end - datetime.timedelta(days=6)
    except ValueError:
        return jsonify({"success": False, "message": "Dates must use YYYY-MM-DD"}), 400
    if start > end:
        start, end = end, start
    camera_names = TCP_PAIR_MAP[key]
    camera_breakdown = []
    camera_stats_rows = []
    for camera_name in camera_names:
        camera_stats = get_dashboard_stats(
            camera_name=camera_name,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )
        camera_stats_rows.append(camera_stats)
        camera_breakdown.append({
            "camera_name": camera_name,
            "mil": int(camera_stats.get("total_mil") or 0),
            "civil": int(camera_stats.get("total_civil") or 0),
            "mil_overspeed": int(camera_stats.get("mil_overspeed") or 0),
            "mil_within_limit": int(camera_stats.get("mil_within_limit") or 0),
            "civil_overspeed": int(camera_stats.get("civil_overspeed") or 0),
            "civil_within_limit": int(camera_stats.get("civil_within_limit") or 0),
        })
    dates = camera_stats_rows[0].get("dates", []) if camera_stats_rows else []
    def series_value(stats, field, index):
        values = stats.get(field) or []
        return int(values[index] or 0) if index < len(values) else 0

    mil = [
        sum(series_value(stats, "mil", index) for stats in camera_stats_rows)
        for index in range(len(dates))
    ]
    civil = [
        sum(series_value(stats, "civil", index) for stats in camera_stats_rows)
        for index in range(len(dates))
    ]
    total_mil = sum(mil)
    total_civil = sum(civil)
    mil_overspeed = sum(int(stats.get("mil_overspeed") or 0) for stats in camera_stats_rows)
    civil_overspeed = sum(int(stats.get("civil_overspeed") or 0) for stats in camera_stats_rows)

    return jsonify({
        "success": True,
        "tcp_name": key,
        "dates": dates,
        "mil": mil,
        "civil": civil,
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "today_mil": mil[-1] if mil else 0,
        "today_civil": civil[-1] if civil else 0,
        "total_mil": total_mil,
        "total_civil": total_civil,
        "mil_overspeed": mil_overspeed,
        "mil_within_limit": max(total_mil - mil_overspeed, 0),
        "civil_overspeed": civil_overspeed,
        "civil_within_limit": max(total_civil - civil_overspeed, 0),
        "week_total": total_mil + total_civil,
        "counts_consistent": (
            mil_overspeed + max(total_mil - mil_overspeed, 0) == total_mil
            and civil_overspeed + max(total_civil - civil_overspeed, 0) == total_civil
            and sum(mil) + sum(civil) == total_mil + total_civil
        ),
        "camera_breakdown": camera_breakdown,
    })


@bp.route("/api/sunday_military_report")
def api_sunday_military_report():
    date_value = request.args.get("date")
    limit = max(50, min(request.args.get("limit", default=500, type=int), 2000))
    cache_key = f"sunday_military:{date_value or 'latest'}:{limit}"
    cached = cache_get(cache_key, 30)
    if cached is not None:
        return jsonify(cached)
    return jsonify(cache_set(cache_key, get_sunday_military_report(limit=limit, date_value=date_value)))
