import os

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
os.environ["FLAGS_enable_pir_api"] = "0"

from waitress import serve
from flask_cors import CORS
from flask_app import create_app
from core.common import ensure_database, ensure_table, import_vehicle_details_from_excel

try:
    from core.license_utils import get_paddle_ocr
    OCR_PRELOAD_ERROR = None
except Exception as e:
    get_paddle_ocr = None
    OCR_PRELOAD_ERROR = e

app = create_app()
CORS(app, resources={r"/*": {"origins": os.getenv("FRONTEND_ORIGIN", "*")}})

if __name__ == "__main__":
    ensure_database()
    ensure_table()
    try:
        result = import_vehicle_details_from_excel()
        print("[APP]", result.get("message"))
    except Exception as e:
        print("[APP] Vehicle Excel import skipped:", e)

    # Preload PaddleOCR at startup so the first detected vehicle does not freeze the stream.
    try:
        print("[APP] Preloading PaddleOCR...")
        if get_paddle_ocr is None:
            print("[APP] PaddleOCR preload skipped:", OCR_PRELOAD_ERROR)
        else:
            get_paddle_ocr()
            print("[APP] PaddleOCR ready.")
    except Exception as e:
        print("[APP] PaddleOCR preload skipped:", e)

    host ="192.168.1.50"
    port = "7070"

    print(f"e-TCP API running on http://192.168.1.50:{port}")
    serve(app, host=host, port=port, threads=64, connection_limit=1000, channel_timeout=120)
