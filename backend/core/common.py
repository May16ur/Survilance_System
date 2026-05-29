import os
import re
import json
import zipfile
import cv2
import numpy as np
import datetime
import threading
import time
from collections import Counter
from xml.etree import ElementTree as ET

import mysql.connector
from mysql.connector import Error
from mysql.connector import pooling

from project_config import get_camera_name_map, get_tcp_pair_map


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
VEHICLE_MODEL_PATH = os.path.join(BASE_DIR, "veh.pt")
LICENSE_MODEL_PATH = os.path.join(BASE_DIR, "best.pt")
VEH_DETAILS_PATH = os.getenv(
    "VEH_DETAILS_PATH",
    os.path.join(PROJECT_ROOT, "datacontrol", "veh_details.xlsx"),
)

LOG_DIR = os.path.join(BASE_DIR, "flask_app", "static", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE_PATH = os.path.join(LOG_DIR, f"logs_{datetime.datetime.now().strftime('%Y%m%d')}.json")

CONFIDENCE_THRESHOLD = 0.10
IOU_THRESHOLD = 0.20
LICENSE_CONFIDENCE_THRESHOLD = 0.10

CLASS_NAMES = {0: "Mil Veh", 1: "Civil Veh"}
NO_RECORD_TEXT = "No record found"


def class_bucket(class_name="", class_id=None):
    text = str(class_name or "").lower()
    if str(class_id) == "0" or "mil" in text:
        return "mil"
    if str(class_id) == "1" or "civil" in text:
        return "civil"
    return ""


def display_unit_for_class(unit="", class_name="", class_id=None):
    unit_text = str(unit or "").strip()
    if unit_text and unit_text.lower() != NO_RECORD_TEXT.lower():
        return unit_text
    bucket = class_bucket(class_name, class_id)
    if bucket == "civil":
        return "Civil"
    if bucket == "mil":
        return "Mil"
    return ""

DEFAULT_CAMERA_NAME_MAP = {
    1: "IGOO TCP to Leh",
    2: "IGOO TCP to Kiari",
    3: "Kiari to Leh",
    4: "Kiari-CThang",
    5: "C/Thang to Kiari",
    6: "C/Thang to Nyoma",
    7: "Nyoma to C/Thang",
    8: "Nyoma to Loma",
    9: "Loma to Nyoma",
    10: "Loma to Hanle",
    11: "Hanle to Loma",
    12: "Hanle to Tasigang",
    13: "Chushul to Tara",
    14: "Chushul to Parma",
}
CAMERA_NAME_MAP = get_camera_name_map() or DEFAULT_CAMERA_NAME_MAP

DEFAULT_TCP_PAIR_MAP = {
    "igoo": ("IGOO TCP to Leh", "IGOO TCP to Kiari"),
    "kiari": ("Kiari to Leh", "Kiari-CThang"),
    "cthang": ("C/Thang to Kiari", "C/Thang to Nyoma"),
    "nyoma": ("Nyoma to C/Thang", "Nyoma to Loma"),
    "loma": ("Loma to Nyoma", "Loma to Hanle"),
    "hanle": ("Hanle to Loma", "Hanle to Tasigang"),
    "chushul": ("Chushul to Tara", "Chushul to Parma"),
}
TCP_PAIR_MAP = get_tcp_pair_map() or DEFAULT_TCP_PAIR_MAP

CAMERA_NAME_ALIASES = {
    "IGOO TCP to Leh": ["IGOO TCP to Leh", "Ego TCP to Leh", "IGOO to Leh", "IGOO TCP to Lay", "IGOO to Lay"],
    "IGOO TCP to Kiari": ["IGOO TCP to Kiari", "Ego TCP to Kiari", "IGOO to Kiari", "IGOO TCP to Kiar", "IGOO to Kiar"],
    "Kiari to Leh": ["Kiari to Leh", "Kiari-Leh", "Kiari to Lay"],
    "Kiari-CThang": ["Kiari-CThang", "Kiari to C/Thang", "Kiari to C'Thang"],
    "C/Thang to Kiari": ["C/Thang to Kiari", "C'Thang to Kiari"],
    "C/Thang to Nyoma": ["C/Thang to Nyoma", "C'Thang to Nyoma"],
    "Nyoma to C/Thang": ["Nyoma to C/Thang", "Nyoma to C'Thang"],
    "Nyoma to Loma": ["Nyoma to Loma"],
    "Loma to Nyoma": ["Loma to Nyoma"],
    "Loma to Hanle": ["Loma to Hanle"],
    "Hanle to Loma": ["Hanle to Loma", "Hanle Loma"],
    "Hanle to Tasigang": ["Hanle to Tasigang", "Hanle toTasiganag", "Hanle to Tasiganag"],
    "Chushul to Tara": ["Chushul to Tara"],
    "Chushul to Parma": ["Chushul to Parma"],
}

def get_camera_aliases(camera_name):
    return list(dict.fromkeys([str(x) for x in CAMERA_NAME_ALIASES.get(camera_name, [camera_name]) if x]))

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", ""),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "vehicle_logsnew"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "connection_timeout": int(os.getenv("MYSQL_CONNECTION_TIMEOUT", "2")),
}
MYSQL_POOL = None
MYSQL_UNAVAILABLE_UNTIL = 0
MYSQL_FAILURE_BACKOFF_SEC = int(os.getenv("MYSQL_FAILURE_BACKOFF_SEC", "10"))
VEHICLE_LOG_UPDATE_WINDOW_SEC = int(os.getenv("ETCP_VEHICLE_LOG_UPDATE_WINDOW_SEC", "300"))
UNKNOWN_TRACK_LOG_UPDATE_WINDOW_SEC = int(os.getenv("ETCP_UNKNOWN_TRACK_LOG_UPDATE_WINDOW_SEC", "1800"))

# Backward-compatible name; routes import this.
TABLE_NAME = "vehicle_logs"

db_lock = threading.Lock()
log_lock = threading.Lock()
logs_dict = {"uploadLogs": {}, "streamLogs": {}}
license_text_cache = {}
vehicle_details_cache = {"mtime": None, "rows": {}}

DEFAULT_CAMERA_POLYGONS = {
    1: np.array([[10, 70], [480, 70], [454, 354], [20, 348]], dtype=np.int32),
    2: np.array([[30, 80], [610, 80], [610, 350], [30, 350]], dtype=np.int32),
    3: np.array([[95, 220], [530, 215], [500, 359], [20, 359]], dtype=np.int32),
    4: np.array([[110, 170], [580, 170], [654, 554], [120, 548]], dtype=np.int32),
    5: np.array([[50, 120], [360, 115], [450, 355], [20, 355]], dtype=np.int32),
    6: np.array([[185, 205], [400, 205], [420, 355], [90, 355]], dtype=np.int32),
    7: np.array([[10, 70], [480, 70], [454, 354], [20, 348]], dtype=np.int32),
    8: np.array([[111, 180], [365, 175], [368, 356], [25, 356]], dtype=np.int32),
    9: np.array([[161, 182], [353, 180], [425, 355], [90, 355]], dtype=np.int32),
    10: np.array([[110, 180], [350, 180], [425, 355], [90, 355]], dtype=np.int32),
    11: np.array([[10, 70], [480, 70], [454, 354], [20, 348]], dtype=np.int32),
    12: np.array([[111, 180], [365, 175], [368, 356], [25, 356]], dtype=np.int32),
    13: np.array([[161, 182], [353, 180], [425, 355], [90, 355]], dtype=np.int32),
    14: np.array([[110, 180], [350, 180], [425, 355], [90, 355]], dtype=np.int32),
}
CAMERA_TARGET_DIMS = {i: {"width": 7, "height": 45} for i in range(1, 15)}
CAMERA_CAPTURE_ZONES = DEFAULT_CAMERA_POLYGONS.copy()
CAMERA_CAPTURE_ZONES[3] = np.array([[35, 288], [500, 282], [488, 359], [22, 359]], dtype=np.int32)

class ViewTransformer:
    def __init__(self, source: np.ndarray, target: np.ndarray) -> None:
        self.m = cv2.getPerspectiveTransform(source.astype(np.float32), target.astype(np.float32))
    def transform_points(self, points: np.ndarray) -> np.ndarray:
        if points.size == 0:
            return points
        reshaped = points.reshape(-1, 1, 2).astype(np.float32)
        transformed = cv2.perspectiveTransform(reshaped, self.m)
        return transformed.reshape(-1, 2)

def get_camera_polygon(camera_id): return DEFAULT_CAMERA_POLYGONS.get(camera_id, DEFAULT_CAMERA_POLYGONS[1])
def get_target_polygon(camera_id=None, width=None, height=None):
    if camera_id is not None:
        dims = CAMERA_TARGET_DIMS.get(camera_id, CAMERA_TARGET_DIMS[1]); width=dims["width"]; height=dims["height"]
    else:
        width = 8 if width is None else width; height = 40 if height is None else height
    return np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]], dtype=np.float32)
def get_capture_zone(camera_id): return CAMERA_CAPTURE_ZONES.get(camera_id, CAMERA_CAPTURE_ZONES[1])
def point_in_polygon(point, polygon): return True if polygon is None else cv2.pointPolygonTest(polygon.astype(np.int32), point, False) >= 0

def convert_to_serializable(obj):
    if isinstance(obj, (np.integer,)): return int(obj)
    if isinstance(obj, (np.floating,)): return float(obj)
    if isinstance(obj, np.ndarray): return obj.tolist()
    raise TypeError(f"Type {type(obj)} not serializable")

def save_logs_dict(data, file_path=LOG_FILE_PATH):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, default=convert_to_serializable)

def _mysql_no_db_connection():
    return mysql.connector.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        port=MYSQL_CONFIG["port"],
        connection_timeout=MYSQL_CONFIG.get("connection_timeout", 2),
    )

def _get_connection():
    global MYSQL_POOL, MYSQL_UNAVAILABLE_UNTIL
    now = time.time()
    if now < MYSQL_UNAVAILABLE_UNTIL:
        remaining = max(1, int(MYSQL_UNAVAILABLE_UNTIL - now))
        raise Error(f"MySQL temporarily unavailable after recent connection failure; retrying in {remaining}s")

    had_pool = MYSQL_POOL is not None
    try:
        if MYSQL_POOL is None:
            MYSQL_POOL = pooling.MySQLConnectionPool(
                pool_name="vehicle_logs_pool",
                pool_size=12,
                pool_reset_session=True,
                **MYSQL_CONFIG,
            )
        return MYSQL_POOL.get_connection()
    except Exception:
        MYSQL_POOL = None
        if not had_pool:
            MYSQL_UNAVAILABLE_UNTIL = time.time() + max(1, MYSQL_FAILURE_BACKOFF_SEC)
            raise
        try:
            conn = mysql.connector.connect(**MYSQL_CONFIG)
            MYSQL_UNAVAILABLE_UNTIL = 0
            return conn
        except Exception:
            MYSQL_UNAVAILABLE_UNTIL = time.time() + max(1, MYSQL_FAILURE_BACKOFF_SEC)
            raise


