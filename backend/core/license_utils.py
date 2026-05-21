import os
import re
import time
import cv2
import numpy as np
from ultralytics import YOLO

# ==========================================================
# PaddleOCR ONLY
# ==========================================================
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
os.environ["FLAGS_enable_pir_api"] = "0"

from paddleocr import PaddleOCR

from core.common import (
    LICENSE_MODEL_PATH,
    LICENSE_CONFIDENCE_THRESHOLD,
)

DEBUG_SAVE_PLATE = False
MAX_OCR_VARIANTS = 4
OCR_VERBOSE = False

# ==========================================================
# LOAD LICENSE PLATE DETECTOR
# ==========================================================
license_model = YOLO(LICENSE_MODEL_PATH)

try:
    license_model.to("cuda")
    try:
        license_model.fuse()
    except Exception:
        pass
    print("[PLATE MODEL] Using CUDA")
except Exception as e:
    print("[PLATE MODEL] Using CPU:", e)


# ==========================================================
# LAZY LOAD PADDLEOCR
# ==========================================================
paddle_reader = None


def get_paddle_ocr():
    global paddle_reader
    if paddle_reader is None:
        if OCR_VERBOSE:
            print("[OCR] Loading PaddleOCR only...")
        try:
            paddle_reader = PaddleOCR(use_angle_cls=False, lang="en")
        except Exception:
            paddle_reader = PaddleOCR(lang="en")
        if OCR_VERBOSE:
            print("[OCR] PaddleOCR loaded")
    return paddle_reader


# ==========================================================
# PLATE FORMAT RULES
# ==========================================================
VALID_STATE_CODES = {
    "JK", "LA", "WB", "TN", "CH", "DL", "NL", "MH", "MP", "AP", "HP",
    "AR", "PY", "GA", "UP", "GJ", "OD", "BR", "PB", "HR", "CG",
    "KA", "TS", "RJ", "AS", "KL", "UK"
}

CIVIL_PATTERNS = [
    re.compile(r"^[A-Z]{2}\d{2}[A-Z]\d{4}$"),       # LA02G0195 / LA02A2233
    re.compile(r"^[A-Z]{2}\d{2}[A-Z]{2}\d{4}$"),    # MH12AB1234
    re.compile(r"^[A-Z]{2}\d{2}[A-Z]{3}\d{4}$"),
    re.compile(r"^(LA|JK)\d{2}\d{4}$"),             # JK102033
]

MIL_THIRD_ALLOWED = set("NPAFDCB")
MIL_LAST_ALLOWED = set("PMNXYKLWHEA")
MILITARY_PATTERN = re.compile(r"^(1[2-9]|2[0-6])[NPAFDCB]\d{6}[PMNXYKLWHEA]$")


def clean_plate_text(txt):
    if not txt:
        return ""

    txt = str(txt).upper().strip()

    for ch in ["↑", "^", "→", "↟", "⬆", "➜", " ", "-", ".", ":", "/", "\\", "_", "|", "'", '"']:
        txt = txt.replace(ch, "")

    return "".join(ch for ch in txt if ch.isalnum())


def _to_digit(ch):
    return {
        "O": "0", "Q": "0", "D": "0", "U": "0",
        "I": "1", "L": "1", "T": "1", "J": "1",
        "Z": "2",
        "S": "5",
        "B": "8",
        "G": "6",
        "A": "4",
    }.get(ch, ch)


def _to_letter(ch):
    return {
        "0": "O",
        "1": "I",
        "2": "Z",
        "4": "A",
        "5": "S",
        "8": "B",
        "6": "G",
        "7": "T",
    }.get(ch, ch)


def _fix_state_code(text):
    if len(text) < 2:
        return text

    first = _to_letter(text[0])
    second = _to_letter(text[1])
    state = first + second

    corrections = {
        "L4": "LA", "1A": "LA", "I4": "LA", "IA": "LA",
        "JX": "JK", "IK": "JK", "1K": "JK", "JH": "JK",
        "0D": "OD", "O0": "OD",
        "D1": "DL", "0L": "DL",
        "M8": "MP",
        "N1": "NL",
    }

    state = corrections.get(state, state)
    return state + text[2:]


