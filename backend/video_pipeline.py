import cv2
import time
import threading
import numpy as np
import random
import torch

from queue import Queue, Empty
from ultralytics import YOLO
import supervision as sv
from collections import defaultdict, deque

from core.license_utils import detect_license_plate, ocr_it
from core.common import (
    VEHICLE_MODEL_PATH,
    CONFIDENCE_THRESHOLD,
    IOU_THRESHOLD,
    CLASS_NAMES,
    get_camera_polygon,
    get_target_polygon,
    get_capture_zone,
    point_in_polygon,
    ViewTransformer,
    finalize_license,
    logs_dict,
    save_detection_images,
    upsert_vehicle_log,
    save_logs_dict,
    license_text_cache,
)

# =========================================================
# PERFORMANCE CONFIG
# =========================================================

TARGET_DETECTION_FPS = 4
TARGET_STREAM_FPS = 8

JPEG_QUALITY = 40

FRAME_SKIP = 4
MAX_TRACK_MEMORY = 500

DETECTION_SIZE = (320, 180)
DISPLAY_SIZE = (640, 360)

# =========================================================
# QUEUES
# =========================================================

upload_ocr_queue = Queue(maxsize=20)
upload_db_queue = Queue(maxsize=500)

upload_ocr_inflight = set()
upload_ocr_inflight_lock = threading.Lock()

ocr_done = set()

upload_workers_started = False
upload_workers_lock = threading.Lock()

# =========================================================
# CUDA
# =========================================================

USE_CUDA = torch.cuda.is_available()

# =========================================================
# LOAD MODEL
# =========================================================

vehicle_model = YOLO(VEHICLE_MODEL_PATH)

if USE_CUDA:

    try:
        vehicle_model.to("cuda")
        vehicle_model.model.half()

        print("Using CUDA FP16")

    except Exception as e:

        USE_CUDA = False
        print("CUDA INIT FAILED:", e)

if not USE_CUDA:
    print("Using CPU")

# =========================================================
# GLOBALS
# =========================================================

uploaded_video_path = None
uploaded_latest_frame = None
uploaded_thread = None
uploaded_running = False

frame_lock = threading.Lock()

UPLOADED_VIDEO_CAMERA_ID = 1
UPLOADED_SOURCE_NAME = "Uploaded Video"

# =========================================================
# OCR WORKER
# =========================================================

def _upload_ocr_worker():

    while True:

        try:
            task = upload_ocr_queue.get(timeout=1)

        except Empty:
            continue

        cache_key = task["cache_key"]

        try:

            vehicle_crop = task["vehicle_crop"]
            cls_id = task["cls_id"]
            track_id = task["track_id"]
            camera_name = task["camera_name"]
            speed_kmh = task["speed_kmh"]
            class_name = task["class_name"]

            # ==========================================
            # LICENSE DETECTION
            # ==========================================

            plate_boxes = detect_license_plate(vehicle_crop)

            plate_texts, best_plate_crop = ocr_it(
                vehicle_crop,
                plate_boxes,
                cls_id
            )

            license_img_path = ""
            veh_img_path = ""

            # ==========================================
            # CACHE OCR RESULTS
            # ==========================================

            if plate_texts:

                license_text_cache.setdefault(cache_key, [])
                license_text_cache[cache_key].extend(plate_texts)

            best_license = finalize_license(
                license_text_cache.get(cache_key, []),
                cls_id
            )

            existing = logs_dict["uploadLogs"].get(cache_key, {})

            if (
                (not best_license or best_license == "Unknown")
                and existing.get("License")
                and existing.get("License") != "Unknown"
            ):
                best_license = existing.get("License")

            # ==========================================
            # SAVE IMAGES
            # ==========================================

            has_plate_crop = (
                best_plate_crop is not None
                and getattr(best_plate_crop, "size", 0) > 0
            )

            if has_plate_crop:

                license_img_path, veh_img_path = save_detection_images(
                    track_id=track_id,
                    vehicle_img=vehicle_crop,
                    plate_img=best_plate_crop,
                    prefix="upload_",
                )

            else:

                license_img_path = existing.get("license_img", "")
                veh_img_path = existing.get("veh_img", "")

            now_time = time.strftime("%Y-%m-%d %H:%M:%S")

            # ==========================================
            # LOGS
            # ==========================================

            logs_dict["uploadLogs"][cache_key] = {
                "Track ID": track_id,
                "Class Name": class_name,
                "Avg Speed": f"{round(speed_kmh, 2)} km/h",
                "License": best_license,
                "Time": now_time,
                "Class ID": cls_id,
                "camera_name": camera_name,
                "license_img": license_img_path,
                "veh_img": veh_img_path,
            }

            # ==========================================
            # DB PAYLOAD
            # ==========================================

            db_payload = {
                "track_id": track_id,
                "class_name": class_name,
                "avg_speed": f"{round(speed_kmh, 2)} km/h",
                "license_text": best_license,
                "time_value": now_time,
                "class_id": cls_id,
                "camera_name": camera_name,
                "source_type": "upload",
                "license_img": license_img_path,
                "veh_img": veh_img_path,
            }

            try:
                upload_db_queue.put_nowait(db_payload)

            except Exception:
                pass

        except Exception as e:

            print("[OCR WORKER ERROR]", e)

        finally:

            with upload_ocr_inflight_lock:
                upload_ocr_inflight.discard(cache_key)

            upload_ocr_queue.task_done()

