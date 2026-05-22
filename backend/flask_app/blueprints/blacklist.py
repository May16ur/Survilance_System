from flask import Blueprint, jsonify, request

from core.common import (
    _get_connection,
    ensure_database,
    ensure_table,
    _build_union_logs_query,
)

bp = Blueprint("blacklist", __name__)

def _norm_plate_for_search(v):
    return "".join(ch for ch in str(v or "").upper().strip() if ch.isalnum())


def _ensure_blacklist_table():
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blacklisted_vehicles (
            id INT AUTO_INCREMENT PRIMARY KEY,
            license_plate VARCHAR(64) NOT NULL UNIQUE,
            remarks VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


@bp.route("/api/search_license")
@bp.route("/search_license")
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


@bp.route("/api/blacklist", methods=["GET", "POST"])
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
            ON DUPLICATE KEY UPDATE remarks = VALUES(remarks)
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


@bp.route("/api/blacklist/<plate>", methods=["DELETE"])
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


@bp.route("/api/blacklist_alerts")
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
            WHERE logs.log_date >= DATE_SUB(CURDATE(), INTERVAL 1 DAY)
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
