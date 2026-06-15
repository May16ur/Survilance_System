from io import BytesIO
import datetime
import os
from urllib.parse import unquote, urlparse
from urllib.request import urlopen

from flask import Blueprint, jsonify, request, send_file

from core.common import CAMERA_NAME_MAP, display_unit_for_class, get_last_7_days_report_rows
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
        "start_date": start_date,
        "end_date": end_date,
        "total": len(rows),
        "rows": rows,
    }))


STATIC_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))


def _pdf_text(value, paragraph_style, Paragraph):
    text = str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(text or "-", paragraph_style)


def _pdf_image(value, width, height, Image):
    image_value = str(value or "").strip()
    if not image_value:
        return "No image"

    parsed = urlparse(image_value)
    path_value = unquote(parsed.path or image_value)
    local_path = None

    if path_value.startswith("/static/"):
        candidate = os.path.abspath(os.path.join(STATIC_ROOT, path_value[len("/static/"):].lstrip("/\\")))
        if os.path.commonpath([STATIC_ROOT, candidate]) == STATIC_ROOT:
            local_path = candidate
    elif path_value.startswith("static/"):
        candidate = os.path.abspath(os.path.join(STATIC_ROOT, path_value[len("static/"):].lstrip("/\\")))
        if os.path.commonpath([STATIC_ROOT, candidate]) == STATIC_ROOT:
            local_path = candidate
    elif os.path.isabs(image_value):
        local_path = image_value

    try:
        if local_path and os.path.isfile(local_path):
            return Image(local_path, width=width, height=height)
        if parsed.scheme in {"http", "https"}:
            with urlopen(image_value, timeout=3) as response:
                return Image(BytesIO(response.read()), width=width, height=height)
    except Exception:
        pass
    return "No image"


def _build_report_pdf(rows, vehicle_type, camera_name, start_date, end_date):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A3
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Image, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except Exception as e:
        raise RuntimeError(f"PDF report generation is unavailable: {e}") from e

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A3),
        leftMargin=28,
        rightMargin=28,
        topMargin=26,
        bottomMargin=26,
    )

    styles = getSampleStyleSheet()
    story = []

    range_text = start_date if start_date == end_date else f"{start_date} to {end_date}"
    vehicle_label = {"mil": "Mil", "civil": "Civil", "all": "All"}.get(vehicle_type, vehicle_type.title())
    title_text = f"Vehicle Logs - {vehicle_label} - {camera_name}"
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.black,
    )
    meta_style = ParagraphStyle(
        "ReportMeta",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=9,
        textColor=colors.HexColor("#4b5563"),
    )
    cell_style = ParagraphStyle(
        "ReportCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9,
        textColor=colors.black,
    )

    story.append(Paragraph(title_text, title_style))
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph(f"{range_text} | Total records: {len(rows)}", meta_style))
    story.append(Spacer(1, 0.35 * inch))

    table_data = [[
        "Track",
        "Class",
        "Speed",
        "License",
        "Unit",
        "Time",
        "Camera",
        "Source",
        "Plate",
        "Vehicle",
    ]]

    for row in rows:
        speed = str(row.get("avg_speed") or row.get("speed") or "").strip()
        if speed and "km" not in speed.lower():
            speed = f"{speed} km/h"
        unit = display_unit_for_class(row.get("unit"), row.get("class_name"), row.get("class_id"))
        table_data.append([
            _pdf_text(row.get("track_id"), cell_style, Paragraph),
            _pdf_text(row.get("class_name"), cell_style, Paragraph),
            _pdf_text(speed, cell_style, Paragraph),
            _pdf_text(row.get("license"), cell_style, Paragraph),
            _pdf_text(unit, cell_style, Paragraph),
            _pdf_text(row.get("time"), cell_style, Paragraph),
            _pdf_text(row.get("camera_name"), cell_style, Paragraph),
            _pdf_text(row.get("source_type") or row.get("source_table"), cell_style, Paragraph),
            _pdf_image(row.get("plate") or row.get("license_img") or row.get("plate_img"), 1.25 * inch, 0.62 * inch, Image),
            _pdf_image(row.get("vehicle") or row.get("veh_img") or row.get("vehicle_img"), 1.45 * inch, 0.72 * inch, Image),
        ])

    col_widths = [
        1.15 * inch,
        1.10 * inch,
        0.90 * inch,
        1.35 * inch,
        0.75 * inch,
        1.65 * inch,
        1.85 * inch,
        1.20 * inch,
        1.40 * inch,
        1.60 * inch,
    ]

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="CENTER")

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f2a44")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#c5d2df")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (2, -1), "CENTER"),
        ("ALIGN", (4, 1), (4, -1), "CENTER"),
        ("ALIGN", (8, 1), (9, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
            colors.white,
            colors.HexColor("#f6f9fc"),
        ]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
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
    end_date = request.args.get("end_date") or datetime.date.today().strftime("%Y-%m-%d")
    start_date = request.args.get("start_date") or (
        datetime.datetime.strptime(end_date, "%Y-%m-%d").date() - datetime.timedelta(days=6)
    ).strftime("%Y-%m-%d")

    rows = get_last_7_days_report_rows(
        camera_name=None if camera_name == "All Cameras" else camera_name,
        vehicle_type=vehicle_type,
        start_date=start_date,
        end_date=end_date,
        limit=int(request.args.get("limit", 2000)),
    )

    try:
        pdf_buffer = _build_report_pdf(rows, vehicle_type, camera_name, start_date, end_date)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"vehicle_report_{start_date}_to_{end_date}_{vehicle_type}.pdf",
    )