def restore_civil(txt):
    """
    Supported:
    LA02G0195
    LA02A2233
    MH12AB1234
    JK102033
    """
    txt = clean_plate_text(txt)
    n = len(txt)

    # JK102033 / LA021234 style
    if n == 8:
        chars = list(txt)
        chars[0] = _to_letter(chars[0])
        chars[1] = _to_letter(chars[1])
        for i in range(2, n):
            chars[i] = _to_digit(chars[i])
        return _fix_state_code("".join(chars))

    # AA00A0000 / AA00AA0000 / AA00AAA0000
    if n == 9:
        letter_pos = {0, 1, 4}
    elif n == 10:
        letter_pos = {0, 1, 4, 5}
    elif n == 11:
        letter_pos = {0, 1, 4, 5, 6}
    else:
        return txt

    chars = list(txt)
    for i in range(n):
        if i in letter_pos:
            chars[i] = _to_letter(chars[i])
        else:
            chars[i] = _to_digit(chars[i])

    return _fix_state_code("".join(chars))


def restore_military(txt):
    """
    Military format:
    12-26 + N/P/A/F/D/C/B + 6 digits + P/M/N/X/Y/K/L/W/H/E/A
    Example: 17D205014M, 24B140639N
    """
    txt = clean_plate_text(txt)

    if len(txt) != 10:
        return txt

    chars = list(txt)

    chars[0] = _to_digit(chars[0])
    chars[1] = _to_digit(chars[1])

    chars[2] = _to_letter(chars[2])
    chars[2] = {
        "8": "B",
        "6": "B",
        "0": "D",
        "O": "D",
        "4": "A",
        "1": "N",
    }.get(chars[2], chars[2])

    for i in range(3, 9):
        chars[i] = _to_digit(chars[i])

    chars[9] = _to_letter(chars[9])
    chars[9] = {
        "0": "O",
        "1": "I",
        "4": "A",
    }.get(chars[9], chars[9])

    return "".join(chars)


def is_valid_civil(txt):
    fixed = restore_civil(txt)

    if len(fixed) not in (8, 9, 10, 11):
        return False

    if fixed[:2] not in VALID_STATE_CODES:
        return False

    return any(pattern.fullmatch(fixed) for pattern in CIVIL_PATTERNS)


def is_valid_military(txt):
    fixed = restore_military(txt)
    return bool(MILITARY_PATTERN.fullmatch(fixed))


def class_from_plate(plate):
    plate = clean_plate_text(plate)

    if is_valid_military(plate):
        return 0, "Mil Veh"

    if is_valid_civil(plate):
        return 1, "Civil Veh"

    return None, None


def _looks_bad_civil(txt):
    """
    Reject impossible OCR like CICF2017:
    it starts with CI, which is not an allowed civil state code.
    """
    txt = clean_plate_text(txt)

    if len(txt) in (8, 9, 10, 11) and txt[:2].isalpha():
        if txt[:2] not in VALID_STATE_CODES:
            if not is_valid_military(txt):
                return True

    return False


def plate_score(txt, cls_id=None):
    txt = clean_plate_text(txt)

    if not txt:
        return -999

    mil = restore_military(txt)
    civ = restore_civil(txt)

    if is_valid_military(mil):
        return 1300

    if is_valid_civil(civ):
        return 1250

    if _looks_bad_civil(txt):
        return -250

    score = 0

    # Military-like score
    if len(mil) == 10:
        score += 120

    if len(mil) >= 2 and mil[:2].isdigit():
        try:
            if 12 <= int(mil[:2]) <= 26:
                score += 160
        except Exception:
            pass

    if len(mil) >= 3 and mil[2] in MIL_THIRD_ALLOWED:
        score += 110

    if len(mil) >= 9 and mil[3:9].isdigit():
        score += 110

    if len(mil) >= 10 and mil[-1] in MIL_LAST_ALLOWED:
        score += 70

    # Civil-like score
    if len(civ) in (8, 9, 10, 11):
        score += 90

    if len(civ) >= 2 and civ[:2] in VALID_STATE_CODES:
        score += 220

    if sum(ch.isdigit() for ch in civ) >= 5:
        score += 80

    if sum(ch.isalpha() for ch in civ) >= 2:
        score += 50

    if len(txt) < 7 or len(txt) > 12:
        score -= 150

    return score


