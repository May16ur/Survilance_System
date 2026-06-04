import asyncio
import fractions
import threading
import time

from preview_pipeline import STREAM_FPS, get_preview_frame

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
    from av import VideoFrame
    WEBRTC_IMPORT_ERROR = None
except Exception as e:
    RTCPeerConnection = RTCSessionDescription = VideoStreamTrack = VideoFrame = None
    WEBRTC_IMPORT_ERROR = e


_pcs = set()
_pcs_lock = threading.Lock()
_loop = None
_loop_thread = None
_loop_lock = threading.Lock()


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


class PreviewVideoTrack(VideoStreamTrack):
    def __init__(self, camera_id):
        super().__init__()
        self.camera_id = camera_id
        self.frame_no = 0
        self.started_at = time.time()
        self.time_base = fractions.Fraction(1, 90000)
        self.frame_interval = max(1, int(90000 / max(1, STREAM_FPS)))

    async def recv(self):
        await asyncio.sleep(1.0 / max(1, STREAM_FPS))
        frame = get_preview_frame(self.camera_id)
        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        self.frame_no += 1
        video_frame.pts = self.frame_no * self.frame_interval
        video_frame.time_base = self.time_base
        return video_frame


async def _create_answer(camera_id, offer_sdp, offer_type):
    pc = RTCPeerConnection()
    with _pcs_lock:
        _pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close()
            with _pcs_lock:
                _pcs.discard(pc)

    pc.addTrack(PreviewVideoTrack(camera_id))
    offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}


def create_webrtc_answer(camera_id, offer_sdp, offer_type="offer", timeout=10):
    if WEBRTC_IMPORT_ERROR is not None:
        raise RuntimeError(f"WebRTC unavailable: {WEBRTC_IMPORT_ERROR}")
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(
        _create_answer(camera_id, offer_sdp, offer_type),
        loop,
    )
    return future.result(timeout=timeout)
