import os
import time

from flask import jsonify

try:
    from rtsp_pipeline import (
        start_rtsp_streams,
        start_rtsp_camera,
        generate_frames,
        get_latest_frame_jpeg,
        get_stream_logs_by_camera,
        save_stream_logs_to_database,
    )
    RTSP_PIPELINE_ERROR = None
except Exception as e:
    RTSP_PIPELINE_ERROR = e
    start_rtsp_streams = start_rtsp_camera = generate_frames = get_latest_frame_jpeg = None
    get_stream_logs_by_camera = save_stream_logs_to_database = None

try:
    from video_pipeline import start_uploaded_video, generate_uploaded_video_frames, get_upload_logs
    VIDEO_PIPELINE_ERROR = None
except Exception as e:
    VIDEO_PIPELINE_ERROR = e
    start_uploaded_video = generate_uploaded_video_frames = get_upload_logs = None

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
RECEIVED_FOLDER = os.path.join(BASE_DIR, "received")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RECEIVED_FOLDER, exist_ok=True)

# Small route cache to stop many browser tabs / hover popups from hammering MySQL.
_API_CACHE = {}


def cache_get(key, ttl_sec):
    item = _API_CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if time.time() - ts > ttl_sec:
        _API_CACHE.pop(key, None)
        return None
    return value


def cache_set(key, value):
    _API_CACHE[key] = (time.time(), value)
    if len(_API_CACHE) > 200:
        for old_key in list(_API_CACHE.keys())[:50]:
            _API_CACHE.pop(old_key, None)
    return value


def clear_api_cache():
    _API_CACHE.clear()


def pipeline_unavailable_response(name, error):
    return jsonify({
        "success": False,
        "message": f"{name} pipeline unavailable. CP Plus ANPR receiver still works.",
        "error": str(error),
    }), 503