def check_mysql_connection(log=True):
    started = datetime.datetime.now()
    try:
        conn = _get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT DATABASE() AS db_name, NOW() AS server_time")
        row = cur.fetchone() or {}
        cur.close()
        conn.close()
        elapsed_ms = int((datetime.datetime.now() - started).total_seconds() * 1000)
        result = {
            "connected": True,
            "host": MYSQL_CONFIG["host"],
            "port": MYSQL_CONFIG["port"],
            "database": row.get("db_name") or MYSQL_CONFIG["database"],
            "server_time": _fmt_dt(row.get("server_time")),
            "latency_ms": elapsed_ms,
        }
        if log:
            print(f"[MYSQL] connected {result['host']}:{result['port']}/{result['database']} in {elapsed_ms}ms")
        return result
    except Exception as e:
        result = {
            "connected": False,
            "host": MYSQL_CONFIG["host"],
            "port": MYSQL_CONFIG["port"],
            "database": MYSQL_CONFIG["database"],
            "error": str(e),
        }
        if log:
            print(f"[MYSQL] disconnected {result['host']}:{result['port']}/{result['database']} - {e}")
        return result



def _column_exists(cur, table_name, column_name):
    """Return True if column exists in current MySQL database table."""
    try:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
            """,
            (MYSQL_CONFIG["database"], table_name, column_name),
        )
        row = cur.fetchone()
        return bool(row and row[0] > 0)
    except Exception as e:
        print(f"[DB] _column_exists error for {table_name}.{column_name}:", e)
        return False


def _index_exists(cur, table_name, index_name):
    """Return True if index exists in current MySQL database table."""
    try:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND INDEX_NAME = %s
            """,
            (MYSQL_CONFIG["database"], table_name, index_name),
        )
        row = cur.fetchone()
        return bool(row and row[0] > 0)
    except Exception as e:
        print(f"[DB] _index_exists error for {table_name}.{index_name}:", e)
        return False


def ensure_database():
    conn = None
    try:
        conn = _mysql_no_db_connection(); cur = conn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{MYSQL_CONFIG['database']}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
        )
        conn.commit(); cur.close(); conn.close()
        return True
    except Error as e:
        print("[MYSQL] database setup skipped:", e)
        if conn:
            try: conn.close()
            except Exception: pass
        return False

def _execute_many(cur, statements):
    for sql in statements:
        try: cur.execute(sql)
        except Error as e: print("DB schema statement skipped:", e)