def build_candidates(raw_texts, cls_id=None):
    candidates = set()

    for raw in raw_texts:
        base = clean_plate_text(raw)
        if not base:
            continue

        possible = [base]

        if len(base) > 7:
            possible.append(base[1:])
            possible.append(base[:-1])

        if len(base) > 11:
            for size in (8, 9, 10, 11):
                for start in range(0, len(base) - size + 1):
                    possible.append(base[start:start + size])

        for item in possible:
            item = clean_plate_text(item)
            if 4 <= len(item) <= 14:
                candidates.add(item)
                candidates.add(restore_civil(item))
                candidates.add(restore_military(item))

    ranked = sorted(candidates, key=lambda x: plate_score(x, cls_id), reverse=True)
    return ranked


def choose_final_text(raw_texts, cls_id=None):
    candidates = build_candidates(raw_texts, cls_id)

    if OCR_VERBOSE:
        print("[OCR CANDIDATES] =>", candidates)

    # Strict valid format first
    for candidate in candidates:
        mil = restore_military(candidate)
        if is_valid_military(mil):
            return [mil]

        civ = restore_civil(candidate)
        if is_valid_civil(civ):
            return [civ]

    return []


# ==========================================================
# IMAGE PREPROCESSING
# ==========================================================

def _force_bgr(img):
    if img is None or img.size == 0:
        return None

    if len(img.shape) == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    return img


def _resize_for_ocr(img, target_h=135):
    if img is None or img.size == 0:
        return img

    h, w = img.shape[:2]

    if h <= 0 or w <= 0:
        return img

    scale = target_h / float(h)
    new_w = int(w * scale)
    new_w = max(320, min(new_w, 820))

    return cv2.resize(img, (new_w, target_h), interpolation=cv2.INTER_CUBIC)


def _trim_text_band(img):
    if img is None or img.size == 0:
        return img

    img = _force_bgr(img)
    h, w = img.shape[:2]

    if h <= 0 or w <= 0:
        return img

    aspect = w / max(1, h)

    if 2.0 <= aspect <= 8.0 and h <= 110:
        return img

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8)).apply(gray)

    grad = cv2.Sobel(gray, cv2.CV_8U, 1, 0, ksize=3)

    _, th = cv2.threshold(
        grad,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 3))
    morph = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(
        morph,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    best = None
    best_score = -1

    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)

        if bw < 45 or bh < 8:
            continue

        ratio = bw / max(1, bh)

        if not (2.0 <= ratio <= 12.0):
            continue

        area = bw * bh
        center_bonus = 1.0 - abs((y + bh / 2) - h / 2) / max(1, h)
        score = area * max(0.25, center_bonus)

        if score > best_score:
            best_score = score
            best = (x, y, bw, bh)

    if best is not None:
        x, y, bw, bh = best

        px = max(5, int(bw * 0.14))
        py = max(4, int(bh * 0.70))

        crop = img[
            max(0, y - py):min(h, y + bh + py),
            max(0, x - px):min(w, x + bw + px)
        ]

        if crop is not None and crop.size > 0:
            return crop

    return img[
        int(h * 0.18):int(h * 0.88),
        int(w * 0.02):int(w * 0.98)
    ]


