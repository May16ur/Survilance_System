import { Play, RefreshCw, Square } from "lucide-react";
import { WebRtcPreview } from "../components/WebRtcPreview.jsx";
import { LogTable } from "../components/Tables.jsx";
import { TcpReportGroup } from "./DashboardPanel.jsx";

const DEFAULT_TCP_REPORTS = [
  { key: "igoo", label: "IGOO TCP" },
  { key: "kiari", label: "Kiari TCP" },
  { key: "cthang", label: "C/Thang TCP" },
  { key: "nyoma", label: "Nyoma TCP" },
  { key: "loma", label: "Loma TCP" },
  { key: "hanle", label: "Hanle TCP" },
  { key: "chushul", label: "Chushul TCP" },
];

export function LogsPanel({
  cameras,
  selectedCamera,
  loadCameraLogs,
  rows,
  deleteLog,
  running,
  startCamera,
  stopCamera,
  comparison,
}) {
  const camera = cameras.find((item) => Number(item.id) === Number(selectedCamera));
  const comparisonPairs = comparison?.pairs || {};
  const pairs = DEFAULT_TCP_REPORTS.map((fallback) => ({
    ...fallback,
    ...(comparisonPairs[fallback.key] || {}),
    label: fallback.label,
  }));

  return (
    <section className="panel">
      <div className="panel-toolbar">
        <select value={selectedCamera} onChange={(event) => loadCameraLogs(Number(event.target.value))}>
          {cameras.map((camera) => <option key={camera.id} value={camera.id}>{camera.id}. {camera.name}</option>)}
        </select>
        <button onClick={() => loadCameraLogs(selectedCamera)}><RefreshCw size={17} /> Refresh</button>
        {camera && !running[camera.id] && <button onClick={() => startCamera(camera)}><Play size={16} /> Start Feed</button>}
        {camera && running[camera.id] && <button onClick={() => stopCamera(camera.id)}><Square size={16} /> Stop Feed</button>}
      </div>
      <div className="logs-feed-panel">
        <div className="logs-feed-head">
          <div>
            <strong>{camera?.name || "Selected Camera"}</strong>
            <span>Camera {selectedCamera} live RTSP preview</span>
          </div>
          <b>{rows?.length || 0} logs</b>
        </div>
        <div className="camera-preview logs-preview">
          <WebRtcPreview camera={camera} running={Boolean(camera && running[camera.id])} />
        </div>
      </div>
      <div className="logs-tcp-reports">
        <TcpReportGroup title="TCP Reports (Military Vehicles)" pairs={pairs} type="mil" />
        <TcpReportGroup title="TCP Reports (Civil Vehicles)" pairs={pairs} type="civil" />
      </div>
      <LogTable rows={rows} onDelete={deleteLog} />
    </section>
  );
}