def ensure_table():
    conn = None
    try:
        conn = _get_connection(); cur = conn.cursor()
        statements = [
            """
            CREATE TABLE IF NOT EXISTS camera_master (
                id INT PRIMARY KEY,
                camera_name VARCHAR(120) NOT NULL,
                rtsp_link TEXT,
                tcp_name VARCHAR(50),
                direction_type VARCHAR(20),
                location_x INT DEFAULT 0,
                location_y INT DEFAULT 0,
                is_active TINYINT DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_tcp_name (tcp_name),
                INDEX idx_active (is_active)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS vehicle_logs (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                track_id INT,
                camera_id INT,
                camera_name VARCHAR(120),
                vehicle_class VARCHAR(50),
                class_name VARCHAR(50),
                class_id INT,
                license_plate VARCHAR(50),
                license VARCHAR(50),
                speed VARCHAR(50),
                avg_speed VARCHAR(50),
                vehicle_img VARCHAR(255),
                veh_img VARCHAR(255),
                plate_img VARCHAR(255),
                license_img VARCHAR(255),
                detection_time DATETIME,
                time DATETIME,
                detection_date DATE,
                log_date DATE,
                source_type VARCHAR(30) DEFAULT 'stream',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_camera_date (camera_name, detection_date),
                INDEX idx_camera_id_date (camera_id, detection_date),
                INDEX idx_license_date (license_plate, detection_date),
                INDEX idx_detection_time (detection_time),
                INDEX idx_camera_license_time (camera_name, license_plate, detection_time),
                INDEX idx_class_date (class_id, detection_date),
                INDEX idx_time (time),
                INDEX idx_log_date_time (log_date, time)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS tcp_movements (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                tcp_name VARCHAR(50),
                in_camera VARCHAR(120),
                out_camera VARCHAR(120),
                license_plate VARCHAR(50),
                time_in DATETIME,
                time_out DATETIME,
                speed_in VARCHAR(50),
                speed_out VARCHAR(50),
                vehicle_class VARCHAR(50),
                class_id INT,
                vehicle_img VARCHAR(255),
                plate_img VARCHAR(255),
                status VARCHAR(30) DEFAULT 'IN',
                remarks VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_tcp_status (tcp_name, status),
                INDEX idx_tcp_license (tcp_name, license_plate),
                INDEX idx_license_time (license_plate, time_in, time_out),
                INDEX idx_time_in (time_in),
                INDEX idx_time_out (time_out)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS vehicle_master (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                license_plate VARCHAR(50) NOT NULL,
                license_norm VARCHAR(50) NOT NULL,
                make_model VARCHAR(120),
                vehicle_type VARCHAR(80),
                unit VARCHAR(120),
                driver_name VARCHAR(120),
                remarks VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_license_norm (license_norm),
                INDEX idx_license_plate (license_plate)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS blacklisted_vehicles (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                license_plate VARCHAR(50) NOT NULL,
                license_norm VARCHAR(50) NOT NULL,
                remarks VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_blacklist_license (license_norm),
                INDEX idx_blacklist_plate (license_plate)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        ]
        _execute_many(cur, statements)

        # Self-heal existing vehicle_logs table created with older/new-only schema.
        # This prevents errors like: Unknown column 'class_name' in 'field list'.
        required_vehicle_logs_columns = {
            "track_id": "INT NULL",
            "camera_id": "INT NULL",
            "camera_name": "VARCHAR(120) NULL",
            "vehicle_class": "VARCHAR(50) NULL",
            "class_name": "VARCHAR(50) NULL",
            "class_id": "INT NULL",
            "license_plate": "VARCHAR(50) NULL",
            "license": "VARCHAR(50) NULL",
            "speed": "VARCHAR(50) NULL",
            "avg_speed": "VARCHAR(50) NULL",
            "vehicle_img": "VARCHAR(255) NULL",
            "veh_img": "VARCHAR(255) NULL",
            "plate_img": "VARCHAR(255) NULL",
            "license_img": "VARCHAR(255) NULL",
            "detection_time": "DATETIME NULL",
            "time": "DATETIME NULL",
            "detection_date": "DATE NULL",
            "log_date": "DATE NULL",
            "source_type": "VARCHAR(30) DEFAULT 'stream'",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
        for col_name, col_def in required_vehicle_logs_columns.items():
            if not _column_exists(cur, "vehicle_logs", col_name):
                try:
                    cur.execute(f"ALTER TABLE vehicle_logs ADD COLUMN {col_name} {col_def}")
                    print(f"[DB] Added missing column vehicle_logs.{col_name}")
                except Error as e:
                    print(f"[DB] Column add skipped vehicle_logs.{col_name}:", e)

        # Fill legacy-compatible columns from new columns and vice versa.
        try:
            cur.execute("""
                UPDATE vehicle_logs
                SET
                    class_name = COALESCE(NULLIF(class_name,''), vehicle_class),
                    vehicle_class = COALESCE(NULLIF(vehicle_class,''), class_name),
                    license = COALESCE(NULLIF(license,''), license_plate),
                    license_plate = COALESCE(NULLIF(license_plate,''), license),
                    avg_speed = COALESCE(NULLIF(avg_speed,''), speed),
                    speed = COALESCE(NULLIF(speed,''), avg_speed),
                    time = COALESCE(time, detection_time),
                    detection_time = COALESCE(detection_time, time),
                    log_date = COALESCE(log_date, detection_date, DATE(COALESCE(time, detection_time))),
                    detection_date = COALESCE(detection_date, log_date, DATE(COALESCE(detection_time, time))),
                    veh_img = COALESCE(NULLIF(veh_img,''), vehicle_img),
                    vehicle_img = COALESCE(NULLIF(vehicle_img,''), veh_img),
                    license_img = COALESCE(NULLIF(license_img,''), plate_img),
                    plate_img = COALESCE(NULLIF(plate_img,''), license_img)
            """)
        except Error as e:
            print("[DB] Compatibility column sync skipped:", e)

        # Add indexes if missing; safe for existing tables.
        index_specs = {
            "idx_camera_date": "camera_name, detection_date",
            "idx_camera_id_date": "camera_id, detection_date",
            "idx_license_date": "license_plate, detection_date",
            "idx_detection_time": "detection_time",
            "idx_camera_license_time": "camera_name, license_plate, detection_time",
            "idx_class_date": "class_id, detection_date",
            "idx_time": "time",
            "idx_log_date_time": "log_date, time",
        }
        for idx_name, idx_cols in index_specs.items():
            if not _index_exists(cur, "vehicle_logs", idx_name):
                try:
                    cur.execute(f"ALTER TABLE vehicle_logs ADD INDEX {idx_name} ({idx_cols})")
                    print(f"[DB] Added index {idx_name}")
                except Error as e:
                    print(f"[DB] Index add skipped {idx_name}:", e)

        # Seed camera master without overwriting rtsp_link.
        for cid, cname in CAMERA_NAME_MAP.items():
            tcp_name, direction = _camera_tcp_info(cname)
            cur.execute("""
                INSERT INTO camera_master (id, camera_name, tcp_name, direction_type)
                VALUES (%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE camera_name=VALUES(camera_name), tcp_name=VALUES(tcp_name), direction_type=VALUES(direction_type)
            """, (cid, cname, tcp_name, direction))
        conn.commit(); cur.close(); conn.close()
        return True
    except Error as e:
        print("[MYSQL] table setup skipped:", e)
        if conn:
            try: conn.close()
            except Exception: pass
        return False

def _camera_tcp_info(camera_name):
    name = normalize_camera_name(camera_name)
    for tcp, (in_cam, out_cam) in TCP_PAIR_MAP.items():
        in_aliases = [normalize_camera_name(x) for x in get_camera_aliases(in_cam)]
        out_aliases = [normalize_camera_name(x) for x in get_camera_aliases(out_cam)]
        if name in in_aliases:
            return tcp, "IN"
        if name in out_aliases:
            return tcp, "OUT"
    return "", ""


def _camera_route_label(camera_name):
    text = str(camera_name or "").strip()
    if not text:
        return "opposite camera"
    return re.sub(r"\s+", " ", text.replace("TCP", "")).strip()


def _tcp_out_remark(out_camera, matched=False, unknown=False):
    label = _camera_route_label(out_camera)
    if matched:
        return f"OUT from {label}"
    if unknown:
        return f"Waiting OUT from {label} / OCR UNKNOWN"
    return f"Waiting OUT from {label}"


def camera_name_variants(name): return get_camera_aliases(name)

def normalize_camera_name(name): return str(name or "").strip()

def normalize_plate_text(txt: str) -> str:
    if not txt: return ""
    return "".join(ch for ch in str(txt).upper().strip() if ch.isalnum())

def normalize_match_license(value):
    v = normalize_plate_text(value)
    if not v or v in {"UNKNOWN", "NONE", "NULL", "NAN"} or len(v) < 5: return ""
    military = normalize_military_plate_candidate(v)
    if military:
        return military
    return v

def normalize_plate_for_storage(value):
    v = normalize_plate_text(value)
    if not v or v in {"UNKNOWN", "NONE", "NULL", "NAN"}:
        return ""
    return normalize_military_plate_candidate(v) or v

def _clean_match_license(value): return normalize_match_license(value)

def _license_match_score(a, b):
    a = normalize_match_license(a); b = normalize_match_license(b)
    if not a or not b: return 0
    if a == b: return 100
    if abs(len(a) - len(b)) > 2: return 0
    if len(a) >= 7 and len(b) >= 7 and (a in b or b in a): return 90
    max_len=max(len(a),len(b)); same=sum(1 for i in range(min(len(a),len(b))) if a[i]==b[i])
    return int((same/max_len)*100)

def finalize_license(candidates, class_id):
    """
    Pick the best OCR candidate. Reject impossible state codes like CICF2017.
    license_utils already restores by format; this is final safety.
    """
    cleaned = []
    valid_states = {"JK","LA","WB","TN","CH","DL","NL","MH","MP","AP","HP","AR","PY","GA","UP","GJ","OD","BR","PB","HR","CG","KA","TS","RJ","AS","KL","UK"}
    mil_re = re.compile(r"^(1[2-9]|2[0-6])[NPAFDCB]\d{6}[PMNXYKLWHEA]$")
    civil_res = [
        re.compile(r"^[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}$"),
        re.compile(r"^(LA|JK)\d{2}\d{4}$"),
    ]

    for x in candidates or []:
        val = normalize_plate_text(x)
        if not (7 <= len(val) <= 12):
            continue
        military = normalize_military_plate_candidate(val)
        if military:
            cleaned.append(military)
            continue
        if val[:2] in valid_states and any(p.fullmatch(val) for p in civil_res):
            cleaned.append(val)
            continue

    if not cleaned:
        return "Unknown"

    best_text, count = Counter(cleaned).most_common(1)[0]
    return best_text if best_text else "Unknown"


MIL_RE = re.compile(r"^(1[2-9]|2[0-6])[NPAFDCB]\d{6}[PMNXYKLWHEA]$")
CIVIL_RE_LIST = [
    re.compile(r"^(JK|LA|WB|TN|CH|DL|NL|MH|MP|AP|HP|AR|PY|GA|UP|GJ|OD|BR|PB|HR|CG|KA|TS|RJ|AS|KL|UK)\d{2}[A-Z]{1,3}\d{4}$"),
    re.compile(r"^(LA|JK)\d{2}\d{4}$"),
]

def normalize_military_plate_candidate(plate):
    plate = normalize_plate_text(plate or "").upper()
    if MIL_RE.fullmatch(plate):
        return plate

    # CP Plus/OCR can read the broad arrow as "1". Military plates still have
    # exactly two digits before the first alphabet and end with an alphabet.
    if plate.startswith("1") and MIL_RE.fullmatch(plate[1:]):
        return plate[1:]
    if plate.endswith("1") and MIL_RE.fullmatch(plate[:-1]):
        return plate[:-1]
    return ""


def is_valid_license_text(plate):
    plate = normalize_plate_text(plate or "").upper()
    if not plate or plate in {"UNKNOWN", "NONE", "NULL", "NAN"}:
        return False
    if normalize_military_plate_candidate(plate):
        return True
    return any(pattern.fullmatch(plate) for pattern in CIVIL_RE_LIST)

def class_from_license_rule(plate):
    plate = normalize_plate_text(plate or "").upper()
    if normalize_military_plate_candidate(plate):
        return 0, "Mil Veh"
    for pattern in CIVIL_RE_LIST:
        if pattern.fullmatch(plate):
            return 1, "Civil Veh"
    return None, None


MILITARY_PLATE_COLORS = {"BLACK", "OLIVE", "OLIVEGREEN", "OLIVE GREEN"}
CIVIL_PLATE_COLORS = {"WHITE", "YELLOW", "GREEN", "RED", "BLUE"}
BROAD_ARROW_MARKERS = ("↑", "^", "⇧", "▲", "△")
RTO_STATE_PREFIXES = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
    "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK",
    "UP", "WB",
}


def classify_vehicle_from_anpr(plate, plate_color="", plate_type="", vehicle_type=""):
    """
    Fast CP Plus ANPR classification. Uses text/color metadata only; no YOLO.

    Priority:
      1. Broad-arrow / military plate format.
      2. Existing military/civil plate regex rules.
      3. Plate background color signals.
      4. RTO state/UT prefix.
    """
    raw_plate = str(plate or "").upper().strip()
    norm_plate = normalize_plate_text(raw_plate)
    color = str(plate_color or "").upper().replace("-", " ").strip()
    color_compact = color.replace(" ", "")
    plate_type_text = str(plate_type or "").upper()
    vehicle_type_text = str(vehicle_type or "").upper()

    if raw_plate.startswith(BROAD_ARROW_MARKERS) or any(raw_plate.startswith(marker) for marker in BROAD_ARROW_MARKERS):
        return 0, "Mil Veh", "broad_arrow"

    rule_cls_id, rule_class_name = class_from_license_rule(raw_plate)
    if rule_cls_id is not None:
        return rule_cls_id, rule_class_name, "plate_pattern"

    if color in MILITARY_PLATE_COLORS or color_compact in MILITARY_PLATE_COLORS:
        return 0, "Mil Veh", "military_plate_color"

    if "ARMY" in plate_type_text or "MIL" in plate_type_text or "DEFENCE" in plate_type_text:
        return 0, "Mil Veh", "camera_plate_type"

    if "ARMY" in vehicle_type_text or "MIL" in vehicle_type_text or "DEFENCE" in vehicle_type_text:
        return 0, "Mil Veh", "camera_vehicle_type"

    if len(norm_plate) >= 2 and norm_plate[:2] in RTO_STATE_PREFIXES:
        return 1, "Civil Veh", "rto_state_prefix"

    if color in CIVIL_PLATE_COLORS or color_compact in CIVIL_PLATE_COLORS:
        return 1, "Civil Veh", "civil_plate_color"

    return 2, "Unknown Veh", "no_confident_signal"


def save_detection_images(track_id, vehicle_img, plate_img, prefix=""):
    date_folder = datetime.datetime.now().strftime("%Y%m%d")
    license_dir = os.path.join(BASE_DIR, "flask_app", "static", date_folder, "license")
    veh_dir = os.path.join(BASE_DIR, "flask_app", "static", date_folder, "veh")
    os.makedirs(license_dir, exist_ok=True); os.makedirs(veh_dir, exist_ok=True)
    filename = f"{prefix}{track_id}_{int(datetime.datetime.now().timestamp()*1000)}.jpeg"
    license_rel_path=f"/static/{date_folder}/license/{filename}"; veh_rel_path=f"/static/{date_folder}/veh/{filename}"
    if vehicle_img is not None and hasattr(vehicle_img, "size") and vehicle_img.size > 0: cv2.imwrite(os.path.join(veh_dir, filename), vehicle_img)
    else: veh_rel_path=""
    if plate_img is not None and hasattr(plate_img, "size") and plate_img.size > 0: cv2.imwrite(os.path.join(license_dir, filename), plate_img)
    else: license_rel_path=""
    return license_rel_path, veh_rel_path

def parse_time_value(time_value):
    if isinstance(time_value, datetime.datetime): return time_value
    if isinstance(time_value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try: return datetime.datetime.strptime(time_value, fmt)
            except ValueError: pass
    return datetime.datetime.now()

def _camera_id_from_name(camera_name):
    for cid, cname in CAMERA_NAME_MAP.items():
        if cname == camera_name: return cid
    return None

def insert_vehicle_log_event(
    track_id,
    class_name,
    avg_speed,
    license_text,
    time_value,
    class_id,
    camera_name,
    source_type="cp_plus_anpr",
    license_img="",
    veh_img="",
):
    """Insert one camera event row. Used for ANPR events that do not have stable tracker ids."""
    try:
        dt = parse_time_value(time_value)
        log_date = dt.date()
        lic = normalize_plate_for_storage(license_text) or "UNKNOWN"
        camera_id = _camera_id_from_name(camera_name)

        try:
            rule_cls_id, rule_class_name = class_from_license_rule(lic)
            if rule_cls_id is not None:
                class_id = rule_cls_id
                class_name = rule_class_name
        except Exception:
            pass

        with db_lock:
            conn = _get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO vehicle_logs
                (
                    track_id,
                    camera_id,
                    camera_name,
                    vehicle_class,
                    class_name,
                    class_id,
                    license_plate,
                    license,
                    speed,
                    avg_speed,
                    vehicle_img,
                    veh_img,
                    plate_img,
                    license_img,
                    detection_time,
                    time,
                    detection_date,
                    log_date,
                    source_type
                )
                VALUES
                (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    int(track_id),
                    camera_id,
                    camera_name,
                    class_name,
                    class_name,
                    int(class_id),
                    lic,
                    lic,
                    avg_speed,
                    avg_speed,
                    veh_img,
                    veh_img,
                    license_img,
                    license_img,
                    dt,
                    dt,
                    log_date,
                    log_date,
                    source_type,
                ),
            )
            inserted_id = cur.lastrowid
            _update_tcp_movement(cur, camera_name, lic, dt, avg_speed, class_name, int(class_id), veh_img, license_img)
            conn.commit()
            cur.close()
            conn.close()
            return {"success": True, "inserted": True, "id": inserted_id}
    except Exception as e:
        print("MySQL event insert error:", e)
        return {"success": False, "message": str(e)}

def upsert_vehicle_log(
    track_id,
    class_name,
    avg_speed,
    license_text,
    time_value,
    class_id,
    camera_name,
    source_type="stream",
    license_img="",
    veh_img="",
):
    """
    Correct vehicle log write logic.

    Rules:
    1. Same camera + same track_id within VEHICLE_LOG_UPDATE_WINDOW_SEC = update same row.
    2. Same camera + same track_id after that window = insert new row.
    3. detection_time/time/log_date/detection_date are never overwritten.
    4. vehicle/plate image paths are never overwritten once saved.
    5. UNKNOWN license may be updated to a valid OCR plate within the 60-second row.
    6. License format corrects class:
       17D205014M -> Mil Veh
       LA02G0195  -> Civil Veh
    """
    try:
        dt = parse_time_value(time_value)
        log_date = dt.date()

        lic = normalize_plate_for_storage(license_text) or "UNKNOWN"
        lic_upper = lic.upper()
        new_license_good = is_valid_license_text(lic_upper)

        camera_id = _camera_id_from_name(camera_name)

        try:
            rule_cls_id, rule_class_name = class_from_license_rule(lic)
            if rule_cls_id is not None:
                class_id = rule_cls_id
                class_name = rule_class_name
        except Exception:
            pass

        with db_lock:
            conn = _get_connection()
            cur = conn.cursor(dictionary=True)

            update_window_sec = VEHICLE_LOG_UPDATE_WINDOW_SEC if new_license_good else UNKNOWN_TRACK_LOG_UPDATE_WINDOW_SEC

            cur.execute(
                """
                SELECT
                    id,
                    license_plate,
                    license,
                    license_img,
                    plate_img,
                    veh_img,
                    vehicle_img,
                    detection_time,
                    time
                FROM vehicle_logs
                WHERE camera_name = %s
                  AND track_id = %s
                  AND detection_date = %s
                  AND ABS(TIMESTAMPDIFF(SECOND, detection_time, %s)) <= %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (camera_name, int(track_id), log_date, dt, update_window_sec),
            )

            existing = cur.fetchone()

            if existing:
                old_license = normalize_plate_text(
                    existing.get("license_plate")
                    or existing.get("license")
                    or ""
                )
                old_license_good = is_valid_license_text(old_license)

                if old_license_good:
                    final_license = old_license
                elif new_license_good:
                    final_license = lic
                else:
                    final_license = "UNKNOWN"

                try:
                    rule_cls_id, rule_class_name = class_from_license_rule(final_license)
                    if rule_cls_id is not None:
                        class_id = rule_cls_id
                        class_name = rule_class_name
                except Exception:
                    pass

                cur.execute(
                    """
                    UPDATE vehicle_logs
                    SET
                        camera_id = %s,
                        vehicle_class = %s,
                        class_name = %s,
                        class_id = %s,
                        license_plate = %s,
                        license = %s,
                        speed = %s,
                        avg_speed = %s,
                        vehicle_img = CASE
                            WHEN (vehicle_img IS NULL OR vehicle_img = '') AND %s <> ''
                            THEN %s ELSE vehicle_img END,
                        veh_img = CASE
                            WHEN (veh_img IS NULL OR veh_img = '') AND %s <> ''
                            THEN %s ELSE veh_img END,
                        plate_img = CASE
                            WHEN (plate_img IS NULL OR plate_img = '') AND %s <> ''
                            THEN %s ELSE plate_img END,
                        license_img = CASE
                            WHEN (license_img IS NULL OR license_img = '') AND %s <> ''
                            THEN %s ELSE license_img END,
                        source_type = %s
                    WHERE id = %s
                    """,
                    (
                        camera_id,
                        class_name,
                        class_name,
                        int(class_id),
                        final_license,
                        final_license,
                        avg_speed,
                        avg_speed,
                        veh_img,
                        veh_img,
                        veh_img,
                        veh_img,
                        license_img,
                        license_img,
                        license_img,
                        license_img,
                        source_type,
                        existing["id"],
                    ),
                )

                tcp_dt = existing.get("detection_time") or existing.get("time") or dt
                tcp_veh_img = existing.get("veh_img") or existing.get("vehicle_img") or veh_img
                tcp_license_img = existing.get("license_img") or existing.get("plate_img") or license_img

                _update_tcp_movement(
                    cur,
                    camera_name,
                    final_license,
                    tcp_dt,
                    avg_speed,
                    class_name,
                    int(class_id),
                    tcp_veh_img,
                    tcp_license_img,
                )

            else:
                cur.execute(
                    """
                    INSERT INTO vehicle_logs
                    (
                        track_id,
                        camera_id,
                        camera_name,
                        vehicle_class,
                        class_name,
                        class_id,
                        license_plate,
                        license,
                        speed,
                        avg_speed,
                        vehicle_img,
                        veh_img,
                        plate_img,
                        license_img,
                        detection_time,
                        time,
                        detection_date,
                        log_date,
                        source_type
                    )
                    VALUES
                    (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        int(track_id),
                        camera_id,
                        camera_name,
                        class_name,
                        class_name,
                        int(class_id),
                        lic,
                        lic,
                        avg_speed,
                        avg_speed,
                        veh_img,
                        veh_img,
                        license_img,
                        license_img,
                        dt,
                        dt,
                        log_date,
                        log_date,
                        source_type,
                    ),
                )

                _update_tcp_movement(
                    cur,
                    camera_name,
                    lic,
                    dt,
                    avg_speed,
                    class_name,
                    int(class_id),
                    veh_img,
                    license_img,
                )

            conn.commit()
            cur.close()
            conn.close()

    except Exception as e:
        print("MySQL insert/update error:", e)


def _update_tcp_movement(cur, camera_name, lic, dt, speed, class_name, class_id, veh_img, license_img):
    """
    Two-way TCP IN/OUT logic.

    Rule:
      - The first camera that detects the license becomes IN.
      - The next opposite camera detection becomes OUT.
      - Works in both directions, e.g. Kiari to Leh -> Kiari-CThang
        and Kiari-CThang -> Kiari to Leh.
    """
    lic = normalize_match_license(lic)
    if not lic or lic.upper() == "UNKNOWN":
        return

    tcp, _direction = _camera_tcp_info(camera_name)
    if not tcp:
        return

    in_cam_fixed, out_cam_fixed = TCP_PAIR_MAP[tcp]
    camera_name_norm = normalize_camera_name(camera_name)
    other_camera = out_cam_fixed if camera_name_norm == normalize_camera_name(in_cam_fixed) else in_cam_fixed

    # Find the nearest pending row for same license from the opposite camera.
    # Do NOT force fixed IN/OUT direction. Time decides direction.
    cur.execute(
        """
        SELECT id, in_camera, out_camera, time_in, speed_in, vehicle_img, plate_img
        FROM tcp_movements
        WHERE tcp_name = %s
          AND license_plate = %s
          AND time_out IS NULL
          AND TRIM(LOWER(in_camera)) <> TRIM(LOWER(%s))
          AND ABS(TIMESTAMPDIFF(HOUR, time_in, %s)) <= 24
        ORDER BY ABS(TIMESTAMPDIFF(SECOND, time_in, %s)) ASC
        LIMIT 1
        """,
        (tcp, lic, camera_name, dt, dt),
    )
    row = cur.fetchone()

    if row:
        row_id = row["id"] if isinstance(row, dict) else row[0]
        existing_in_camera = row["in_camera"] if isinstance(row, dict) else row[1]
        existing_time_in = row["time_in"] if isinstance(row, dict) else row[3]
        existing_speed_in = row.get("speed_in") if isinstance(row, dict) else row[4]
        matched_remark = _tcp_out_remark(camera_name, matched=True)

        # Normal case: existing pending row is earlier, current detection is OUT.
        if existing_time_in is None or existing_time_in <= dt:
            cur.execute(
                """
                UPDATE tcp_movements
                SET
                    out_camera = %s,
                    time_out = %s,
                    speed_out = %s,
                    status = 'OUT',
                    remarks = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (camera_name, dt, speed, matched_remark, row_id),
            )
        else:
            # Late/updated OCR case: current detection is earlier than pending row.
            # Reverse the row so the earliest camera is IN and old pending row becomes OUT.
            cur.execute(
                """
                UPDATE tcp_movements
                SET
                    in_camera = %s,
                    out_camera = %s,
                    time_in = %s,
                    time_out = %s,
                    speed_in = %s,
                    speed_out = %s,
                    vehicle_class = %s,
                    class_id = %s,
                    vehicle_img = CASE WHEN %s <> '' THEN %s ELSE vehicle_img END,
                    plate_img = CASE WHEN %s <> '' THEN %s ELSE plate_img END,
                    status = 'OUT',
                    remarks = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    camera_name,
                    existing_in_camera,
                    dt,
                    existing_time_in,
                    speed,
                    existing_speed_in,
                    class_name,
                    int(class_id),
                    veh_img,
                    veh_img,
                    license_img,
                    license_img,
                    _tcp_out_remark(existing_in_camera, matched=True),
                    row_id,
                ),
            )
        return

    # Avoid creating many pending rows for same license from the same camera close together.
    cur.execute(
        """
        SELECT id
        FROM tcp_movements
        WHERE tcp_name = %s
          AND license_plate = %s
          AND time_out IS NULL
          AND TRIM(LOWER(in_camera)) = TRIM(LOWER(%s))
          AND ABS(TIMESTAMPDIFF(MINUTE, time_in, %s)) <= 10
        ORDER BY time_in DESC
        LIMIT 1
        """,
        (tcp, lic, camera_name, dt),
    )
    same_cam_pending = cur.fetchone()
    if same_cam_pending:
        return

    cur.execute(
        """
        INSERT INTO tcp_movements
        (
            tcp_name,
            in_camera,
            out_camera,
            license_plate,
            time_in,
            speed_in,
            vehicle_class,
            class_id,
            vehicle_img,
            plate_img,
            status,
            remarks
        )
        VALUES
        (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            'IN',
            %s
        )
        """,
        (
            tcp,
            camera_name,
            other_camera,
            lic,
            dt,
            speed,
            class_name,
            int(class_id),
            veh_img,
            license_img,
            _tcp_out_remark(other_camera),
        ),
    )

def _row_to_log(row):
    return {
        "id": row.get("id"),
        "track_id": row.get("track_id"),
        "class_name": row.get("class_name") or row.get("vehicle_class"),
        "avg_speed": row.get("avg_speed") or row.get("speed"),
        "license": row.get("license") or row.get("license_plate"),
        "time": _fmt_dt(row.get("time") or row.get("detection_time")),
        "log_date": _fmt_date(row.get("log_date") or row.get("detection_date")),
        "plate": row.get("license_img") or row.get("plate_img"),
        "vehicle": row.get("veh_img") or row.get("vehicle_img"),
        "license_img": row.get("license_img") or row.get("plate_img"),
        "veh_img": row.get("veh_img") or row.get("vehicle_img"),
        "class_id": row.get("class_id"),
        "camera_name": row.get("camera_name"),
        "source_type": row.get("source_type"),
        "source_table": "vehicle_logs",
    }

def _fmt_dt(v): return v.strftime("%Y-%m-%d %H:%M:%S") if hasattr(v, "strftime") else str(v or "")
def _fmt_date(v): return v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v or "")

def _date_where(start_date=None, end_date=None, col="detection_date"):
    where=[]; params=[]
    if start_date: where.append(f"{col} >= %s"); params.append(start_date)
    if end_date: where.append(f"{col} <= %s"); params.append(end_date)
    return where, params


def _count_class_totals(cur, camera_name, start_date, end_date):
    where = ["detection_date BETWEEN %s AND %s"]
    params = [start_date, end_date]
    if camera_name:
        aliases = get_camera_aliases(camera_name)
        where.append("camera_name IN (" + ",".join(["%s"] * len(aliases)) + ")")
        params.extend(aliases)
    where_sql = "WHERE " + " AND ".join(where)
    cur.execute(
        f"""
            SELECT
                SUM(CASE WHEN class_id=0 OR LOWER(COALESCE(class_name,'')) LIKE '%mil%' THEN 1 ELSE 0 END) AS mil_count,
                SUM(CASE WHEN class_id=1 OR LOWER(COALESCE(class_name,'')) LIKE '%civil%' THEN 1 ELSE 0 END) AS civil_count,
                COUNT(*) AS total_count
            FROM vehicle_logs
            {where_sql}
        """,
        tuple(params),
    )
    row = cur.fetchone() or {}
    return int(row.get('mil_count') or 0), int(row.get('civil_count') or 0), int(row.get('total_count') or 0)


def fetch_recent_logs(camera_name=None, camera_id=None, limit=200, start_date=None, end_date=None):
    try:
        conn=_get_connection()
        cur=conn.cursor(dictionary=True)
        where=[]; params=[]
        if camera_id is not None:
            where.append("camera_id = %s")
            params.append(int(camera_id))
        if camera_name:
            aliases=[str(a).strip().lower() for a in get_camera_aliases(camera_name)]
            where.append("LOWER(TRIM(camera_name)) IN ("+",".join(["%s"]*len(aliases))+")")
            params.extend(aliases)
        dwhere,dparams=_date_where(start_date,end_date)
        where += dwhere; params += dparams
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        cur.execute(f"""
            SELECT
                id,
                track_id,
                class_name,
                avg_speed,
                license,
                time,
                log_date,
                detection_time,
                detection_date,
                license_img,
                plate_img,
                veh_img,
                vehicle_img,
                class_id,
                camera_name,
                source_type
            FROM vehicle_logs
            {where_sql}
            ORDER BY detection_time DESC, id DESC
            LIMIT %s
        """, tuple(params+[int(limit)]))
        rows=enrich_rows_with_vehicle_master([_row_to_log(r) for r in cur.fetchall()])
        cur.close(); conn.close()
        return rows
    except Error as e:
        print("Fetch recent logs error:", e)
        return []

def get_last_7_days_report_rows(camera_name=None, vehicle_type="all", start_date=None, end_date=None, limit=2000):
    if not end_date: end_date=datetime.date.today().strftime("%Y-%m-%d")
    if not start_date: start_date=(datetime.date.today()-datetime.timedelta(days=6)).strftime("%Y-%m-%d")
    rows=fetch_recent_logs(camera_name=camera_name, limit=limit, start_date=start_date, end_date=end_date)
    vehicle_type=(vehicle_type or "all").lower()
    if vehicle_type=="mil": rows=[r for r in rows if str(r.get("class_id"))=="0" or "mil" in str(r.get("class_name","")).lower()]
    elif vehicle_type=="civil": rows=[r for r in rows if str(r.get("class_id"))=="1" or "civil" in str(r.get("class_name","")).lower()]
    return rows

def get_dashboard_stats(camera_name=None, days=7, start_date=None, end_date=None):
    try:
        today=datetime.date.today(); end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else today
        start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else end - datetime.timedelta(days=days-1)
        conn=_get_connection(); cur=conn.cursor(dictionary=True)
        date_expr = "COALESCE(detection_date, log_date, DATE(detection_time), DATE(time))"
        where=[f"{date_expr} BETWEEN %s AND %s"]; params=[start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")]
        if camera_name:
            aliases=[str(a).strip().lower() for a in get_camera_aliases(camera_name)]; where.append("LOWER(TRIM(camera_name)) IN ("+",".join(["%s"]*len(aliases))+")"); params.extend(aliases)
        where_sql="WHERE "+" AND ".join(where)
        cur.execute(f"""
            SELECT {date_expr} as detection_date,
              SUM(CASE WHEN class_id=0 OR LOWER(COALESCE(class_name,'')) LIKE '%mil%' THEN 1 ELSE 0 END) mil_count,
              SUM(CASE WHEN class_id=1 OR LOWER(COALESCE(class_name,'')) LIKE '%civil%' THEN 1 ELSE 0 END) civil_count,
              COUNT(*) total_count
            FROM vehicle_logs {where_sql} GROUP BY {date_expr} ORDER BY {date_expr}
        """, tuple(params))
        trend={_fmt_date(r['detection_date']): r for r in cur.fetchall()}
        dates=[]; mil=[]; civil=[]; total=[]
        d=start
        while d<=end:
            key=d.strftime("%Y-%m-%d"); label=d.strftime("%d-%m"); r=trend.get(key,{})
            dates.append(label); mil.append(int(r.get('mil_count') or 0)); civil.append(int(r.get('civil_count') or 0)); total.append(int(r.get('total_count') or 0)); d+=datetime.timedelta(days=1)

        week_start = max(start, end - datetime.timedelta(days=6))
        month_start = max(start, end.replace(day=1))
        year_start = max(start, end.replace(month=1, day=1))

        week_mil, week_civil, _ = _count_class_totals(cur, camera_name, week_start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        month_mil, month_civil, _ = _count_class_totals(cur, camera_name, month_start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        year_mil, year_civil, _ = _count_class_totals(cur, camera_name, year_start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))

        today_key=today.strftime("%Y-%m-%d")
        if camera_name:
            aliases = [str(a).strip().lower() for a in get_camera_aliases(camera_name)]
            cur.execute(f"SELECT COUNT(*) c, SUM(CASE WHEN class_id=0 OR LOWER(COALESCE(class_name,'')) LIKE '%mil%' THEN 1 ELSE 0 END) m, SUM(CASE WHEN class_id=1 OR LOWER(COALESCE(class_name,'')) LIKE '%civil%' THEN 1 ELSE 0 END) cv FROM vehicle_logs WHERE LOWER(TRIM(camera_name)) IN ("+",".join(['%s']*len(aliases))+f") AND {date_expr}=%s", tuple(aliases+[today_key]))
        else:
            cur.execute(f"SELECT COUNT(*) c, SUM(CASE WHEN class_id=0 OR LOWER(COALESCE(class_name,'')) LIKE '%mil%' THEN 1 ELSE 0 END) m, SUM(CASE WHEN class_id=1 OR LOWER(COALESCE(class_name,'')) LIKE '%civil%' THEN 1 ELSE 0 END) cv FROM vehicle_logs WHERE {date_expr}=%s", (today_key,))
        tr=cur.fetchone() or {}
        logs=fetch_recent_logs(camera_name=camera_name, limit=10)
        cur.close(); conn.close()
        return {"dates":dates,"mil":mil,"civil":civil,"total":total,"today_total":int(tr.get('c') or 0),"today_mil":int(tr.get('m') or 0),"today_civil":int(tr.get('cv') or 0),"week_total":sum(total),"week_mil":sum(mil),"week_civil":sum(civil),"total_mil":sum(mil),"total_civil":sum(civil),"week_pie":[week_mil,week_civil],"month_pie":[month_mil,month_civil],"year_pie":[year_mil,year_civil],"logs":logs,"report_rows":[],"report_total":0,"report_range":{"from":start.strftime('%Y-%m-%d'),"to":end.strftime('%Y-%m-%d')}}
    except Exception as e:
        print("Dashboard stats error:", e); return {"dates":[],"mil":[],"civil":[],"total":[],"today_total":0,"today_mil":0,"today_civil":0,"week_total":0,"week_mil":0,"week_civil":0,"logs":[],"report_rows":[]}

def get_camera_sum_vs_dashboard(date_value=None):
    """
    Diagnostic function: Compare dashboard total vs. sum of all individual cameras for today.
    Helps identify if there are duplicates, missing camera_id, or counting mismatches.
    """
    try:
        conn = _get_connection()
        cur = conn.cursor(dictionary=True)
        
        count_date = date_value if date_value else datetime.date.today().strftime("%Y-%m-%d")
        date_expr = "COALESCE(detection_date, log_date, DATE(detection_time), DATE(time))"
        
        # Dashboard total (no camera filter)
        cur.execute(f"SELECT COUNT(*) c, SUM(CASE WHEN class_id=0 OR LOWER(COALESCE(class_name,'')) LIKE '%mil%' THEN 1 ELSE 0 END) m, SUM(CASE WHEN class_id=1 OR LOWER(COALESCE(class_name,'')) LIKE '%civil%' THEN 1 ELSE 0 END) cv FROM vehicle_logs WHERE {date_expr}=%s", (count_date,))
        dashboard_row = cur.fetchone() or {}
        dashboard_total = int(dashboard_row.get('c') or 0)
        dashboard_mil = int(dashboard_row.get('m') or 0)
        dashboard_civ = int(dashboard_row.get('cv') or 0)
        
        # Get sum of all individual cameras
        camera_sums = []
        camera_total = 0
        camera_mil_total = 0
        camera_civ_total = 0
        
        for cam_id, cam_name in CAMERA_NAME_MAP.items():
            stats = get_camera_today_db_stats(camera_id=cam_id, camera_name=cam_name, date_value=count_date)
            total = stats.get('today_total', 0)
            mil = stats.get('today_mil', 0)
            civ = stats.get('today_civil', 0)
            camera_sums.append({
                'camera_id': cam_id,
                'camera_name': cam_name,
                'mil': mil,
                'civil': civ,
                'total': total
            })
            camera_total += total
            camera_mil_total += mil
            camera_civ_total += civ
        
        # Check for vehicles with NULL camera_id or camera_name
        cur.execute(f"SELECT COUNT(*) c FROM vehicle_logs WHERE {date_expr}=%s AND (camera_id IS NULL OR camera_name IS NULL OR TRIM(camera_name)='')", (count_date,))
        null_row = cur.fetchone() or {}
        vehicles_without_camera_id = int(null_row.get('c') or 0)
        
        cur.close()
        conn.close()
        
        return {
            'date': count_date,
            'dashboard_total': dashboard_total,
            'dashboard_mil': dashboard_mil,
            'dashboard_civil': dashboard_civ,
            'camera_sum_total': camera_total,
            'camera_sum_mil': camera_mil_total,
            'camera_sum_civil': camera_civ_total,
            'mismatch': dashboard_total - camera_total,
            'vehicles_without_camera_id': vehicles_without_camera_id,
            'camera_breakdown': camera_sums
        }
    except Exception as e:
        print("Diagnostic error:", e)
        return {'error': str(e)}



def build_tcp_report_rows(tcp_name="all", limit=300, start_date=None, end_date=None):
    """
    Build TCP report directly from vehicle_logs.

    Important:
      - Dashboard TCP total = total detections from both cameras.
      - TCP table rows = movements/waiting rows.
      - A matched movement uses 2 detections but shows as 1 row with Time In + Time Out.
      - UNKNOWN / bad OCR plates are also shown as waiting rows, so they do not disappear.

    Rule:
      - first detection by time = Time In
      - next opposite camera detection for same cleaned license = Time Out
      - if no opposite camera detection exists = Waiting for OUT camera match
    """
    try:
        tcp_name = (tcp_name or "all").lower().strip()

        if not start_date:
            start_date = datetime.date.today().strftime("%Y-%m-%d")
        if not end_date:
            end_date = start_date

        limit = max(50, int(limit or 300))

        if tcp_name == "all":
            final = []
            ser = 1
            for key in TCP_PAIR_MAP:
                rep = build_tcp_report_rows(
                    key,
                    limit=limit,
                    start_date=start_date,
                    end_date=end_date,
                )
                for row in rep.get("rows", []):
                    row["ser_no"] = ser
                    row["ser"] = ser
                    final.append(row)
                    ser += 1

            return {
                "success": True,
                "tcp_name": "all",
                "start_date": start_date,
                "end_date": end_date,
                "rows": final[:limit],
                "total_rows": len(final),
                "matching_note": (
                    "TCP report is built from MySQL vehicle_logs. IN/OUT is decided by detection time: "
                    "the first camera that sees a plate is IN, and the next opposite camera is OUT."
                ),
            }

        if tcp_name not in TCP_PAIR_MAP:
            return {"success": False, "message": "Invalid TCP name", "rows": []}

        cam_a, cam_b = TCP_PAIR_MAP[tcp_name]

        aliases_a = [str(x).strip().lower() for x in get_camera_aliases(cam_a)]
        aliases_b = [str(x).strip().lower() for x in get_camera_aliases(cam_b)]
        all_aliases = list(dict.fromkeys(aliases_a + aliases_b))

        cam_a_ids = [
            cid for cid, name in CAMERA_NAME_MAP.items()
            if normalize_camera_name(name) == normalize_camera_name(cam_a)
        ]
        cam_b_ids = [
            cid for cid, name in CAMERA_NAME_MAP.items()
            if normalize_camera_name(name) == normalize_camera_name(cam_b)
        ]
        all_ids = cam_a_ids + cam_b_ids

        conn = _get_connection()
        cur = conn.cursor(dictionary=True)

        date_expr = "COALESCE(detection_date, log_date, DATE(detection_time), DATE(time))"
        time_expr = "COALESCE(detection_time, time, created_at)"

        where_parts = [f"{date_expr} BETWEEN %s AND %s"]
        params = [start_date, end_date]

        cam_filters = []
        if all_aliases:
            cam_filters.append(
                "LOWER(TRIM(camera_name)) IN (" + ",".join(["%s"] * len(all_aliases)) + ")"
            )
            params.extend(all_aliases)

        if all_ids:
            cam_filters.append(
                "camera_id IN (" + ",".join(["%s"] * len(all_ids)) + ")"
            )
            params.extend(all_ids)

        if not cam_filters:
            cur.close()
            conn.close()
            return {"success": False, "message": "No cameras mapped for TCP", "rows": []}

        where_parts.append("(" + " OR ".join(cam_filters) + ")")

        # Fetch more than display limit because matched rows consume two detections.
        # This prevents the table from showing only a few rows when many detections exist.
        fetch_limit = max(limit * 4, 10000)

        cur.execute(
            f"""
            SELECT
                id,
                track_id,
                camera_id,
                camera_name,
                class_name,
                vehicle_class,
                class_id,
                license,
                license_plate,
                avg_speed,
                speed,
                license_img,
                plate_img,
                veh_img,
                vehicle_img,
                {time_expr} AS det_time,
                {date_expr} AS det_date
            FROM vehicle_logs
            WHERE {' AND '.join(where_parts)}
            ORDER BY det_time ASC, id ASC
            LIMIT %s
            """,
            tuple(params + [fetch_limit]),
        )

        raw_rows = cur.fetchall()
        cur.close()
        conn.close()

        def _to_dt(v):
            if isinstance(v, datetime.datetime):
                return v
            if isinstance(v, datetime.date):
                return datetime.datetime.combine(v, datetime.time.min)
            try:
                return parse_time_value(v)
            except Exception:
                return datetime.datetime.min

        def _side_and_camera(row):
            cname = normalize_camera_name(row.get("camera_name"))
            cname_l = cname.lower().strip()
            cid = row.get("camera_id")

            if cname_l in aliases_a or cid in cam_a_ids:
                return "A", cam_a
            if cname_l in aliases_b or cid in cam_b_ids:
                return "B", cam_b

            return "", cname or "Unknown Camera"

        valid_items = []
        result_rows = []
        total_detections = 0
        unknown_count = 0

        for r in raw_rows:
            side, canonical_cam = _side_and_camera(r)
            if not side:
                continue

            total_detections += 1

            original_license = (
                r.get("license")
                or r.get("license_plate")
                or ""
            )
            cleaned_license = normalize_match_license(original_license)

            item = {
                "id": r.get("id"),
                "track_id": r.get("track_id") or "",
                "side": side,
                "camera": canonical_cam,
                "det_time": _to_dt(r.get("det_time")),
                "class_name": r.get("class_name") or r.get("vehicle_class") or "",
                "class_id": r.get("class_id"),
                "speed": r.get("avg_speed") or r.get("speed") or "",
                "license_img": r.get("license_img") or r.get("plate_img") or "",
                "veh_img": r.get("veh_img") or r.get("vehicle_img") or "",
                "original_license": str(original_license or "UNKNOWN").strip() or "UNKNOWN",
            }

            if cleaned_license:
                item["cleaned_license"] = cleaned_license
                valid_items.append(item)
            else:
                # Do not hide UNKNOWN / bad OCR rows. They cannot be matched safely,
                # but they must appear in TCP table as waiting rows.
                unknown_count += 1
                out_camera = cam_b if side == "A" else cam_a
                result_rows.append({
                    "tcp": tcp_name.upper(),
                    "camera": f"{canonical_cam} → {out_camera}",
                    "in_camera": canonical_cam,
                    "out_camera": out_camera,
                    "class_name": item["class_name"],
                    "class_id": item["class_id"],
                    "track_id": item["track_id"],
                    "license_img": item["license_img"],
                    "plate": item["license_img"],
                    "veh_img": item["veh_img"],
                    "vehicle": item["veh_img"],
                    "source_table": "vehicle_logs",
                    "license": item["original_license"],
                    "time_in": _fmt_dt(item["det_time"]),
                    "time_out": "",
                    "speed": item["speed"],
                    "out_speed": "",
                    "remarks": _tcp_out_remark(out_camera, unknown=True),
                    "matched": False,
                    "detected_count": 1,
                })

        matched_count = 0
        valid_items.sort(key=lambda x: (x.get("det_time") or datetime.datetime.min, x.get("id") or 0))
        used = set()

        for idx, first in enumerate(valid_items):
            if idx in used:
                continue

            used.add(idx)
            match_idx = None
            best_score = 0
            best_seconds = None

            for j in range(idx + 1, len(valid_items)):
                if j in used:
                    continue

                second_candidate = valid_items[j]

                if second_candidate["side"] != first["side"] and _license_match_score(first.get("cleaned_license"), second_candidate.get("cleaned_license")) >= 85:
                    match_idx = j
                    best_score = _license_match_score(first.get("cleaned_license"), second_candidate.get("cleaned_license"))
                    break

            second = valid_items[match_idx] if match_idx is not None else None

            if second:
                used.add(match_idx)
                matched_count += 1

            in_camera = first["camera"]
            out_camera = second["camera"] if second else (cam_b if first["side"] == "A" else cam_a)
            display_license = first.get("cleaned_license") or first.get("original_license") or "UNKNOWN"
            second_license = second.get("cleaned_license") if second else ""

            result_rows.append({
                    "tcp": tcp_name.upper(),
                    "camera": f"{in_camera} → {out_camera}",
                    "in_camera": in_camera,
                    "out_camera": out_camera,
                    "class_name": first.get("class_name", ""),
                    "class_id": first.get("class_id"),
                    "track_id": first.get("track_id", ""),
                    "license_img": first.get("license_img", ""),
                    "plate": first.get("license_img", ""),
                    "veh_img": first.get("veh_img", ""),
                    "vehicle": first.get("veh_img", ""),
                    "source_table": "vehicle_logs",
                    "license": display_license,
                    "out_license": second_license,
                    "match_score": best_score if second else 0,
                    "time_in": _fmt_dt(first.get("det_time")),
                    "time_out": _fmt_dt(second.get("det_time")) if second else "",
                    "speed": first.get("speed", ""),
                    "out_speed": second.get("speed", "") if second else "",
                    "remarks": _tcp_out_remark(out_camera, matched=bool(second)),
                    "matched": bool(second),
                    "detected_count": 2 if second else 1,
                })

        result_rows.sort(key=lambda r: r.get("time_in") or "", reverse=True)

        display_rows = enrich_rows_with_vehicle_master(result_rows[:limit])
        for i, row in enumerate(display_rows, 1):
            row["ser_no"] = i
            row["ser"] = i

        waiting_count = len(result_rows) - matched_count

        return {
            "success": True,
            "tcp_name": tcp_name,
            "camera_a": cam_a,
            "camera_b": cam_b,
            "in_camera": "First detection by time",
            "out_camera": "Next opposite camera by time",
            "start_date": start_date,
            "end_date": end_date,
            "rows": display_rows,
            "total_rows": len(result_rows),
            "total_detections": total_detections,
            "matched_count": matched_count,
            "waiting_count": waiting_count,
            "unknown_ocr_count": unknown_count,
            "display_limit": limit,
            "matching_note": (
                "Built from MySQL vehicle_logs. Both TCP cameras are considered. Either camera can be IN: "
                "first detection by time is IN, and the next detection from the opposite camera is OUT. "
                "Unmatched/UNKNOWN OCR detections remain visible."
            ),
        }

    except Exception as e:
        print("TCP report error:", e)
        return {"success": False, "message": str(e), "rows": []}




def get_camera_comparison_stats():
    """
    Dashboard TCP cards.
    veh_in = total detections from both cameras of that TCP today.
    matched = number of licenses found in both cameras with valid IN/OUT today.
    remaining = unmatched detections after matched pairs consume two detections.
    """
    today = datetime.date.today().strftime("%Y-%m-%d")
    pairs = {}
    counts = {}

    for key, (cam_a, cam_b) in TCP_PAIR_MAP.items():
        try:
            stats_a = _count_class_totals_for_camera_name(cam_a, today, today)
            stats_b = _count_class_totals_for_camera_name(cam_b, today, today)
            total_a = int(stats_a.get("total", 0))
            total_b = int(stats_b.get("total", 0))
            pair_total = total_a + total_b
            rep = build_tcp_report_rows(key, limit=5000, start_date=today, end_date=today)
            matched = int(rep.get("matched_count") or 0)
            waiting = int(rep.get("waiting_count") or 0)
            remaining = max(pair_total - (matched * 2), 0)
        except Exception as e:
            print("Camera comparison pair error", key, e)
            total_a = total_b = pair_total = matched = waiting = remaining = 0

        pairs[key] = {
            "tcp_key": key,
            "label": key.upper(),
            "in_camera": cam_a,
            "out_camera": cam_b,
            "veh_in": pair_total,
            "total_detections": pair_total,
            "camera_a_count": total_a,
            "camera_b_count": total_b,
            "matched": matched,
            "matched_count": matched,
            "remaining": remaining,
            "remaining_count": remaining,
            "waiting_rows": waiting,
            "out_seen_count": matched,
            "remaining_rows": [],
            "matched_rows": [],
        }
        counts[cam_a] = total_a
        counts[cam_b] = total_b

    out = {
        "success": True,
        "today": today,
        "pairs": pairs,
        "counts": counts,
        "today_total": sum(p["veh_in"] for p in pairs.values()),
        "today_mil": 0,
        "today_civil": 0,
        "matching_note": "TCP card total = sum of both camera detections. Matched = same license found in both cameras.",
    }
    for k, p in pairs.items():
        out[f"{k}_matched"] = p["matched"]
        out[f"{k}_remaining"] = p["remaining"]
    return out


def _count_class_totals_for_camera_name(camera_name, start_date, end_date):
    try:
        conn = _get_connection()
        cur = conn.cursor(dictionary=True)
        aliases = [str(a).strip().lower() for a in get_camera_aliases(camera_name)]
        date_expr = "COALESCE(detection_date, log_date, DATE(detection_time), DATE(time))"
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN class_id=0 OR LOWER(COALESCE(class_name,'')) LIKE '%mil%' THEN 1 ELSE 0 END) AS mil_count,
                SUM(CASE WHEN class_id=1 OR LOWER(COALESCE(class_name,'')) LIKE '%civil%' THEN 1 ELSE 0 END) AS civil_count
            FROM vehicle_logs
            WHERE {date_expr} BETWEEN %s AND %s
              AND LOWER(TRIM(camera_name)) IN ({','.join(['%s'] * len(aliases))})
            """,
            tuple([start_date, end_date] + aliases),
        )
        row = cur.fetchone() or {}
        cur.close()
        conn.close()
        return {
            "total": int(row.get("total_count") or 0),
            "mil": int(row.get("mil_count") or 0),
            "civil": int(row.get("civil_count") or 0),
        }
    except Exception as e:
        print("_count_class_totals_for_camera_name error:", e)
        return {"total": 0, "mil": 0, "civil": 0}

def get_remaining_vehicle_rows(group="kiari", limit=200):
    rep=build_tcp_report_rows(group, limit=2000); rows=[r for r in rep.get('rows',[]) if not r.get('time_out')]
    return {"success":True,"group":group,"in_camera":rep.get('in_camera',''),"out_camera":rep.get('out_camera',''),"total":len(rows),"rows":rows[:int(limit)]}

def get_camera_today_db_stats(camera_id=None, camera_name=None, date_value=None):
    """
    Camera popup count from vehicle_logsnew.vehicle_logs.

    If date_value is given, count that date.
    Otherwise count only today’s detections for the requested camera.
    """
    try:
        conn = _get_connection()
        cur = conn.cursor(dictionary=True)

        where = []
        params = []

        if camera_id is not None:
            where.append("camera_id = %s")
            params.append(int(camera_id))

        if camera_name:
            aliases = [str(a).strip().lower() for a in get_camera_aliases(camera_name)]
            where.append("LOWER(TRIM(camera_name)) IN (" + ",".join(["%s"] * len(aliases)) + ")")
            params.extend(aliases)

        count_date = date_value if date_value else datetime.date.today().strftime("%Y-%m-%d")
        date_expr = "COALESCE(detection_date, log_date, DATE(detection_time), DATE(time))"

        where2 = list(where)
        params2 = list(params)
        where2.append(f"{date_expr} = %s")
        params2.append(count_date)
        where_sql2 = "WHERE " + " AND ".join(where2) if where2 else ""

        cur.execute(
            f"SELECT COUNT(*) AS total_count, SUM(CASE WHEN class_id = 0 OR LOWER(COALESCE(class_name,'')) LIKE '%mil%' THEN 1 ELSE 0 END) AS mil_count, SUM(CASE WHEN class_id = 1 OR LOWER(COALESCE(class_name,'')) LIKE '%civil%' THEN 1 ELSE 0 END) AS civil_count FROM vehicle_logs {where_sql2}",
            tuple(params2),
        )

        r = cur.fetchone() or {}
        cur.close()
        conn.close()

        return {
            "success": True,
            "camera_name": camera_name or "All Cameras",
            "today_mil": int(r.get("mil_count") or 0),
            "today_civil": int(r.get("civil_count") or 0),
            "today_total": int(r.get("total_count") or 0),
            "source": "vehicle_logsnew.vehicle_logs",
            "date": count_date,
        }
    except Exception as e:
        print("get_camera_today_db_stats error:", e)
        return {
            "success": False,
            "camera_name": camera_name or "All Cameras",
            "today_mil": 0,
            "today_civil": 0,
            "today_total": 0,
            "source": "vehicle_logsnew.vehicle_logs",
            "date": date_value or datetime.date.today().strftime("%Y-%m-%d"),
            "message": str(e),
        }

def ensure_vehicle_master_table(): ensure_table()

def _xlsx_col_index(cell_ref):
    letters = "".join(ch for ch in str(cell_ref or "") if ch.isalpha()).upper()
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return max(0, idx - 1)

def _read_first_xlsx_sheet_rows(path):
    ns = {
        "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    with zipfile.ZipFile(path) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", ns):
                shared.append("".join(t.text or "" for t in item.findall(".//a:t", ns)))

        book = ET.fromstring(zf.read("xl/workbook.xml"))
        first_sheet = book.find("a:sheets/a:sheet", ns)
        rel_id = first_sheet.attrib[f"{{{ns['r']}}}id"]
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in rels.findall("rel:Relationship", ns):
            if rel.attrib.get("Id") == rel_id:
                target = rel.attrib["Target"].lstrip("/")
                break
        sheet_path = "xl/" + target if not target.startswith("xl/") else target
        sheet = ET.fromstring(zf.read(sheet_path))

        rows = []
        for row_el in sheet.findall(".//a:sheetData/a:row", ns):
            values = []
            for cell in row_el.findall("a:c", ns):
                col_idx = _xlsx_col_index(cell.attrib.get("r", "A"))
                while len(values) <= col_idx:
                    values.append("")
                cell_type = cell.attrib.get("t")
                value_el = cell.find("a:v", ns)
                if cell_type == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall(".//a:t", ns))
                elif value_el is None:
                    value = ""
                elif cell_type == "s":
                    value = shared[int(value_el.text or 0)] if shared else ""
                else:
                    value = value_el.text or ""
                values[col_idx] = str(value).strip()
            rows.append(values)
        return rows