def preprocess_plate_variants(plate_img):
    variants = []

    if plate_img is None or plate_img.size == 0:
        return variants

    plate_img = _trim_text_band(plate_img)
    plate_img = _force_bgr(plate_img)

    base = _resize_for_ocr(plate_img, target_h=135)

    if base is None or base.size == 0:
        return variants

    variants.append(base)

    gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=4.5, tileGridSize=(8, 8))
    cl = clahe.apply(gray)

    gamma_table = np.array(
        255 * (np.arange(256) / 255.0) ** 0.55,
        dtype="uint8"
    )
    bright = cv2.LUT(cl, gamma_table)

    denoise = cv2.bilateralFilter(bright, 7, 70, 70)

    kernel = np.array([
        [0, -1, 0],
        [-1, 5.8, -1],
        [0, -1, 0]
    ])
    sharp = cv2.filter2D(denoise, -1, kernel)

    _, th_white = cv2.threshold(
        sharp,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    _, th_black = cv2.threshold(
        sharp,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    adaptive = cv2.adaptiveThreshold(
        sharp,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        7
    )

    morph_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    close = cv2.morphologyEx(th_white, cv2.MORPH_CLOSE, morph_kernel, iterations=1)
    openv = cv2.morphologyEx(th_white, cv2.MORPH_OPEN, morph_kernel, iterations=1)

    for g in [
        cl,
        bright,
        denoise,
        sharp,
        th_white,
        th_black,
        adaptive,
        close,
        openv,
    ]:
        variants.append(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))

    return variants[:MAX_OCR_VARIANTS]


def _save_debug_crop(img, name="plate"):
    if not DEBUG_SAVE_PLATE:
        return

    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        debug_dir = os.path.join(base_dir, "flask_app", "static", "debug_ocr")
        os.makedirs(debug_dir, exist_ok=True)

        path = os.path.join(debug_dir, f"{name}_{int(time.time() * 1000)}.jpg")
        cv2.imwrite(path, img)
        if OCR_VERBOSE:
            print("[OCR DEBUG CROP SAVED] =>", path)

    except Exception as e:
        if OCR_VERBOSE:
            print("[OCR DEBUG SAVE ERROR] =>", e)


# ==========================================================
# PLATE DETECTION
# ==========================================================

def _expand_box(x1, y1, x2, y2, img_w, img_h):
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)

    pad_x = max(5, int(w * 0.08))
    pad_y = max(4, int(h * 0.14))

    return (
        max(0, x1 - pad_x),
        max(0, y1 - pad_y),
        min(img_w, x2 + pad_x),
        min(img_h, y2 + pad_y),
    )


def _fallback_plate_boxes(vehicle_crop):
    boxes = []

    if vehicle_crop is None or vehicle_crop.size == 0:
        return boxes

    h, w = vehicle_crop.shape[:2]

    candidates = [
        (int(w * 0.10), int(h * 0.42), int(w * 0.90), int(h * 0.78)),
        (int(w * 0.16), int(h * 0.50), int(w * 0.84), int(h * 0.82)),
        (int(w * 0.18), int(h * 0.30), int(w * 0.82), int(h * 0.62)),
        (int(w * 0.25), int(h * 0.38), int(w * 0.75), int(h * 0.70)),
    ]

    for x1, y1, x2, y2 in candidates:
        if (x2 - x1) >= 55 and (y2 - y1) >= 14:
            boxes.append((x1, y1, x2, y2, 0.01))

    return boxes


def detect_license_plate(vehicle_crop):
    plate_boxes = []

    if vehicle_crop is None or vehicle_crop.size == 0:
        return plate_boxes

    img_h, img_w = vehicle_crop.shape[:2]

    try:
        results = license_model.predict(
            vehicle_crop,
            verbose=False,
            imgsz=416
        )[0]

    except Exception as e:
        print("[PLATE DET ERROR] =>", e)
        return _fallback_plate_boxes(vehicle_crop)[:2]

    if results.boxes is not None:
        for box in results.boxes:
            conf = float(box.conf[0])

            if conf < LICENSE_CONFIDENCE_THRESHOLD:
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

            x1, y1, x2, y2 = _expand_box(
                x1,
                y1,
                x2,
                y2,
                img_w,
                img_h
            )

            bw = x2 - x1
            bh = y2 - y1

            if bw < 45 or bh < 10:
                continue

            ratio = bw / max(1, bh)

            if 1.4 <= ratio <= 12.0:
                plate_boxes.append((x1, y1, x2, y2, conf))

    plate_boxes = sorted(plate_boxes, key=lambda x: x[4], reverse=True)

    if not plate_boxes:
        plate_boxes = _fallback_plate_boxes(vehicle_crop)

    return plate_boxes[:3]


