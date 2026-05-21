import os
import time
import threading

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;3000000|rw_timeout;3000000"

import cv2
import numpy as np


MAX_CAMERAS = 14
STREAM_SIZE = (
    max(640, min(1280, int(os.getenv("PREVIEW_STREAM_WIDTH", "960")))),
    max(360, min(720, int(os.getenv("PREVIEW_STREAM_HEIGHT", "540")))),
)
STREAM_JPEG_QUALITY = max(35, min(95, int(os.getenv("PREVIEW_STREAM_JPEG_QUALITY", "80"))))
STREAM_FPS = max(3, min(20, int(os.getenv("PREVIEW_STREAM_FPS", "10"))))
BUFFER_DROP_FRAMES = max(0, min(5, int(os.getenv("PREVIEW_BUFFER_DROP_FRAMES", "2"))))

camera_urls = {i: "" for i in range(1, MAX_CAMERAS + 1)}
camera_threads = {}
camera_running = {i: False for i in range(1, MAX_CAMERAS + 1)}
frame_locks = {i: threading.Lock() for i in range(1, MAX_CAMERAS + 1)}
latest_jpegs = {}
latest_times = {}


def register_preview_urls(urls):
    for i in range(1, min(MAX_CAMERAS, len(urls)) + 1):
        url = (urls[i - 1] or "").strip()
        if url:
            camera_urls[i] = url


def start_preview_camera(camera_id, url=None):
    if camera_id < 1 or camera_id > MAX_CAMERAS:
        raise ValueError("Invalid camera id")

    if url:
        camera_urls[camera_id] = url.strip()

    camera_url = camera_urls.get(camera_id, "")
    if not camera_url:
        raise ValueError("RTSP URL is required")

    if camera_running.get(camera_id):
        return

    camera_running[camera_id] = True
    thread = threading.Thread(
        target=_preview_loop,
        args=(camera_id, camera_url),
        daemon=True,
        name=f"Preview-Camera-{camera_id}",
    )
    camera_threads[camera_id] = thread
    thread.start()


def stop_preview_camera(camera_id):
    if camera_id in camera_running:
        camera_running[camera_id] = False


def _blank_frame(text):
    frame = np.zeros((STREAM_SIZE[1], STREAM_SIZE[0], 3), dtype=np.uint8)
    cv2.putText(frame, text, (40, STREAM_SIZE[1] // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (235, 235, 235), 2)
    return frame


def _publish(camera_id, frame):
    if frame is None:
        return
    if frame.shape[1] != STREAM_SIZE[0] or frame.shape[0] != STREAM_SIZE[1]:
        frame = cv2.resize(frame, STREAM_SIZE)
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY])
    if not ok:
        return
    with frame_locks[camera_id]:
        latest_jpegs[camera_id] = buffer.tobytes()
        latest_times[camera_id] = time.time()


def _preview_loop(camera_id, rtsp_url):
    cap = None
    last_connect = 0
    frame_interval = 1.0 / STREAM_FPS

    while camera_running.get(camera_id):
        try:
            now = time.time()
            if cap is None or not cap.isOpened():
                if now - last_connect < 3:
                    time.sleep(0.2)
                    continue
                last_connect = now
                if cap is not None:
                    cap.release()
                cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass
                if not cap.isOpened():
                    _publish(camera_id, _blank_frame(f"Camera {camera_id} not connected"))
                    time.sleep(1)
                    continue

            # Drop buffered frames so the web preview shows the newest camera frame.
            if BUFFER_DROP_FRAMES:
                ok = True
                for _ in range(BUFFER_DROP_FRAMES):
                    ok = cap.grab()
                    if not ok:
                        break
                frame = None
                if ok:
                    ok, frame = cap.retrieve()
            else:
                ok, frame = cap.read()

            if not ok or frame is None:
                _publish(camera_id, _blank_frame(f"Camera {camera_id} waiting for frame"))
                cap.release()
                cap = None
                time.sleep(0.5)
                continue

            _publish(camera_id, frame)
            time.sleep(frame_interval)

        except Exception as e:
            print(f"[PREVIEW CAM {camera_id}] {e}")
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass
            cap = None
            time.sleep(1)

    try:
        if cap is not None:
            cap.release()
    except Exception:
        pass
    camera_running[camera_id] = False


def get_preview_snapshot(camera_id):
    with frame_locks[camera_id]:
        jpg = latest_jpegs.get(camera_id)
    if jpg:
        return jpg

    frame = _blank_frame(f"Waiting for Camera {camera_id}...")
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY])
    return buffer.tobytes() if ok else b""


def generate_preview_frames(camera_id):
    while True:
        try:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + get_preview_snapshot(camera_id)
                + b"\r\n"
            )
            time.sleep(1.0 / STREAM_FPS)
        except GeneratorExit:
            break
        except Exception as e:
            print(f"[PREVIEW STREAM {camera_id}] {e}")
            time.sleep(0.5)