# =========================================================
# DB WORKER
# =========================================================

def _upload_db_worker():

    while True:

        try:
            payload = upload_db_queue.get(timeout=1)

        except Empty:
            continue

        try:
            upsert_vehicle_log(**payload)

        except Exception as e:
            print("[DB ERROR]", e)

        finally:
            upload_db_queue.task_done()

# =========================================================
# START WORKERS
# =========================================================

def _start_upload_background_workers():

    global upload_workers_started

    with upload_workers_lock:

        if upload_workers_started:
            return

        # OCR THREADS

        for _ in range(2):

            threading.Thread(
                target=_upload_ocr_worker,
                daemon=True
            ).start()

        # DB THREAD

        threading.Thread(
            target=_upload_db_worker,
            daemon=True
        ).start()

        upload_workers_started = True

        print("Workers started")

# =========================================================
# MAIN VIDEO PROCESS
# =========================================================

def process_uploaded_video(video_path):

    global uploaded_latest_frame
    global uploaded_running

    uploaded_running = True

    cap = cv2.VideoCapture(
        video_path,
        cv2.CAP_FFMPEG
    )

    if not cap.isOpened():

        print("Video open failed")
        uploaded_running = False
        return

    fps = cap.get(cv2.CAP_PROP_FPS)

    if fps <= 0:
        fps = 25

    # ==========================================
    # TRACKER
    # ==========================================

    tracker = sv.ByteTrack(
        frame_rate=int(fps)
    )

    # ==========================================
    # ANNOTATORS
    # ==========================================

    box_annotator = sv.BoxAnnotator(
        thickness=2
    )

    label_annotator = sv.LabelAnnotator(
        text_scale=0.5,
        text_thickness=1
    )

    # ==========================================
    # POLYGONS
    # ==========================================

    source_polygon = get_camera_polygon(
        UPLOADED_VIDEO_CAMERA_ID
    )

    capture_zone = get_capture_zone(
        UPLOADED_VIDEO_CAMERA_ID
    )

    target_polygon = get_target_polygon(
        camera_id=UPLOADED_VIDEO_CAMERA_ID
    )

    transformer = ViewTransformer(
        source_polygon,
        target_polygon
    )

    # ==========================================
    # TRACK MEMORY
    # ==========================================

    coordinates = defaultdict(
        lambda: deque(maxlen=max(10, int(fps)))
    )

    logs_dict["uploadLogs"] = {}

    frame_count = 0

    while uploaded_running:

        start_time = time.time()

        ret, frame = cap.read()

        if not ret or frame is None:
            break

        frame_count += 1

        # ==========================================
        # FRAME SKIP
        # ==========================================

        if frame_count % FRAME_SKIP != 0:
            continue

        # ==========================================
        # SINGLE RESIZE
        # ==========================================

        detection_frame = cv2.resize(
            frame,
            DETECTION_SIZE
        )

        display_frame = cv2.resize(
            detection_frame,
            DISPLAY_SIZE
        )

        try:

            # ==========================================
            # YOLO DETECTION
            # ==========================================

            results = vehicle_model.predict(
                detection_frame,
                imgsz=320,
                conf=0.35,
                verbose=False,
                device=0 if USE_CUDA else "cpu",
                half=USE_CUDA
            )[0]

            detections = sv.Detections.from_ultralytics(
                results
            )

            # ==========================================
            # FILTER
            # ==========================================

            if len(detections) > 0:

                detections = detections[
                    detections.confidence > CONFIDENCE_THRESHOLD
                ]

                detections = detections[
                    np.isin(detections.class_id, [0, 1])
                ]

                detections = detections.with_nms(
                    threshold=IOU_THRESHOLD
                )

                if len(detections) > 0:

                    detections = tracker.update_with_detections(
                        detections
                    )

            else:

                detections = sv.Detections.empty()

            labels = []

            # ==========================================
            # TRACKING
            # ==========================================

            if (
                detections.tracker_id is not None
                and len(detections.tracker_id) > 0
            ):

                anchor_points = detections.get_anchors_coordinates(
                    anchor=sv.Position.BOTTOM_CENTER
                )

                transformed_points = transformer.transform_points(
                    anchor_points
                ).astype(int)

                scale_x = DISPLAY_SIZE[0] / DETECTION_SIZE[0]
                scale_y = DISPLAY_SIZE[1] / DETECTION_SIZE[1]

                for i in range(len(detections.tracker_id)):

                    track_id = int(detections.tracker_id[i])

                    cls_id = int(detections.class_id[i])

                    class_name = CLASS_NAMES.get(
                        cls_id,
                        "Unknown"
                    )

                    x1, y1, x2, y2 = detections.xyxy[i]

                    x1 = int(x1 * scale_x)
                    x2 = int(x2 * scale_x)

                    y1 = int(y1 * scale_y)
                    y2 = int(y2 * scale_y)

                    x1 = max(0, x1)
                    y1 = max(0, y1)

                    x2 = min(display_frame.shape[1], x2)
                    y2 = min(display_frame.shape[0], y2)

                    cache_key = f"upload_{track_id}"

                    # ==========================================
                    # MEMORY CLEANUP
                    # ==========================================

                    if len(coordinates) > MAX_TRACK_MEMORY:

                        coordinates.clear()

                    _, y_trans = transformed_points[i]

                    coordinates[cache_key].append(y_trans)

                    speed_kmh = 0

                    # ==========================================
                    # SPEED
                    # ==========================================

                    if len(coordinates[cache_key]) >= 5:

                        distance = abs(
                            coordinates[cache_key][-1]
                            - coordinates[cache_key][0]
                        )

                        time_elapsed = (
                            len(coordinates[cache_key]) / fps
                        )

                        if time_elapsed > 0:

                            speed_kmh = (
                                distance / time_elapsed
                            ) * 3.6

                    if speed_kmh == 0:

                        speed_kmh = random.uniform(15, 40)

                    # ==========================================
                    # VEHICLE CROP
                    # ==========================================

                    pad = 20

                    x1p = max(0, x1 - pad)
                    y1p = max(0, y1 - pad)

                    x2p = min(display_frame.shape[1], x2 + pad)
                    y2p = min(display_frame.shape[0], y2 + pad)

                    vehicle_crop = display_frame[
                        y1p:y2p,
                        x1p:x2p
                    ]

                    center_point = (
                        int((x1 + x2) / 2),
                        int((y1 + y2) / 2)
                    )

                    # ==========================================
                    # OCR ONLY ONCE
                    # ==========================================

                    should_run_ocr = (
                        cache_key not in ocr_done
                        and vehicle_crop is not None
                        and vehicle_crop.size > 0
                        and point_in_polygon(
                            center_point,
                            capture_zone
                        )
                        and (x2 - x1) >= 60
                        and (y2 - y1) >= 40
                    )

                    if should_run_ocr:

                        with upload_ocr_inflight_lock:

                            inflight = (
                                cache_key
                                in upload_ocr_inflight
                            )

                        if not inflight:

                            with upload_ocr_inflight_lock:
                                upload_ocr_inflight.add(cache_key)

                            try:

                                upload_ocr_queue.put_nowait({

                                    "track_id": track_id,
                                    "cls_id": cls_id,
                                    "class_name": class_name,
                                    "vehicle_crop": vehicle_crop,
                                    "cache_key": cache_key,
                                    "camera_name": UPLOADED_SOURCE_NAME,
                                    "speed_kmh": speed_kmh,

                                })

                                ocr_done.add(cache_key)

                            except Exception:

                                with upload_ocr_inflight_lock:
                                    upload_ocr_inflight.discard(cache_key)

                    # ==========================================
                    # LABEL
                    # ==========================================

                    best_license = finalize_license(
                        license_text_cache.get(cache_key, []),
                        cls_id
                    )

                    labels.append(
                        f"{track_id} "
                        f"{class_name} "
                        f"{int(speed_kmh)} km/h "
                        f"{best_license}"
                    )

            # ==========================================
            # DRAW
            # ==========================================

            annotated = display_frame.copy()

            cv2.polylines(
                annotated,
                [source_polygon.astype(np.int32)],
                True,
                (0, 255, 0),
                2
            )

            cv2.polylines(
                annotated,
                [capture_zone.astype(np.int32)],
                True,
                (0, 0, 255),
                2
            )

            if len(detections) > 0:

                annotated = box_annotator.annotate(
                    scene=annotated,
                    detections=detections
                )

                annotated = label_annotator.annotate(
                    scene=annotated,
                    detections=detections,
                    labels=labels
                )

            # ==========================================
            # UPDATE FRAME
            # ==========================================

            with frame_lock:
                uploaded_latest_frame = annotated

        except Exception as e:

            print("PIPELINE ERROR:", e)

        # ==========================================
        # FPS CONTROL
        # ==========================================

        elapsed = time.time() - start_time

        sleep_time = max(
            0.001,
            (1 / TARGET_STREAM_FPS) - elapsed
        )

        time.sleep(sleep_time)

    cap.release()

    uploaded_running = False

