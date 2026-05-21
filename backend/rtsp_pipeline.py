import os
os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"
RTSP_TRANSPORT = os.getenv("ETCP_RTSP_TRANSPORT", "udp").strip().lower()
if RTSP_TRANSPORT not in ("udp", "tcp"):
    RTSP_TRANSPORT = "udp"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    f"rtsp_transport;{RTSP_TRANSPORT}|fflags;nobuffer|flags;low_delay|"
    "stimeout;3000000|rw_timeout;3000000|max_delay;0|reorder_queue_size;0|analyzeduration;0|probesize;32"
)

import cv2
import time
import threading
import math
import numpy as np
import supervision as sv
from ultralytics import YOLO
from collections import defaultdict, deque
from queue import Queue, Empty

try:
    import torch
    torch.set_num_threads(max(1, int(os.getenv("ETCP_TORCH_THREADS", "2"))))
except Exception:
    torch = None

from core.license_utils import detect_license_plate, ocr_it
from core.common import (
    VEHICLE_MODEL_PATH,
    CONFIDENCE_THRESHOLD,
    IOU_THRESHOLD,
    CLASS_NAMES,
    CAMERA_NAME_MAP,
    logs_dict,
    log_lock,
    license_text_cache,
    finalize_license,
    save_logs_dict,
    upsert_vehicle_log,
    ensure_database,
    ensure_table,
    ViewTransformer,
    get_camera_polygon,
    get_target_polygon,
    get_capture_zone,
    point_in_polygon,
    save_detection_images,
    class_from_license_rule,
    is_valid_license_text,
    normalize_plate_text,
)

import random

cv2.setNumThreads(1)

vehicle_model = YOLO(VEHICLE_MODEL_PATH)
vehicle_model_lock = threading.Lock()
MODEL_DEVICE = "cpu"
try:
    vehicle_model.to("cuda")
    MODEL_DEVICE = "cuda"
    try:
        vehicle_model.fuse()
    except Exception:
        pass
    if torch is not None:
        try:
            vehicle_model.model.half()
        except Exception:
            pass
    print("[VEHICLE MODEL] Using CUDA")
except Exception:
    print("CUDA not available, using CPU")

MAX_CAMERAS = 14
camera_urls = {i: "" for i in range(1, MAX_CAMERAS + 1)}
latest_frames = {}
latest_encoded_frames = {}
latest_frame_times = defaultdict(float)
frame_locks = {i: threading.Lock() for i in range(1, MAX_CAMERAS + 1)}
camera_threads = {}
camera_running = {i: False for i in range(1, MAX_CAMERAS + 1)}
camera_stats = defaultdict(lambda: {
    "capture_frames": 0,
    "detect_frames": 0,
    "skipped_frames": 0,
    "detections": 0,
    "published_frames": 0,
})
stats_lock = threading.Lock()

# =========================
# PERFORMANCE FIX
# OCR and DB writes are done in background threads.
# This keeps RTSP frames and browser streaming smooth.
# =========================
ocr_queue = Queue(maxsize=10)
db_queue = Queue(maxsize=500)

ocr_inflight = set()
ocr_inflight_lock = threading.Lock()

last_ocr_request_time = defaultdict(float)
last_db_write_time = defaultdict(float)
last_db_license = {}
last_db_images = {}

workers_started = False
workers_lock = threading.Lock()
logs_dirty = False
logs_dirty_lock = threading.Lock()

# Larger intervals reduce OCR/DB pressure when 4-10 cameras are active.
OCR_MIN_INTERVAL_SEC = float(os.getenv("ETCP_OCR_MIN_INTERVAL_SEC", "8.0"))
DB_MIN_INTERVAL_SEC = 10.0
LOG_FLUSH_INTERVAL_SEC = 3.0

