import { Camera, Database, Play, RefreshCw, Save, Square } from "lucide-react";

export function StreamsPanel({
  cameras,
  cameraStats,
  running,
  previewTick,
  registerAllStreams,
  saveLogs,
  updateCameraUrl,
  startCamera,
  stopCamera,
  openLogs,
}) {
  return (
    <section className="panel">
      <div className="panel-toolbar">
        <button onClick={registerAllStreams}><RefreshCw size={17} /> Register URLs</button>
        <button onClick={saveLogs}><Save size={17} /> Save Logs</button>
        <span className="hint">Live preview is RTSP only. Detection/logs come from CP Plus ANPR events.</span>
      </div>
      <div className="camera-grid">
        {cameras.slice(0, 14).map((camera) => (
          <article className="camera-card" key={camera.id}>
            <div className="camera-card-head">
              <div>
                <strong>{camera.name}</strong>
                <span>Camera {camera.id}</span>
              </div>
              <b>{cameraStats[camera.id]?.today_total || 0}</b>
            </div>
            <input value={camera.url} onChange={(event) => updateCameraUrl(camera.id, event.target.value)} placeholder="RTSP URL" />
            <div className="camera-preview">
              {running[camera.id] ? (
                <img src={`/camera_snapshot/${camera.id}?t=${previewTick}`} alt={`${camera.name} preview`} />
              ) : (
                <div className="empty-preview"><Camera size={30} /> Feed stopped</div>
              )}
            </div>
            <div className="button-row">
              <button onClick={() => startCamera(camera)}><Play size={16} /> Start</button>
              <button onClick={() => stopCamera(camera.id)}><Square size={16} /> Stop</button>
              <button onClick={() => openLogs(camera.id)}><Database size={16} /> Logs</button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