def import_vehicle_details_from_excel(path=None):
    path = path or VEH_DETAILS_PATH
    if not os.path.exists(path):
        return {"success": False, "message": f"Excel file not found: {path}", "imported": 0}

    rows = _read_first_xlsx_sheet_rows(path)
    header_idx = None
    header = []
    for idx, row in enumerate(rows):
        normalized = [re.sub(r"\s+", " ", str(v or "")).strip().upper() for v in row]
        if "VEH BA NO" in normalized and "UNIT" in normalized:
            header_idx = idx
            header = normalized
            break
    if header_idx is None:
        return {"success": False, "message": "Could not find VEH BA NO / UNIT columns", "imported": 0}

    plate_idx = header.index("VEH BA NO")
    type_idx = header.index("VEH TYPE") if "VEH TYPE" in header else None
    unit_idx = header.index("UNIT")

    imported = skipped = 0
    try:
        conn = _get_connection()
    except Error as e:
        return {"success": False, "message": f"MySQL unavailable: {e}", "imported": 0, "skipped": skipped, "path": path}

    cur = conn.cursor()
    try:
        for row in rows[header_idx + 1:]:
            plate = str(row[plate_idx] if plate_idx < len(row) else "").upper().strip()
            norm = normalize_match_license(plate)
            if not norm:
                skipped += 1
                continue
            vehicle_type = str(row[type_idx] if type_idx is not None and type_idx < len(row) else "").strip()
            unit = str(row[unit_idx] if unit_idx < len(row) else "").strip()
            cur.execute(
                """
                INSERT INTO vehicle_master
                    (license_plate, license_norm, make_model, vehicle_type, unit, driver_name, remarks)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    license_plate=VALUES(license_plate),
                    vehicle_type=VALUES(vehicle_type),
                    unit=VALUES(unit),
                    remarks=VALUES(remarks)
                """,
                (plate, norm, "", vehicle_type, unit, "", "Imported from VEH DETAILS.xlsx"),
            )
            imported += 1
        conn.commit()
        return {"success": True, "message": f"Imported {imported} vehicle detail rows", "imported": imported, "skipped": skipped, "path": path}
    except Error as e:
        conn.rollback()
        return {"success": False, "message": str(e), "imported": 0, "skipped": skipped, "path": path}
    finally:
        cur.close()
        conn.close()