# Run YOLO on every Nth frame. Preview remains live between detection frames.
# Higher value = smoother stream (less processing lag), lower value = more frequent detection.
DEFAULT_PROCESS_EVERY_N_FRAMES = "6" if MODEL_DEVICE == "cuda" else "10"
PROCESS_EVERY_N_FRAMES = max(1, int(os.getenv("ETCP_PROCESS_EVERY_N_FRAMES", DEFAULT_PROCESS_EVERY_N_FRAMES)))
PREVIEW_SIZE = (640, 360)
STREAM_SIZE = (
    max(640, min(1280, int(os.getenv("ETCP_STREAM_WIDTH", "960")))),
    max(360, min(720, int(os.getenv("ETCP_STREAM_HEIGHT", "540")))),
)
STREAM_JPEG_QUALITY = max(35, min(95, int(os.getenv("ETCP_STREAM_JPEG_QUALITY", "82"))))
STREAM_FPS = max(5, min(25, int(os.getenv("ETCP_STREAM_FPS", "12"))))
RAW_PUBLISH_INTERVAL_SEC = 1.0 / STREAM_FPS
RTSP_GRAB_DROPS = max(0, min(12, int(os.getenv("ETCP_RTSP_GRAB_DROPS", "5"))))
PUBLISH_DETECTION_OVERLAY = os.getenv("ETCP_PUBLISH_DETECTION_OVERLAY", "1").strip().lower() in ("1", "true", "yes", "on")
SHOW_ROI_OVERLAY = os.getenv("ETCP_SHOW_ROI_OVERLAY", "1").strip().lower() in ("1", "true", "yes", "on")
USE_GSTREAMER = os.getenv("ETCP_USE_GSTREAMER", "0").strip().lower() in ("1", "true", "yes", "on")
GSTREAMER_STRICT = os.getenv("ETCP_GSTREAMER_STRICT", "0").strip().lower() in ("1", "true", "yes", "on")
GSTREAMER_LATENCY_MS = max(0, min(1000, int(os.getenv("ETCP_GSTREAMER_LATENCY_MS", "0"))))
GSTREAMER_CODEC = os.getenv("ETCP_GSTREAMER_CODEC", "h264").strip().lower()
if GSTREAMER_CODEC not in ("h264", "h265"):
    GSTREAMER_CODEC = "h264"
GSTREAMER_DECODER = os.getenv("ETCP_GSTREAMER_DECODER", "").strip()
MIN_LOG_TRACK_POINTS = max(1, int(os.getenv("ETCP_MIN_LOG_TRACK_POINTS", "3")))
MIN_LOG_MOVEMENT_METERS = max(0.0, float(os.getenv("ETCP_MIN_LOG_MOVEMENT_METERS", "0.0")))


def _opencv_has_gstreamer():
    try:
        return "GStreamer:                   YES" in cv2.getBuildInformation()
    except Exception:
        return False


def _build_gstreamer_rtsp_pipeline(src):
    # Works only when OpenCV was built with GStreamer support.
    # Most pip opencv-python Windows builds do not include it, so FFmpeg remains the default.
    escaped_src = str(src).replace("\\", "\\\\").replace('"', '\\"')
    width, height = PREVIEW_SIZE
    protocols = "tcp" if RTSP_TRANSPORT == "tcp" else "udp"
    if GSTREAMER_CODEC == "h265":
        depay = "rtph265depay ! h265parse"
        decoder = GSTREAMER_DECODER or "avdec_h265"
    else:
        depay = "rtph264depay ! h264parse"
        decoder = GSTREAMER_DECODER or "avdec_h264"

    return (
        f'rtspsrc location="{escaped_src}" protocols={protocols} latency={GSTREAMER_LATENCY_MS} '
        "drop-on-latency=true do-retransmission=false ! "
        f"{depay} ! {decoder} ! "
        "videoconvert ! videoscale ! "
        f"video/x-raw,width={width},height={height},format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    )


def _print_gstreamer_help_once():
    if getattr(_print_gstreamer_help_once, "_printed", False):
        return
    _print_gstreamer_help_once._printed = True
    print(
        "[GSTREAMER] OpenCV in this Python environment was not built with GStreamer.\n"
        "Install GStreamer runtime/development files and use an OpenCV build with GStreamer enabled, "
        "then run with ETCP_USE_GSTREAMER=1 and ETCP_GSTREAMER_STRICT=1."
    )


def _predict_vehicles(frame):
    with vehicle_model_lock:
        if torch is not None:
            with torch.inference_mode():
                return vehicle_model.predict(frame, verbose=False)[0]
        return vehicle_model.predict(frame, verbose=False)[0]


def _draw_roi_overlay(frame, camera_id):
    if not SHOW_ROI_OVERLAY or camera_id is None:
        return frame

    try:
        preview = frame.copy()
        capture_zone = get_capture_zone(camera_id)
        if capture_zone is not None:
            zone = capture_zone.astype(np.float32).copy()
            sx = preview.shape[1] / float(PREVIEW_SIZE[0])
            sy = preview.shape[0] / float(PREVIEW_SIZE[1])
            zone[:, 0] *= sx
            zone[:, 1] *= sy
            cv2.polylines(preview, [zone.astype(np.int32)], True, (0, 0, 255), 3)
        return preview
    except Exception:
        return frame


def _mark_logs_dirty():
    global logs_dirty
    with logs_dirty_lock:
        logs_dirty = True


def _publish_frame(camera_id, frame, frame_time=None, force=False):
    frame_time = frame_time or time.time()
    with frame_locks[camera_id]:
        if not force and frame_time < latest_frame_times[camera_id]:
            return False

    ret, buffer = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY],
    )
    with stats_lock:
        camera_stats[camera_id]["published_frames"] += 1
    with frame_locks[camera_id]:
        if not force and frame_time < latest_frame_times[camera_id]:
            return False
        latest_frame_times[camera_id] = frame_time
        latest_frames[camera_id] = frame
        if ret:
            latest_encoded_frames[camera_id] = buffer.tobytes()
    return True


