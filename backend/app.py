import os

from env_loader import load_project_env

load_project_env()

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
os.environ["FLAGS_enable_pir_api"] = "0"

from waitress import serve
from flask_cors import CORS
from flask_app import create_app
from core.common import check_mysql_connection, ensure_database, ensure_table, import_vehicle_details_from_excel
from project_config import get_server_config

try:
    from core.license_utils import get_paddle_ocr
    OCR_PRELOAD_ERROR = None
except Exception as e:
    get_paddle_ocr = None
    OCR_PRELOAD_ERROR = e

app = create_app()
CORS(app, resources={r"/*": {"origins": os.getenv("FRONTEND_ORIGIN", "*")}})

if __name__ == "__main__":
    mysql_status = check_mysql_connection(log=True)
    if mysql_status.get("connected"):
        if ensure_database() and ensure_table():
            try:
                result = import_vehicle_details_from_excel()
                print("[APP]", result.get("message"))
            except Exception as e:
                print("[APP] Vehicle Excel import skipped:", e)
    else:
        print("[APP] MySQL is offline. Backend will still start; DB-backed pages stay empty until MySQL is available.")

    if os.getenv("ETCP_PRELOAD_OCR", "0").strip().lower() in ("1", "true", "yes", "on"):
        try:
            print("[APP] Preloading PaddleOCR...")
            if get_paddle_ocr is None:
                print("[APP] PaddleOCR preload skipped:", OCR_PRELOAD_ERROR)
            else:
                get_paddle_ocr()
                print("[APP] PaddleOCR ready.")
        except Exception as e:
            print("[APP] PaddleOCR preload skipped:", e)
    else:
        print("[APP] PaddleOCR preload disabled. Set ETCP_PRELOAD_OCR=1 to enable it.")

    server_config = get_server_config()
    host = str(server_config.get("host") or os.getenv("BACKEND_HOST") or os.getenv("APP_HOST") or "0.0.0.0")
    port = int(server_config.get("port") or os.getenv("BACKEND_PORT") or os.getenv("APP_PORT") or "7073")

    public_url = str(server_config.get("public_url") or os.getenv("BACKEND_PUBLIC_URL") or "").strip()
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"e-TCP API listening on http://{display_host}:{port}")
    if public_url:
        print(f"e-TCP camera/client URL: {public_url}")
    serve(app, host=host, port=port, threads=64, connection_limit=1000, channel_timeout=120)