def get_vehicle_details_from_excel(license_plate, path=None):
    path = path or VEH_DETAILS_PATH
    norm = normalize_match_license(license_plate)
    if not norm or not os.path.exists(path):
        return None

    mtime = os.path.getmtime(path)
    if vehicle_details_cache["mtime"] != mtime:
        rows = _read_first_xlsx_sheet_rows(path)
        header_idx = None
        header = []
        for idx, row in enumerate(rows):
            normalized = [re.sub(r"\s+", " ", str(v or "")).strip().upper() for v in row]
            if "VEH BA NO" in normalized and "UNIT" in normalized:
                header_idx = idx
                header = normalized
                break
        details = {}
        if header_idx is not None:
            plate_idx = header.index("VEH BA NO")
            type_idx = header.index("VEH TYPE") if "VEH TYPE" in header else None
            unit_idx = header.index("UNIT")
            for row in rows[header_idx + 1:]:
                plate = str(row[plate_idx] if plate_idx < len(row) else "").upper().strip()
                row_norm = normalize_match_license(plate)
                if not row_norm:
                    continue
                details[row_norm] = {
                    "license_plate": plate,
                    "make_model": "",
                    "vehicle_type": str(row[type_idx] if type_idx is not None and type_idx < len(row) else "").strip(),
                    "unit": str(row[unit_idx] if unit_idx < len(row) else "").strip(),
                    "driver_name": "",
                    "remarks": "Matched from VEH DETAILS.xlsx",
                }
        vehicle_details_cache["mtime"] = mtime
        vehicle_details_cache["rows"] = details
    return vehicle_details_cache["rows"].get(norm)

