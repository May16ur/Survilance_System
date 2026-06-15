import asyncio
import fractions
import os
import threading
import time

from preview_pipeline import STREAM_FPS, get_preview_frame_with_time, get_preview_url

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
    from aiortc.contrib.media import MediaPlayer
    from av import VideoFrame
    WEBRTC_IMPORT_ERROR = None
except Exception as e:
    RTCPeerConnection = RTCSessionDescription = VideoStreamTrack = MediaPlayer = VideoFrame = None
    WEBRTC_IMPORT_ERROR = e


_pcs = set()
_pcs_lock = threading.Lock()
_loop = None
_loop_thread = None
_loop_lock = threading.Lock()
WEBRTC_MODE = os.getenv("ETCP_WEBRTC_MODE", "direct").strip().lower()
WEBRTC_RTSP_TRANSPORT = os.getenv("ETCP_WEBRTC_RTSP_TRANSPORT", "udp").strip().lower()
WEBRTC_RTSP_OPTIONS = {
    "rtsp_transport": WEBRTC_RTSP_TRANSPORT,
    "fflags": "nobuffer",
    "flags": "low_delay",
    "max_delay": "0",
    "stimeout": "3000000",
    "rw_timeout": "3000000",
}


def _ensure_loop():
    global _loop, _loop_thread
    with _loop_lock:
        if _loop and _loop.is_running():
            return _loop

        _loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(_loop)
            _loop.run_forever()

        _loop_thread = threading.Thread(target=_run, daemon=True, name="WebRTC-Loop")
        _loop_thread.start()
        return _loop


class PreviewVideoTrack(VideoStreamTrack if VideoStreamTrack is not None else object):
    def __init__(self, camera_id):
        if VideoStreamTrack is None:
            raise RuntimeError(f"WebRTC unavailable: {WEBRTC_IMPORT_ERROR}")
        super().__init__()
        self.camera_id = camera_id
        self.frame_no = 0
        self.started_at = time.time()
        self.last_frame_time = 0.0
        self.time_base = fractions.Fraction(1, 90000)

    async def recv(self):
        deadline = time.time() + (1.0 / max(1, STREAM_FPS))
        frame, frame_time = get_preview_frame_with_time(self.camera_id)
        while frame_time and frame_time == self.last_frame_time and time.time() < deadline:
            await asyncio.sleep(0.01)
            frame, frame_time = get_preview_frame_with_time(self.camera_id)
        self.last_frame_time = frame_time
        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        elapsed = max(0.0, time.time() - self.started_at)
        video_frame.pts = int(elapsed * 90000)
        video_frame.time_base = self.time_base
        return video_frame


async def _create_answer(camera_id, offer_sdp, offer_type):
    pc = RTCPeerConnection()
    player = None
    media_track = None
    mode = "preview"
    with _pcs_lock:
        _pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close()
            try:
                if media_track is not None:
                    media_track.stop()
            except Exception:
                pass
            with _pcs_lock:
                _pcs.discard(pc)

    rtsp_url = get_preview_url(camera_id)
    if WEBRTC_MODE in ("direct", "rtsp") and rtsp_url:
        try:
            player = MediaPlayer(
                rtsp_url,
                format="rtsp",
                options=WEBRTC_RTSP_OPTIONS,
            )
            if player.video is not None:
                media_track = player.video
                pc.addTrack(media_track)
                mode = f"direct_rtsp_{WEBRTC_RTSP_TRANSPORT}"
            else:
                raise RuntimeError("RTSP URL has no video track")
        except Exception as e:
            print(f"[WEBRTC] Direct RTSP failed for camera {camera_id}; using preview frames: {e}")

    if media_track is None:
        media_track = PreviewVideoTrack(camera_id)
        pc.addTrack(media_track)
        mode = "preview_frame_cache"

    offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "mode": mode}


def create_webrtc_answer(camera_id, offer_sdp, offer_type="offer", timeout=10):
    if WEBRTC_IMPORT_ERROR is not None:
        raise RuntimeError(f"WebRTC unavailable: {WEBRTC_IMPORT_ERROR}")
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(
        _create_answer(camera_id, offer_sdp, offer_type),
        loop,
    )
    return future.result(timeout=timeout)