def _enqueue_db_write(cache_key, row, camera_name, force=False):
    """
    Queue DB write instead of writing in detection thread.
    DB write is slow; doing it inline causes browser/dashboard lag.
    """
    now = time.time()
    current_license = row.get("License", "Unknown")
    current_images = (row.get("license_img", ""), row.get("veh_img", ""))

    current_license_norm = normalize_plate_text(current_license)
    if not force:
        if not current_license_norm and not row.get("license_img") and not row.get("veh_img"):
            return
        if (
            (now - last_db_write_time[cache_key]) < DB_MIN_INTERVAL_SEC
            and last_db_license.get(cache_key) == current_license
            and last_db_images.get(cache_key) == current_images
        ):
            return

    last_db_write_time[cache_key] = now
    last_db_license[cache_key] = current_license
    last_db_images[cache_key] = current_images

    payload = {
        "track_id": row.get("Track ID", 0),
        "class_name": row.get("Class Name", "Unknown"),
        "avg_speed": row.get("Avg Speed", "0 km/h"),
        "license_text": current_license if current_license else "Unknown",
        "time_value": row.get("Time", time.strftime("%Y-%m-%d %H:%M:%S")),
        "class_id": row.get("Class ID", 1),
        "camera_name": camera_name,
        "source_type": "stream",
        "license_img": row.get("license_img", ""),
        "veh_img": row.get("veh_img", ""),
    }

    try:
        db_queue.put_nowait(payload)
    except Exception:
        # If queue is full, drop non-critical DB write; next cycle will update.
        pass


def _db_worker():
    while True:
        try:
            payload = db_queue.get(timeout=1)
        except Empty:
            continue

        try:
            upsert_vehicle_log(**payload)
        except Exception as e:
            print("[DB WORKER ERROR] =>", e)
        finally:
            db_queue.task_done()


def _logs_flush_worker():
    global logs_dirty

    while True:
        time.sleep(LOG_FLUSH_INTERVAL_SEC)

        should_flush = False
        with logs_dirty_lock:
            if logs_dirty:
                logs_dirty = False
                should_flush = True

        if not should_flush:
            continue

        try:
            with log_lock:
                save_logs_dict(logs_dict)
        except Exception as e:
            print("[LOG FLUSH ERROR] =>", e)