def add_or_update_vehicle_master(data):
    try:
        lic=str(data.get('license_plate') or data.get('license') or '').upper().strip(); norm=normalize_match_license(lic)
        if not norm: return {"success":False,"message":"License plate is required"}
        conn=_get_connection(); cur=conn.cursor()
        cur.execute("""INSERT INTO vehicle_master (license_plate,license_norm,make_model,vehicle_type,unit,driver_name,remarks) VALUES (%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE license_plate=VALUES(license_plate), make_model=VALUES(make_model), vehicle_type=VALUES(vehicle_type), unit=VALUES(unit), driver_name=VALUES(driver_name), remarks=VALUES(remarks)""", (lic,norm,data.get('make_model',''),data.get('vehicle_type',''),data.get('unit',''),data.get('driver_name',''),data.get('remarks','')))
        conn.commit(); cur.close(); conn.close(); return {"success":True,"message":"Vehicle information saved","license_norm":norm}
    except Error as e: return {"success":False,"message":str(e)}
def get_vehicle_master_info(license_plate):
    try:
        norm=normalize_match_license(license_plate); 
        if not norm: return None
        conn=_get_connection(); cur=conn.cursor(dictionary=True); cur.execute("SELECT license_plate,make_model,vehicle_type,unit,driver_name,remarks FROM vehicle_master WHERE license_norm=%s LIMIT 1", (norm,)); row=cur.fetchone(); cur.close(); conn.close(); return row
    except Error:
        return get_vehicle_details_from_excel(license_plate)
