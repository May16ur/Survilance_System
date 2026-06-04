import { useEffect, useRef, useState } from "react";
import { Camera } from "lucide-react";

export function WebRtcPreview({ camera, running, previewTick }) {
  const videoRef = useRef(null);
  const peerRef = useRef(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    setFallback(false);
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

  if (!camera || !running) {
    return <div className="empty-preview"><Camera size={30} /> Feed stopped</div>;
  }

  if (fallback) {
    return <img src={`/camera_snapshot/${camera.id}?t=${previewTick}`} alt={`${camera.name} preview`} />;
  }

  return (
    <video
      ref={videoRef}
      className="webrtc-video"
      autoPlay
      muted
      playsInline
      aria-label={`${camera.name} WebRTC preview`}
    />
  );
}
