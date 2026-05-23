from io import BytesIO

from flask import Blueprint, jsonify, request, send_file

from core.common import CAMERA_NAME_MAP, get_last_7_days_report_rows
from flask_app.blueprints.route_utils import cache_get, cache_set

bp = Blueprint("reports", __name__)

@bp.route("/api/last_7_days_report")
def api_last_7_days_report():
    vehicle_type = request.args.get("vehicle_type", "all")
    camera_id = request.args.get("camera_id", type=int)
    camera_name = CAMERA_NAME_MAP.get(camera_id) if camera_id in CAMERA_NAME_MAP else None
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    limit = max(50, min(int(request.args.get("limit", 2000)), 3000))
    cache_key = f"report:{camera_name or 'all'}:{vehicle_type}:{start_date or ''}:{end_date or ''}:{limit}"
    cached = cache_get(cache_key, 20)
    if cached is not None:
        return jsonify(cached)

    rows = get_last_7_days_report_rows(
        camera_name=camera_name,
        vehicle_type=vehicle_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

    return jsonify(cache_set(cache_key, {
        "vehicle_type": vehicle_type,
        "camera_name": camera_name or "All Cameras",
        "total": len(rows),
        "rows": rows,
    }))


def _build_report_pdf(rows, vehicle_type, camera_name):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A3
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except Exception as e:
        raise RuntimeError(f"PDF report generation is unavailable: {e}") from e

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


@bp.route("/download_last_7_days_report")
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

    try:
        pdf_buffer = _build_report_pdf(rows, vehicle_type, camera_name)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"last_7_days_{vehicle_type}_report.pdf",
    )