def _enqueue_ocr_task(
    camera_id,
    track_id,
    cls_id,
    class_name,
    vehicle_crop,
    cache_key,
    camera_name,
    avg_speed,
):
    """
    Queue OCR instead of running Paddle/EasyOCR in the RTSP detection loop.
    """
    if vehicle_crop is None or vehicle_crop.size == 0:
        return

    now = time.time()
    if (now - last_ocr_request_time[cache_key]) < OCR_MIN_INTERVAL_SEC:
        return
    last_ocr_request_time[cache_key] = now

    with ocr_inflight_lock:
        if cache_key in ocr_inflight:
            return
        ocr_inflight.add(cache_key)

    task = {
        "camera_id": camera_id,
        "track_id": track_id,
        "cls_id": cls_id,
        "class_name": class_name,
        "vehicle_crop": vehicle_crop.copy(),
        "cache_key": cache_key,
        "camera_name": camera_name,
        "avg_speed": avg_speed,
        "time_value": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        ocr_queue.put_nowait(task)
    except Exception:
        with ocr_inflight_lock:
            ocr_inflight.discard(cache_key)


def _ocr_worker():
    while True:
        try:
            task = ocr_queue.get(timeout=1)
        except Empty:
            continue

        cache_key = task["cache_key"]

        try:
            vehicle_crop = task["vehicle_crop"]
            cls_id = task["cls_id"]
            camera_id = task["camera_id"]
            track_id = task["track_id"]
            camera_name = task["camera_name"]

            plate_boxes = detect_license_plate(vehicle_crop)
            plate_texts, best_plate_crop = ocr_it(vehicle_crop, plate_boxes, cls_id)

            license_img_path = ""
            veh_img_path = ""

            if plate_texts:
                license_text_cache.setdefault(cache_key, [])
                license_text_cache[cache_key].extend(plate_texts)

            best_license = finalize_license(license_text_cache.get(cache_key, []), cls_id)

            rule_cls_id, rule_class_name = class_from_license_rule(best_license)
            if rule_cls_id is not None:
                cls_id = rule_cls_id
                class_name = rule_class_name
            else:
                class_name = task["class_name"]

            has_plate_crop = best_plate_crop is not None and getattr(best_plate_crop, "size", 0) > 0
            if has_plate_crop:
                license_img_path, veh_img_path = save_detection_images(
                    track_id=track_id,
                    vehicle_img=vehicle_crop,
                    plate_img=best_plate_crop,
                    prefix=f"cam{camera_id}_",
                )

            with log_lock:
                existing = logs_dict["streamLogs"].get(cache_key, {})
                existing_has_plate_image = bool(existing.get("license_img"))
                if rule_cls_id is not None:
                    existing["Class Name"] = class_name
                    existing["Class ID"] = cls_id
                if best_license and best_license != "Unknown":
                    existing["License"] = best_license
                if license_img_path and veh_img_path:
                    existing["license_img"] = license_img_path
                    existing["veh_img"] = veh_img_path
                elif veh_img_path and not existing_has_plate_image:
                    existing["veh_img"] = veh_img_path
                if existing:
                    logs_dict["streamLogs"][cache_key] = existing
                    _mark_logs_dirty()

            row = {
                "Track ID": track_id,
                "Class Name": class_name,
                "Avg Speed": task.get("avg_speed", "0 km/h"),
                "License": best_license if best_license else "Unknown",
                "Time": task["time_value"],
                "Class ID": cls_id,
                "camera_name": camera_name,
                "license_img": license_img_path,
                "veh_img": veh_img_path,
            }

            _enqueue_db_write(cache_key, row, camera_name, force=True)

        except Exception as e:
            print("[OCR WORKER ERROR] =>", e)

        finally:
            with ocr_inflight_lock:
                ocr_inflight.discard(cache_key)
            ocr_queue.task_done()


def _start_background_workers():
    global workers_started

    with workers_lock:
        if workers_started:
            return

        threading.Thread(target=_ocr_worker, daemon=True, name="OCR-Worker-1").start()
        threading.Thread(target=_ocr_worker, daemon=True, name="OCR-Worker-2").start()
        threading.Thread(target=_db_worker, daemon=True, name="DB-Worker").start()
        threading.Thread(target=_logs_flush_worker, daemon=True, name="Log-Flush-Worker").start()

        workers_started = True
        print("[INFO] OCR, DB and log flush background workers started")


def register_rtsp_urls(urls):
    """Store RTSP URLs without starting all camera threads immediately."""
    for i in range(1, min(MAX_CAMERAS, len(urls)) + 1):
        url = urls[i - 1].strip() if i - 1 < len(urls) and urls[i - 1] else ""
        if url:
            camera_urls[i] = url


def start_rtsp_camera(camera_id, url=None):
    """Start a single camera thread on-demand."""
    if camera_id not in CAMERA_NAME_MAP:
        return

    old_url = camera_urls.get(camera_id, "")
    if url:
        camera_urls[camera_id] = url.strip()

    camera_url = camera_urls.get(camera_id, "")
    if not camera_url:
        return

    ensure_database()
    ensure_table()
    _start_background_workers()

    if camera_running.get(camera_id):
        latest_age = time.time() - latest_frame_times.get(camera_id, 0.0)
        if url and old_url and old_url != camera_url:
            print(f"[THREAD] Camera {camera_id} URL changed; restarting RTSP thread")
        elif latest_age <= 15:
            return
        else:
            print(f"[THREAD] Camera {camera_id} feed stale ({latest_age:.1f}s); restarting RTSP thread")

        camera_running[camera_id] = False
        old_thread = camera_threads.get(camera_id)
        if old_thread and old_thread.is_alive():
            old_thread.join(timeout=1.5)

    thread = threading.Thread(
        target=process_camera,
        args=(camera_id, camera_url),
        daemon=True,
        name=f"YOLO-Detect-Cam-{camera_id}"
    )
    camera_threads[camera_id] = thread
    thread.start()
    print(f"[THREAD] Camera {camera_id} YOLO/detection thread started")


class RTSPCamera:
    """
    One RTSP capture thread per camera.

    This class continuously reads RTSP frames in the background and stores only
    the latest frame. The detection loop reads this latest frame and never waits
    on cv2.VideoCapture.read(), so YOLO cannot freeze RTSP frame decoding.
    """
    def __init__(self, src, camera_id=None):
        self.src = src
        self.camera_id = camera_id
        self.cap = None
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_time = 0.0
        self.running = True
        self.last_connect_attempt = 0.0
        self.last_raw_publish_time = 0.0
        self.capture_backend = "ffmpeg"

        self.thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name=f"RTSP-Capture-Cam-{camera_id}"
        )
        self.thread.start()
        print(f"[THREAD] Camera {camera_id} RTSP capture thread started")

    def _open(self):
        now = time.time()
        if now - self.last_connect_attempt < 5:
            return False

        self.last_connect_attempt = now

        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass

        self.capture_backend = "none"
        if USE_GSTREAMER and _opencv_has_gstreamer():
            gst_pipeline = _build_gstreamer_rtsp_pipeline(self.src)
            print(f"[GSTREAMER PIPELINE CAM {self.camera_id}] {gst_pipeline}")
            self.cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
            if self.cap.isOpened():
                self.capture_backend = "gstreamer"
            else:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
                print(f"[GSTREAMER FAILED CAM {self.camera_id}] pipeline could not open")
        elif USE_GSTREAMER:
            _print_gstreamer_help_once()
            print(f"[GSTREAMER UNAVAILABLE CAM {self.camera_id}] OpenCV has no GStreamer support")

        if self.cap is None and USE_GSTREAMER and GSTREAMER_STRICT:
            print(f"[RTSP FAILED CAM {self.camera_id}] strict GStreamer enabled; FFmpeg fallback disabled")
            return False

        if self.cap is None:
            self.capture_backend = "ffmpeg"
            self.cap = cv2.VideoCapture(self.src, cv2.CAP_FFMPEG)

        if self.cap.isOpened():
            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self.cap.set(cv2.CAP_PROP_FPS, 10)
            except Exception:
                pass
            print(f"[RTSP CONNECTED CAM {self.camera_id}] backend={self.capture_backend} {self.src}")
            return True

        print(f"[RTSP FAILED CAM {self.camera_id}] {self.src}")
        return False

    def _capture_loop(self):
        while self.running:
            try:
                if self.cap is None or not self.cap.isOpened():
                    self._open()
                    time.sleep(0.25)
                    continue

                # Drop old buffered frames, keep only the newest decodable frame.
                try:
                    for _ in range(RTSP_GRAB_DROPS):
                        self.cap.grab()
                except Exception:
                    pass

                ret, frame = self.cap.read()

                if not ret or frame is None:
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    self.cap = None
                    time.sleep(0.5)
                    continue

                with stats_lock:
                    camera_stats[self.camera_id]["capture_frames"] += 1

                capture_time = time.time()
                with self.lock:
                    self.latest_frame = frame
                    self.latest_time = capture_time

                # Keep browser preview fresh without JPEG-encoding every decoded frame.
                # Detection thread overwrites this with annotated frames when ready.
                now = capture_time
                if self.camera_id is not None and now - self.last_raw_publish_time >= RAW_PUBLISH_INTERVAL_SEC:
                    self.last_raw_publish_time = now
                    preview_frame = cv2.resize(frame, STREAM_SIZE)
                    preview_frame = _draw_roi_overlay(preview_frame, self.camera_id)
                    _publish_frame(self.camera_id, preview_frame, frame_time=capture_time)

                time.sleep(0.001)

            except Exception as e:
                print(f"[RTSP CAPTURE ERROR CAM {self.camera_id}] =>", e)
                try:
                    if self.cap:
                        self.cap.release()
                except Exception:
                    pass
                self.cap = None
                time.sleep(1.0)

    def read(self):
        with self.lock:
            if self.latest_frame is None:
                return False, None, 0.0

            # If no fresh frame for 10 seconds, consider disconnected.
            if time.time() - self.latest_time > 10:
                return False, None, 0.0

            return True, self.latest_frame.copy(), self.latest_time

    def release(self):
        self.running = False
        try:
            if self.cap:
                self.cap.release()
        except Exception:
            pass


