import { useEffect, useRef, useState } from "react";
import { Camera } from "lucide-react";

export function WebRtcPreview({ camera, running }) {
  const videoRef = useRef(null);
  const peerRef = useRef(null);
  const [fallback, setFallback] = useState(false);
  const [fallbackTick, setFallbackTick] = useState(0);
  const [mode, setMode] = useState("WebRTC");

  useEffect(() => {
    setFallback(false);
    setMode("WebRTC");
    if (!camera || !running) return undefined;

    let cancelled = false;
    const pc = new RTCPeerConnection({
      iceServers: [],
    });
    peerRef.current = pc;

    pc.addTransceiver("video", { direction: "recvonly" });
    pc.ontrack = (event) => {
      if (videoRef.current && event.streams[0]) {
        videoRef.current.srcObject = event.streams[0];
      }
    };
    pc.onconnectionstatechange = () => {
      if (["failed", "disconnected", "closed"].includes(pc.connectionState) && !cancelled) {
        setFallback(true);
      }
    };

    async function connect() {
      try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        const response = await fetch(`/webrtc/offer/${camera.id}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(pc.localDescription),
        });
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        const answer = await response.json();
        if (!answer.success) throw new Error(answer.message || "WebRTC failed");
        if (answer.mode) {
          setMode(answer.mode === "preview_frame_cache" ? "WebRTC preview cache" : "Direct RTSP WebRTC");
        }
        await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type });
      } catch {
        if (!cancelled) setFallback(true);
      }
    }

    connect();

    return () => {
      cancelled = true;
      if (videoRef.current) videoRef.current.srcObject = null;
      peerRef.current = null;
      pc.close();
    };
  }, [camera?.id, running]);

  useEffect(() => {
    if (!fallback || !camera || !running) return undefined;
    const timer = setInterval(() => {
      setFallbackTick((value) => value + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [fallback, camera?.id, running]);

  if (!camera || !running) {
    return <div className="empty-preview"><Camera size={30} /> Feed stopped</div>;
  }

  if (fallback) {
    return (
      <>
        <img src={`/camera_snapshot/${camera.id}?t=${fallbackTick}`} alt={`${camera.name} preview`} />
        <span className="preview-mode">Snapshot fallback</span>
      </>
    );
  }

  return (
    <>
      <video
        ref={videoRef}
        className="webrtc-video"
        autoPlay
        muted
        playsInline
        aria-label={`${camera.name} WebRTC preview`}
      />
      <span className="preview-mode">{mode}</span>
    </>
  );
}