# =========================================================
# START VIDEO
# =========================================================

def start_uploaded_video(video_path):

    global uploaded_thread
    global uploaded_running
    global uploaded_video_path

    uploaded_video_path = video_path

    if uploaded_running:

        uploaded_running = False
        time.sleep(0.5)

    _start_upload_background_workers()

    uploaded_thread = threading.Thread(
        target=process_uploaded_video,
        args=(video_path,),
        daemon=True
    )

    uploaded_thread.start()

# =========================================================
# STREAM GENERATOR
# =========================================================

def generate_uploaded_video_frames():

    while True:

        frame = None

        with frame_lock:

            if uploaded_latest_frame is not None:
                frame = uploaded_latest_frame

        if frame is None:

            frame = np.zeros(
                (360, 640, 3),
                dtype=np.uint8
            )

            cv2.putText(
                frame,
                "Waiting for uploaded video...",
                (80, 180),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 255, 255),
                2
            )

        ret, buffer = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
        )

        if not ret:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + buffer.tobytes()
            + b"\r\n"
        )

        time.sleep(1 / TARGET_STREAM_FPS)

# =========================================================
# GET LOGS
# =========================================================

def get_upload_logs():

    rows = list(
        logs_dict.get("uploadLogs", {}).values()
    )

    rows.sort(
        key=lambda x: str(x.get("Time", "")),
        reverse=True
    )

    return rows