def get_vehicle_master_rows(limit=500):
    try:
        conn=_get_connection(); cur=conn.cursor(dictionary=True); cur.execute("SELECT id,license_plate,make_model,vehicle_type,unit,driver_name,remarks FROM vehicle_master ORDER BY updated_at DESC,id DESC LIMIT %s", (int(limit),)); rows=cur.fetchall(); cur.close(); conn.close(); return rows
    except Error: return []
def enrich_rows_with_vehicle_master(rows):
    if not rows:
        return rows
    norms = []
    row_norms = []
    for row in rows:
        norm = normalize_match_license(row.get("license") or row.get("license_plate") or row.get("plate_number") or "")
        row_norms.append(norm)
        if norm:
            norms.append(norm)
    norms = list(dict.fromkeys(norms))
    if not norms:
        for row in rows:
            row["vehicle_master_match"] = False
            row["unit"] = display_unit_for_class(row.get("unit"), row.get("class_name"), row.get("class_id"))
            row["vehicle_type_master"] = row.get("vehicle_type_master") or NO_RECORD_TEXT
            row["vehicle_remarks"] = row.get("vehicle_remarks") or NO_RECORD_TEXT
        return rows
    try:
        conn = _get_connection()
        cur = conn.cursor(dictionary=True)
        placeholders = ",".join(["%s"] * len(norms))
        cur.execute(
            f"""
            SELECT license_norm, license_plate, make_model, vehicle_type, unit, driver_name, remarks
            FROM vehicle_master
            WHERE license_norm IN ({placeholders})
            """,
            tuple(norms),
        )
        master = {row["license_norm"]: row for row in cur.fetchall()}
        cur.close()
        conn.close()
        for row, norm in zip(rows, row_norms):
            detail = master.get(norm)
            if not detail:
                row["vehicle_master_match"] = False
                row["unit"] = display_unit_for_class(row.get("unit"), row.get("class_name"), row.get("class_id"))
                row["vehicle_type_master"] = row.get("vehicle_type_master") or NO_RECORD_TEXT
                row["vehicle_remarks"] = row.get("vehicle_remarks") or NO_RECORD_TEXT
                continue
            row["vehicle_master_match"] = True
            row["master_license"] = detail.get("license_plate") or ""
            row["make_model"] = detail.get("make_model") or NO_RECORD_TEXT
            row["vehicle_type_master"] = detail.get("vehicle_type") or NO_RECORD_TEXT
            row["unit"] = display_unit_for_class(detail.get("unit"), row.get("class_name"), row.get("class_id"))
            row["driver_name"] = detail.get("driver_name") or NO_RECORD_TEXT
            row["vehicle_remarks"] = detail.get("remarks") or NO_RECORD_TEXT
    except Error as e:
        print("Vehicle master enrichment error:", e)
        for row in rows:
            detail = get_vehicle_details_from_excel(row.get("license") or row.get("license_plate") or row.get("plate_number") or "")
            if not detail:
                row["vehicle_master_match"] = False
                row["unit"] = display_unit_for_class(row.get("unit"), row.get("class_name"), row.get("class_id"))
                row["vehicle_type_master"] = row.get("vehicle_type_master") or NO_RECORD_TEXT
                row["vehicle_remarks"] = row.get("vehicle_remarks") or NO_RECORD_TEXT
                continue
            row["vehicle_master_match"] = True
            row["master_license"] = detail.get("license_plate") or ""
            row["make_model"] = detail.get("make_model") or NO_RECORD_TEXT
            row["vehicle_type_master"] = detail.get("vehicle_type") or NO_RECORD_TEXT
            row["unit"] = display_unit_for_class(detail.get("unit"), row.get("class_name"), row.get("class_id"))
            row["driver_name"] = detail.get("driver_name") or NO_RECORD_TEXT
            row["vehicle_remarks"] = detail.get("remarks") or NO_RECORD_TEXT
    return rows

