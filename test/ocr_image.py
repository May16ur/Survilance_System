"""Run PaddleOCR on one plate image and print the result.

Usage:
    python test/ocr_image.py C:\path\to\plate.jpg
    python test/ocr_image.py C:\path\to\plate.jpg --variants balanced
    python test/ocr_image.py C:\path\to\plate.jpg --det
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")

ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

import cv2  # noqa: E402

from test_paddle_mil_ocr_speed import (  # noqa: E402
    best_text,
    build_variants,
    run_ocr,
)


def load_reader():
    from paddleocr import PaddleOCR

    try:
        return PaddleOCR(use_textline_orientation=False, lang="en")
    except Exception:
        try:
            return PaddleOCR(use_angle_cls=False, lang="en")
        except Exception:
            return PaddleOCR(lang="en")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PaddleOCR on a single plate image.")
    parser.add_argument("image", help="Image path")
    parser.add_argument("--variants", choices=("fast", "balanced"), default="fast")
    parser.add_argument("--det", action="store_true", help="Use Paddle detection+recognition instead of recognition-only.")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.is_absolute():
        image_path = ROOT / image_path

    if not image_path.exists():
        print(f"Image not found: {image_path}")
        return 1

    img = cv2.imread(str(image_path))
    if img is None or img.size == 0:
        print(f"Could not read image: {image_path}")
        return 1

    print("Loading PaddleOCR...")
    started = time.perf_counter()
    reader = load_reader()
    load_ms = (time.perf_counter() - started) * 1000.0

    variants = build_variants(img, args.variants)
    if not variants:
        print("Could not prepare OCR image variant.")
        return 1

    started = time.perf_counter()
    raw_outputs = []
    for variant in variants:
        raw_outputs.extend(run_ocr(reader, variant, recognition_only=not args.det))
    ocr_ms = (time.perf_counter() - started) * 1000.0

    cleaned_best = best_text(raw_outputs)

    print()
    print(f"Image: {image_path}")
    print(f"Mode: variants={args.variants}, paddle={'det+rec' if args.det else 'rec-only'}")
    print(f"Load time: {load_ms:.1f} ms")
    print(f"OCR time: {ocr_ms:.1f} ms")
    print()
    print("Raw OCR outputs:")
    if raw_outputs:
        for item in raw_outputs:
            print(f"- {item}")
    else:
        print("- NO_TEXT")
    print()
    print(f"Best cleaned text: {cleaned_best or 'NO_TEXT'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