# ==========================================================
# PADDLE OCR RUNNER
# ==========================================================

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

    # PaddleOCR v3 fallback string parse
    try:
        s = str(result)
        texts.extend(re.findall(r"'rec_text':\s*'([^']+)'", s))
        texts.extend(re.findall(r'"rec_text":\s*"([^"]+)"', s))
    except Exception:
        pass

    out = []
    seen = set()

    for text in texts:
        if text not in seen:
            out.append(text)
            seen.add(text)

    return out


def _run_paddle(img, tag=""):
    if img is None or img.size == 0:
        return []

    img = _force_bgr(img)
    reader = get_paddle_ocr()
    outputs = []

    # Detection + recognition mode
    try:
        try:
            result = reader.ocr(img, cls=False)
        except TypeError:
            result = reader.ocr(img)

        outputs.extend(_flatten_paddle_result(result))

    except Exception as e:
        if OCR_VERBOSE:
            print(f"[PADDLE ERROR DET {tag}] =>", e)

    # Recognition-only mode on already cropped plate line
    try:
        try:
            result = reader.ocr(img, det=False, cls=False)
        except TypeError:
            result = reader.ocr(img, det=False)

        outputs.extend(_flatten_paddle_result(result))

    except Exception:
        pass

    out = []
    seen = set()

    for item in outputs:
        if item not in seen:
            out.append(item)
            seen.add(item)

    if OCR_VERBOSE:
        print(f"[PADDLE RAW {tag}] =>", out)

    return out


# ==========================================================
# MAIN OCR FUNCTION
# ==========================================================

def ocr_it(vehicle_crop, plate_boxes, cls_id=None):
    texts = []
    best_plate_crop = None

    if vehicle_crop is None or vehicle_crop.size == 0:
        if OCR_VERBOSE:
            print("[OCR] Empty vehicle crop")
        return texts, best_plate_crop

    if not plate_boxes:
        if OCR_VERBOSE:
            print("[OCR] No plate boxes from detector, using fallback boxes")
        plate_boxes = _fallback_plate_boxes(vehicle_crop)

    for idx, box in enumerate(plate_boxes[:3]):
        try:
            x1, y1, x2, y2 = map(int, box[:4])
            conf = float(box[4]) if len(box) > 4 else 0.0
        except Exception:
            continue

        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(vehicle_crop.shape[1], x2)
        y2 = min(vehicle_crop.shape[0], y2)

        raw_crop = vehicle_crop[y1:y2, x1:x2]

        if raw_crop is None or raw_crop.size == 0:
            continue

        plate_crop = _trim_text_band(raw_crop)

        if plate_crop is None or plate_crop.size == 0:
            continue

        ph, pw = plate_crop.shape[:2]

        if pw < 35 or ph < 9:
            if OCR_VERBOSE:
                print("[OCR] Plate crop too small:", pw, ph)
            continue

        best_plate_crop = plate_crop.copy()
        _save_debug_crop(best_plate_crop, name=f"plate_{idx + 1}")

        if OCR_VERBOSE:
            print(
                f"[OCR] FINAL CROP #{idx + 1}: "
                f"box=({x1},{y1},{x2},{y2}) "
                f"conf={conf:.3f} size=({pw}x{ph})"
            )

        raw_texts = []

        variants = preprocess_plate_variants(plate_crop)

        for vi, img in enumerate(variants[:MAX_OCR_VARIANTS]):
            raw_texts.extend(
                _run_paddle(
                    img,
                    tag=f"p{idx + 1}_v{vi + 1}"
                )
            )

        final = choose_final_text(raw_texts, cls_id)

        if OCR_VERBOSE:
            print("[PADDLE OCR FINAL] =>", final)

        for item in final:
            if item not in texts:
                texts.append(item)

        if texts:
            break

    return texts, best_plate_crop
