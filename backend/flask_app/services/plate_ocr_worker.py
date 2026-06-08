import os
import queue
import re
import threading
import time

import cv2
import numpy as np

from core.common import (
    class_from_license_rule,
    correct_plate_with_master_or_military_format,
    is_civil_plate_color,
    normalize_plate_text,
    update_vehicle_log_plate_from_ocr,
)


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC_PREFIX = "/static/"
OCR_ENABLED = os.getenv("ETCP_EVENT_PLATE_OCR", "1").strip().lower() in ("1", "true", "yes", "on")
OCR_QUEUE_MAX = max(1, int(os.getenv("ETCP_EVENT_PLATE_OCR_QUEUE_MAX", "200")))
OCR_MIN_SCORE = int(os.getenv("ETCP_EVENT_PLATE_OCR_MIN_SCORE", "50"))

_queue = queue.Queue(maxsize=OCR_QUEUE_MAX)
_worker_started = False
_worker_lock = threading.Lock()
_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        os.environ.setdefault("FLAGS_use_mkldnn", "0")
        os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")
        os.environ.setdefault("FLAGS_enable_pir_api", "0")
        from paddleocr import PaddleOCR

        started = time.perf_counter()
        try:
            _reader = PaddleOCR(use_textline_orientation=False, lang="en")
        except Exception:
            try:
                _reader = PaddleOCR(use_angle_cls=False, lang="en")
            except Exception:
                _reader = PaddleOCR(lang="en")
        print(f"[EVENT OCR] PaddleOCR loaded in {(time.perf_counter() - started) * 1000:.0f}ms")
    return _reader


def _url_to_path(url):
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith(STATIC_PREFIX):
        return os.path.join(BASE_DIR, "flask_app", "static", text[len(STATIC_PREFIX):].replace("/", os.sep))
    if os.path.isabs(text):
        return text
    return ""


def _flatten_paddle_result(result):
    texts = []
    if not result:
        return texts
    try:
        for page in result:
            if page is None:
                continue
            if isinstance(page, dict):
                rec_texts = page.get("rec_texts") or page.get("texts") or []
                rec_scores = page.get("rec_scores") or page.get("scores") or [1.0] * len(rec_texts)
                for txt, score in zip(rec_texts, rec_scores):
                    if txt and float(score) >= 0.01:
                        texts.append(str(txt))
                continue
            for item in page:
                try:
                    txt = item[1][0]
                    score = float(item[1][1])
                    if txt and score >= 0.01:
                        texts.append(str(txt))
                except Exception:
                    pass
    except Exception:
        pass

    try:
        text = str(result)
        texts.extend(re.findall(r"'rec_text':\s*'([^']+)'", text))
        texts.extend(re.findall(r'"rec_text":\s*"([^"]+)"', text))
    except Exception:
        pass

    out = []
    seen = set()
    for text in texts:
        if text not in seen:
            out.append(text)
            seen.add(text)
    return out


def _preprocess_plate(img):
    if img is None or img.size == 0:
        return None
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return None

    aspect = w / max(1, h)
    if not (2.0 <= aspect <= 9.0 and h <= 160):
        img = img[int(h * 0.25):int(h * 0.82), int(w * 0.04):int(w * 0.96)]
        h, w = img.shape[:2]

    scale = 96 / float(max(1, h))
    new_w = max(180, min(640, int(w * scale)))
    return cv2.resize(img, (new_w, 96), interpolation=cv2.INTER_CUBIC)


def _run_plate_ocr(image_path):
    img = cv2.imread(image_path)
    img = _preprocess_plate(img)
    if img is None or img.size == 0:
        return []
    reader = _get_reader()
    try:
        try:
            result = reader.ocr(img, det=False, cls=False)
        except TypeError:
            result = reader.ocr(img, det=False)
        return _flatten_paddle_result(result)
    except Exception as e:
        print("[EVENT OCR] Paddle run failed:", e)
        return []


def _best_text(raw_texts):
    candidates = [normalize_plate_text(text) for text in raw_texts]
    candidates = [text for text in candidates if text]
    if not candidates:
        return ""
    return max(candidates, key=len)


def _worker():
    while True:
        task = _queue.get()
        try:
            image_path = _url_to_path(task.get("license_img"))
            row_id = task.get("row_id")
            if not image_path or not row_id or not os.path.exists(image_path):
                continue

            started = time.perf_counter()
            raw_texts = _run_plate_ocr(image_path)
            raw_text = _best_text(raw_texts)
            if not raw_text:
                continue

            corrected, reason, score = correct_plate_with_master_or_military_format(
                raw_text,
                min_score=OCR_MIN_SCORE,
                plate_color=task.get("plate_color") or "Black",
            )
            rule_id, _rule_name = class_from_license_rule(corrected)
            elapsed_ms = (time.perf_counter() - started) * 1000

            if rule_id != 0:
                print(f"[EVENT OCR] no military correction row={row_id} raw={raw_text} {elapsed_ms:.0f}ms")
                continue

            update_vehicle_log_plate_from_ocr(
                row_id=row_id,
                license_text=corrected,
                plate_color=task.get("plate_color") or "Black",
                reason=reason,
                score=score,
            )
            print(f"[EVENT OCR] row={row_id} raw={raw_text} corrected={corrected} {elapsed_ms:.0f}ms")
        except Exception as e:
            print("[EVENT OCR] worker error:", e)
        finally:
            _queue.task_done()


def _ensure_worker():
    global _worker_started
    if not OCR_ENABLED:
        return False
    with _worker_lock:
        if _worker_started:
            return True
        thread = threading.Thread(target=_worker, daemon=True, name="Event-Plate-OCR")
        thread.start()
        _worker_started = True
        return True


def enqueue_event_plate_ocr(row_id, license_img, plate_color="", current_license=""):
    if not OCR_ENABLED:
        return {"queued": False, "reason": "disabled"}
    if not row_id or not license_img:
        return {"queued": False, "reason": "missing row/image"}
    if is_civil_plate_color(plate_color):
        return {"queued": False, "reason": "civil plate color"}
    current_rule_id, _current_rule_name = class_from_license_rule(current_license)
    if current_rule_id == 0:
        return {"queued": False, "reason": "already valid military plate"}
    _ensure_worker()
    try:
        _queue.put_nowait({
            "row_id": int(row_id),
            "license_img": license_img,
            "plate_color": plate_color,
            "current_license": current_license,
        })
        return {"queued": True, "size": _queue.qsize()}
    except queue.Full:
        print("[EVENT OCR] queue full; skipped")
        return {"queued": False, "reason": "queue full"}