def process_camera(camera_id, rtsp_url):
    camera_running[camera_id] = True
    camera_name = CAMERA_NAME_MAP.get(camera_id, f"Camera {camera_id}")
    camera = RTSPCamera(rtsp_url, camera_id=camera_id)
    print(f"[THREAD] Camera {camera_id} YOLO/detection thread running")

    tracker = sv.ByteTrack(frame_rate=10)
    box_annotator = sv.BoxAnnotator(thickness=2)
    label_annotator = sv.LabelAnnotator(text_scale=0.5, text_thickness=1)

    source_polygon = get_camera_polygon(camera_id)
    capture_zone = get_capture_zone(camera_id)
    target_polygon = get_target_polygon(camera_id=camera_id)
    transformer = ViewTransformer(source_polygon, target_polygon)

    coordinates = defaultdict(lambda: deque(maxlen=20))
    fps = 10
    frame_count = 0
    last_stats_print = time.time()
    last_seen_frame_time = 0.0

    while camera_running[camera_id]:
        ret, frame, frame_time = camera.read()
        if not ret or frame is None:
            with stats_lock:
                camera_stats[camera_id]["skipped_frames"] += 1

            with frame_locks[camera_id]:
                has_frame = latest_frames.get(camera_id) is not None

            if not has_frame:
                blank = np.zeros((360, 640, 3), dtype=np.uint8)
                cv2.putText(
                    blank,
                    f"{camera_name} not connected",
                    (90, 180),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (255, 255, 255),
                    2
                )
                _publish_frame(camera_id, blank, force=True)

            time.sleep(0.5)
            continue

        if frame_time <= last_seen_frame_time:
            time.sleep(0.01)
            continue

        last_seen_frame_time = frame_time
        source_original = frame.copy()
        frame = cv2.resize(source_original, PREVIEW_SIZE)
        original = frame.copy()
        crop_scale_x = source_original.shape[1] / float(PREVIEW_SIZE[0])
        crop_scale_y = source_original.shape[0] / float(PREVIEW_SIZE[1])
        frame_count += 1

        if time.time() - last_stats_print > 15:
            with stats_lock:
                stats = camera_stats[camera_id].copy()
            print(
                f"[STATS] Cam {camera_id} capture={stats['capture_frames']} detect_frames={stats['detect_frames']} "
                f"skipped={stats['skipped_frames']} detections={stats['detections']} published={stats['published_frames']}"
            )
            last_stats_print = time.time()

        # keep preview responsive
        if frame_count % PROCESS_EVERY_N_FRAMES != 0:
            with stats_lock:
                camera_stats[camera_id]["skipped_frames"] += 1
            continue

        try:
            with stats_lock:
                camera_stats[camera_id]["detect_frames"] += 1

            results = _predict_vehicles(frame)
            detections = sv.Detections.from_ultralytics(results)

            if len(detections) > 0:
                detections = detections[detections.confidence > CONFIDENCE_THRESHOLD]
                detections = detections[np.isin(detections.class_id, [0, 1])]
                detections = detections.with_nms(threshold=IOU_THRESHOLD)

                if len(detections) > 0:
                    roi_mask = []
                    for x1, y1, x2, y2 in detections.xyxy:
                        center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                        bottom_center = (int((x1 + x2) / 2), int(y2))
                        roi_mask.append(
                            point_in_polygon(center, capture_zone)
                            or point_in_polygon(bottom_center, capture_zone)
                            or point_in_polygon(center, source_polygon)
                            or point_in_polygon(bottom_center, source_polygon)
                        )
                    detections = detections[np.array(roi_mask, dtype=bool)]

                if len(detections) > 0:
                    detections = tracker.update_with_detections(detections)
                    if len(detections) > 0:
                        bottom_points = detections.get_anchors_coordinates(anchor=sv.Position.BOTTOM_CENTER)
                        source_mask = np.array(
                            [point_in_polygon((int(pt[0]), int(pt[1])), source_polygon) for pt in bottom_points],
                            dtype=bool,
                        )
                        detections = detections[source_mask]
                else:
                    detections = sv.Detections.empty()
            else:
                detections = sv.Detections.empty()

            if len(detections) > 0:
                with stats_lock:
                    camera_stats[camera_id]["detections"] += len(detections)

            labels = []
            if detections.tracker_id is not None and len(detections.tracker_id) > 0:
                anchor_points = detections.get_anchors_coordinates(anchor=sv.Position.BOTTOM_CENTER)
                transformed_points = transformer.transform_points(anchor_points).astype(int)

                for i in range(len(detections.tracker_id)):
                    track_id = int(detections.tracker_id[i])
                    cls_id = int(detections.class_id[i])
                    class_name = CLASS_NAMES.get(cls_id, "Unknown")

                    x1, y1, x2, y2 = map(int, detections.xyxy[i])
                    x1 = max(0, x1)
                    y1 = max(0, y1)
                    x2 = min(frame.shape[1], x2)
                    y2 = min(frame.shape[0], y2)

                    center_point = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                    bottom_center = (int((x1 + x2) / 2), int(y2))

                    if not point_in_polygon(bottom_center, source_polygon):
                        labels.append(f"{track_id} {class_name}")
                        continue

                    pad = 30
                    x1p = max(0, x1 - pad)
                    y1p = max(0, y1 - pad)
                    x2p = min(frame.shape[1], x2 + pad)
                    y2p = min(frame.shape[0], y2 + pad)
                    sx1p = max(0, int(round(x1p * crop_scale_x)))
                    sy1p = max(0, int(round(y1p * crop_scale_y)))
                    sx2p = min(source_original.shape[1], int(round(x2p * crop_scale_x)))
                    sy2p = min(source_original.shape[0], int(round(y2p * crop_scale_y)))
                    vehicle_crop = source_original[sy1p:sy2p, sx1p:sx2p]

                    cache_key = f"{camera_id}_{track_id}"
                    license_text_cache.setdefault(cache_key, [])

                    existing = logs_dict["streamLogs"].get(cache_key, {})
                    existing_license = existing.get("License", "Unknown")
                    existing_license_img = existing.get("license_img", "")
                    existing_veh_img = existing.get("veh_img", "")
                    has_known_license = existing_license and existing_license != "Unknown"

                    plate_texts = []
                    best_plate_crop = None
                    license_img_path = existing_license_img
                    veh_img_path = existing_veh_img

                    if (
                        not veh_img_path
                        and not existing_license_img
                        and not has_known_license
                        and vehicle_crop is not None
                        and vehicle_crop.size > 0
                        and point_in_polygon(center_point, capture_zone)
                        and (x2 - x1) >= 60
                        and (y2 - y1) >= 40
                    ):
                        _, veh_img_path = save_detection_images(
                            track_id=track_id,
                            vehicle_img=vehicle_crop,
                            plate_img=None,
                            prefix=f"cam{camera_id}_",
                        )

                    # OCR is queued in background to prevent RTSP/browser freeze.
                    avg_speed_text_for_ocr = "0 km/h"
                    should_run_ocr = (
                        vehicle_crop is not None
                        and vehicle_crop.size > 0
                        and point_in_polygon(center_point, capture_zone)
                        and (x2 - x1) >= 60
                        and (y2 - y1) >= 40
                        and (not has_known_license)
                        and len(coordinates[cache_key]) >= 2
                        and (frame_count % max(1, PROCESS_EVERY_N_FRAMES) == 0)
                    )

                    if should_run_ocr:
                        _enqueue_ocr_task(
                            camera_id=camera_id,
                            track_id=track_id,
                            cls_id=cls_id,
                            class_name=class_name,
                            vehicle_crop=vehicle_crop,
                            cache_key=cache_key,
                            camera_name=camera_name,
                            avg_speed=avg_speed_text_for_ocr,
                        )

                    if plate_texts:
                        license_text_cache[cache_key].extend(plate_texts)

                    x_trans, y_trans = transformed_points[i]
                    coordinates[cache_key].append((float(x_trans), float(y_trans)))

                    speed_kmh = None
                    movement_distance = 0.0
                    if len(coordinates[cache_key]) >= 3:
                        first_x, first_y = coordinates[cache_key][0]
                        last_x, last_y = coordinates[cache_key][-1]
                        movement_distance = math.hypot(last_x - first_x, last_y - first_y)
                        time_elapsed = len(coordinates[cache_key]) / fps
                        if time_elapsed > 0:
                            speed_kmh = (movement_distance / time_elapsed) * 3.6

                    if speed_kmh is None or speed_kmh < 1.0:
                        speed_kmh = 0.0
                    
                    speed_text = f"{round(speed_kmh, 2)} km/h"

                    best_license = finalize_license(license_text_cache.get(cache_key, []), cls_id)
                    has_valid_license = is_valid_license_text(best_license)

                    # preserve old good license if current finalize gives Unknown
                    if (not has_valid_license) and has_known_license:
                        best_license = existing_license
                        has_valid_license = is_valid_license_text(best_license)

                    rule_cls_id, rule_class_name = class_from_license_rule(best_license)
                    if rule_cls_id is not None:
                        cls_id = rule_cls_id
                        class_name = rule_class_name

                    now_time = time.strftime("%Y-%m-%d %H:%M:%S")

                    has_enough_track = len(coordinates[cache_key]) >= MIN_LOG_TRACK_POINTS
                    has_real_movement = movement_distance >= MIN_LOG_MOVEMENT_METERS
                    has_good_vehicle_crop = (
                        vehicle_crop is not None
                        and vehicle_crop.size > 0
                        and point_in_polygon(center_point, capture_zone)
                        and (x2 - x1) >= 60
                        and (y2 - y1) >= 40
                    )
                    should_log_detection = has_valid_license or (has_good_vehicle_crop and has_enough_track and has_real_movement)

                    row = {
                        "Track ID": track_id,
                        "Class Name": class_name,
                        "Avg Speed": speed_text,
                        "License": best_license if best_license else "Unknown",
                        "Time": now_time,
                        "Class ID": cls_id,
                        "camera_name": camera_name,
                        "license_img": license_img_path,
                        "veh_img": veh_img_path,
                    }

                    logs_dict["streamLogs"][cache_key] = row
                    _mark_logs_dirty()

                    if should_log_detection:
                        _enqueue_db_write(cache_key, row, camera_name)

                    labels.append(
                        f"{track_id} {class_name} {speed_text} {best_license if best_license else 'Unknown'}"
                    )

            if not PUBLISH_DETECTION_OVERLAY:
                continue
            if len(detections) <= 0:
                continue

            annotated = cv2.resize(source_original, STREAM_SIZE)
            annotated = _draw_roi_overlay(annotated, camera_id)

            if len(labels) != len(detections):
                labels = [
                    CLASS_NAMES.get(int(cls_id), "Vehicle")
                    for cls_id in detections.class_id
                ]
            box_scale_x = STREAM_SIZE[0] / float(PREVIEW_SIZE[0])
            box_scale_y = STREAM_SIZE[1] / float(PREVIEW_SIZE[1])
            for det_idx, box in enumerate(detections.xyxy):
                x1, y1, x2, y2 = box
                p1 = (int(round(x1 * box_scale_x)), int(round(y1 * box_scale_y)))
                p2 = (int(round(x2 * box_scale_x)), int(round(y2 * box_scale_y)))
                cv2.rectangle(annotated, p1, p2, (0, 255, 0), 2)
                label = labels[det_idx] if det_idx < len(labels) else "Vehicle"
                text_y = max(24, p1[1] - 8)
                cv2.putText(
                    annotated,
                    label,
                    (p1[0], text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 0),
                    2,
                )

            cv2.putText(
                annotated,
                camera_name,
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2
            )

            _publish_frame(camera_id, annotated.copy(), frame_time=frame_time)

        except Exception as e:
            print(f"Camera {camera_id} pipeline error:", e)
            if PUBLISH_DETECTION_OVERLAY:
                fallback = original.copy()
                cv2.polylines(fallback, [source_polygon.astype(np.int32)], True, (0, 255, 0), 2)
                cv2.polylines(fallback, [capture_zone.astype(np.int32)], True, (0, 0, 255), 2)
                _publish_frame(camera_id, fallback, frame_time=frame_time)

        time.sleep(0.001)

    camera.release()
    camera_running[camera_id] = False
    print(f"[THREAD] Camera {camera_id} YOLO/detection thread stopped")