def update_vehicle_log_row(data):
    try:
        row_id=int(data.get('id')); dt=parse_time_value(data.get('time'))
        conn=_get_connection(); cur=conn.cursor(); cur.execute("""UPDATE vehicle_logs SET track_id=%s,class_name=%s,vehicle_class=%s,avg_speed=%s,speed=%s,license=%s,license_plate=%s,time=%s,detection_time=%s,log_date=%s,detection_date=%s,camera_name=%s,class_id=%s WHERE id=%s""", (int(data.get('track_id') or 0),data.get('class_name',''),data.get('class_name',''),data.get('avg_speed',''),data.get('avg_speed',''),data.get('license','Unknown'),data.get('license','Unknown'),dt,dt,dt.date(),dt.date(),data.get('camera_name',''),int(data.get('class_id') or 0),row_id)); conn.commit(); aff=cur.rowcount; cur.close(); conn.close(); return {"success":True,"updated":aff}
    except Exception as e: return {"success":False,"message":str(e)}
def delete_vehicle_log_row(source_table, row_id):
    try:
        conn=_get_connection(); cur=conn.cursor(); cur.execute("DELETE FROM vehicle_logs WHERE id=%s", (int(row_id),)); conn.commit(); aff=cur.rowcount; cur.close(); conn.close(); return {"success":True,"deleted":aff}
    except Exception as e: return {"success":False,"message":str(e)}

def _build_union_logs_query(conn):
    # Compatibility for old routes/search. Returns only the new table with old column aliases.
    return """
        SELECT id, track_id, class_name, avg_speed, license, time, log_date, license_img, veh_img, class_id, camera_name, source_type, 'vehicle_logs' AS source_table
        FROM vehicle_logs
    """

def _get_log_tables(cur): return ["vehicle_logs"]
def _get_table_columns(cur, table_name): return set()
def _base_logs_where(camera_name=None):
    where=["log_date IS NOT NULL"]; params=[]
    if camera_name:
        aliases=get_camera_aliases(camera_name); where.append("camera_name IN ("+",".join(["%s"]*len(aliases))+")"); params.extend(aliases)
    return " WHERE "+" AND ".join(where), params
