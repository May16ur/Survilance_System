from flask import Blueprint, jsonify, request

from core.common import (
    add_or_update_vehicle_master,
    import_vehicle_details_from_excel,
    get_vehicle_master_rows,
    get_vehicle_master_info,
    update_vehicle_log_row,
    delete_vehicle_log_row,
)
from flask_app.blueprints.route_utils import clear_api_cache

bp = Blueprint("vehicles", __name__)

@bp.route("/api/vehicle_master", methods=["GET"])
def api_vehicle_master_rows():
    return jsonify({"success": True, "rows": get_vehicle_master_rows()})


@bp.route("/api/vehicle_master", methods=["POST"])
def api_vehicle_master_save():
    data = request.get_json(silent=True) or {}
    result = add_or_update_vehicle_master(data)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@bp.route("/api/vehicle_master/import_excel", methods=["POST"])
def api_vehicle_master_import_excel():
    data = request.get_json(silent=True) or {}
    result = import_vehicle_details_from_excel(data.get("path"))
    if result.get("success"):
        clear_api_cache()
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@bp.route("/api/vehicle_info/<license_plate>")
def api_vehicle_info(license_plate):
    info = get_vehicle_master_info(license_plate)
    return jsonify({"success": bool(info), "info": info or {}})


@bp.route("/api/update_log", methods=["POST"])
def api_update_log():
    data = request.get_json(silent=True) or {}
    result = update_vehicle_log_row(data)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@bp.route("/api/delete_log", methods=["POST"])
def api_delete_log():
    data = request.get_json(silent=True) or {}
    result = delete_vehicle_log_row(data.get("source_table") or "vehicle_logs", data.get("id"))
    status = 200 if result.get("success") else 400
    return jsonify(result), status