def start_rtsp_streams(urls):
    """Register RTSP URLs so individual cameras can start on demand."""
    register_rtsp_urls(urls)


def generate_frames(camera_id):
    """
    Browser MJPEG stream. This only reads latest_frames and never runs YOLO/OCR/DB.
    Therefore the browser feed stays responsive while detection works in other threads.
    """
    blank = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(
        blank,
        f"Waiting for Camera {camera_id}...",
        (120, 180),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2
    )

    last_sent = blank

    while True:
        try:
            with frame_locks[camera_id]:
                frame = latest_frames.get(camera_id)

            if frame is None:
                frame = last_sent
            else:
                last_sent = frame

            with frame_locks[camera_id]:
                jpg = latest_encoded_frames.get(camera_id)

            if not jpg:
                time.sleep(0.02)
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                jpg +
                b"\r\n"
            )

            time.sleep(0.02)

        except GeneratorExit:
            break

        except Exception as e:
            print(f"[STREAM GEN ERROR CAM {camera_id}] =>", e)
            time.sleep(0.5)


def get_latest_frame_jpeg(camera_id):
    """Return the latest encoded frame for short-lived browser snapshot requests."""
    with frame_locks[camera_id]:
        jpg = latest_encoded_frames.get(camera_id)

    if jpg:
        return jpg

    blank = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(
        blank,
        f"Waiting for Camera {camera_id}...",
        (120, 180),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2
    )
    ret, buffer = cv2.imencode(
        ".jpg",
        blank,
        [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY],
    )
    return buffer.tobytes() if ret else b""


