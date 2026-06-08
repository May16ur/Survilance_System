"""Benchmark PaddleOCR on military plate crops without touching live camera code.

Examples:
    python test/test_paddle_mil_ocr_speed.py --path backend/flask_app/static/anpr --fps 5
    python test/test_paddle_mil_ocr_speed.py --path C:\plates --repeat 3 --variants fast
    python test/test_paddle_mil_ocr_speed.py --path plate.jpg --plate-color Black

Notes:
    - This imports PaddleOCR directly and does not import the YOLO plate detector.
    - Use plate cutout images for the most honest speed result.
    - If you pass vehicle/body images, OCR will be slower and less accurate.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from core.common import (  # noqa: E402
    correct_plate_with_master_or_military_format,
    normalize_plate_text,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def iter_images(path: Path):
    if path.is_file():
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path
        return
    for item in sorted(path.rglob("*")):
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS:
            yield item


def force_bgr(img):
    if img is None or img.size == 0:
        return None
    if len(img.shape) == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


def resize_for_ocr(img, target_h=96):
    img = force_bgr(img)
    if img is None:
        return None
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return None
    scale = target_h / float(h)
    new_w = max(180, min(640, int(w * scale)))
    return cv2.resize(img, (new_w, target_h), interpolation=cv2.INTER_CUBIC)


def crop_center_band(img):
    img = force_bgr(img)
    if img is None:
        return None
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return None
    aspect = w / max(1, h)
    if 2.0 <= aspect <= 9.0 and h <= 160:
        return img
    return img[int(h * 0.25):int(h * 0.82), int(w * 0.04):int(w * 0.96)]


def build_variants(img, mode):
    crop = crop_center_band(img)
    base = resize_for_ocr(crop, target_h=96)
    if base is None:
        return []
    if mode == "fast":
        return [base]

    gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    sharp = cv2.filter2D(clahe, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]]))
    _, th = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return [
        base,
        cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR),
        cv2.cvtColor(th, cv2.COLOR_GRAY2BGR),
    ]


def flatten_paddle_result(result):
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
    out = []
    seen = set()
    for text in texts:
        if text not in seen:
            out.append(text)
            seen.add(text)
    return out


def run_ocr(reader, img, recognition_only=True):
    outputs = []
    if recognition_only:
        try:
            result = reader.ocr(img, det=False, cls=False)
        except TypeError:
            result = reader.ocr(img, det=False)
        outputs.extend(flatten_paddle_result(result))
    else:
        try:
            result = reader.ocr(img, cls=False)
        except TypeError:
            result = reader.ocr(img)
        outputs.extend(flatten_paddle_result(result))
    return outputs


def best_text(raw_texts):
    candidates = []
    for text in raw_texts:
        cleaned = normalize_plate_text(text)
        if cleaned:
            candidates.append(cleaned)
    if not candidates:
        return ""
    return max(candidates, key=len)


def percentile(values, pct):
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(round((pct / 100.0) * (len(values) - 1))))
    return values[idx]


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark PaddleOCR speed on plate images.")
    parser.add_argument("--path", required=True, help="Image file or folder containing plate images.")
    parser.add_argument("--repeat", type=int, default=1, help="OCR repeats per image after warmup.")
    parser.add_argument("--fps", type=float, default=5.0, help="Target live FPS to compare against.")
    parser.add_argument("--variants", choices=("fast", "balanced"), default="fast", help="fast=1 variant, balanced=3 variants.")
    parser.add_argument("--plate-color", default="Black", help="Plate color passed to military DB correction.")
    parser.add_argument("--det", action="store_true", help="Use Paddle detection+recognition instead of recognition-only.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of images.")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.is_absolute():
        path = ROOT / path
    images = list(iter_images(path))
    if args.limit > 0:
        images = images[:args.limit]
    if not images:
        print(f"No image files found: {path}")
        return 1

    print("Loading PaddleOCR...")
    start = time.perf_counter()
    from paddleocr import PaddleOCR

    try:
        reader = PaddleOCR(use_angle_cls=False, lang="en")
    except Exception:
        reader = PaddleOCR(lang="en")
    load_ms = (time.perf_counter() - start) * 1000.0
    print(f"PaddleOCR load time: {load_ms:.1f} ms")

    budget_ms = 1000.0 / max(0.1, args.fps)
    all_times = []
    rows = []

    for image_path in images:
        img = cv2.imread(str(image_path))
        variants = build_variants(img, args.variants)
        if not variants:
            rows.append((image_path.name, "READ_FAIL", "", "", 0.0, 0.0, False))
            continue

        # Warmup once per image shape to avoid counting first-call setup.
        try:
            run_ocr(reader, variants[0], recognition_only=not args.det)
        except Exception as exc:
            rows.append((image_path.name, "OCR_ERROR", str(exc), "", 0.0, 0.0, False))
            continue

        image_times = []
        raw_outputs = []
        for _ in range(max(1, args.repeat)):
            started = time.perf_counter()
            raw_outputs.clear()
            for variant in variants:
                raw_outputs.extend(run_ocr(reader, variant, recognition_only=not args.det))
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            image_times.append(elapsed_ms)
            all_times.append(elapsed_ms)

        text = best_text(raw_outputs)
        corrected, reason, score = correct_plate_with_master_or_military_format(
            text,
            plate_color=args.plate_color,
        )
        avg_ms = statistics.mean(image_times)
        rows.append((
            image_path.name,
            text or "NO_TEXT",
            corrected or "",
            reason,
            score,
            avg_ms,
            avg_ms <= budget_ms,
        ))

    print()
    print(f"Target FPS budget: {budget_ms:.1f} ms per OCR call")
    print(f"Mode: variants={args.variants}, paddle={'det+rec' if args.det else 'rec-only'}, repeat={args.repeat}")
    print()
    header = ("file", "ocr_text", "corrected", "reason", "score", "avg_ms", "ok")
    widths = [max(len(header[i]), *(len(str(row[i])) for row in rows)) for i in range(len(header))]
    print(" | ".join(header[i].ljust(widths[i]) for i in range(len(header))))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        printable = list(row)
        printable[4] = str(printable[4])
        printable[5] = f"{float(printable[5]):.1f}"
        printable[6] = "YES" if printable[6] else "NO"
        print(" | ".join(str(printable[i]).ljust(widths[i]) for i in range(len(header))))

    if all_times:
        print()
        print(
            "Latency summary: "
            f"avg={statistics.mean(all_times):.1f} ms, "
            f"p50={statistics.median(all_times):.1f} ms, "
            f"p95={percentile(all_times, 95):.1f} ms, "
            f"max={max(all_times):.1f} ms"
        )
        if statistics.mean(all_times) > budget_ms:
            print("Result: too slow for synchronous live OCR at this FPS. Use queue/background OCR.")
        else:
            print("Result: within single-camera synchronous budget. For many cameras, still use background OCR.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