def get_stream_logs_by_camera():
    """Return RAM stream logs for all configured cameras.
    Older code returned only 4 cameras, which made camera IDs/names look mixed.
    """
    result = {f"camera_{i}": [] for i in range(1, MAX_CAMERAS + 1)}

    for key, row in logs_dict.get("streamLogs", {}).items():
        try:
            camera_id = int(str(key).split("_")[0])
        except Exception:
            continue

        camera_key = f"camera_{camera_id}"
        if camera_key not in result:
            result[camera_key] = []
        result[camera_key].append(row)

    for camera_key in result:
        result[camera_key].sort(key=lambda x: str(x.get("Time", "")), reverse=True)

    return result


def save_stream_logs_to_database():
    count = 0

    for key, row in logs_dict.get("streamLogs", {}).items():
        try:
            camera_id = int(str(key).split("_")[0])
            camera_name = CAMERA_NAME_MAP.get(camera_id, row.get("camera_name", f"Camera {camera_id}"))

            upsert_vehicle_log(
                track_id=row.get("Track ID", 0),
                class_name=row.get("Class Name", "Unknown"),
                avg_speed=row.get("Avg Speed", "0 km/h"),
                license_text=row.get("License", "Unknown"),
                time_value=row.get("Time", time.strftime("%Y-%m-%d %H:%M:%S")),
                class_id=row.get("Class ID", 1),
                camera_name=camera_name,
                source_type="stream",
                license_img=row.get("license_img", ""),
                veh_img=row.get("veh_img", ""),
            )
            count += 1

        except Exception as e:
            print("save_stream_logs_to_database error:", e)

    return count
