import { Activity, CalendarDays, CarFront, Play, RefreshCw, Shield, Square } from "lucide-react";
import { WebRtcPreview } from "../components/WebRtcPreview.jsx";
import { LogTable } from "../components/Tables.jsx";
import { formatDateRange } from "../components/DateRangeSelector.jsx";

export function LogsPanel({
  cameras,
  selectedCamera,
  loadCameraLogs,
  rows,
  cameraDashboard,
  dateRange,
  deleteLog,
  running,
  startCamera,
  stopCamera,
}) {
  const camera = cameras.find((item) => Number(item.id) === Number(selectedCamera));
  const selectedMil = Number(cameraDashboard?.total_mil || 0);
  const selectedCivil = Number(cameraDashboard?.total_civil || 0);
  const kpis = [
    { label: "Selected Vehicles", value: selectedMil + selectedCivil, icon: Activity, tone: "cyan" },
    { label: "Military Vehicles", value: selectedMil, icon: Shield, tone: "emerald" },
    { label: "Civil Vehicles", value: selectedCivil, icon: CarFront, tone: "amber" },
    { label: "Date Range", value: rows?.length || 0, icon: CalendarDays, tone: "violet" },
  ];

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
      <div className="dashboard-summary-grid camera-log-summary-grid">
        {kpis.map(({ label, value, icon: Icon, tone }) => (
          <article className={`dashboard-summary-card ${tone}`} key={label}>
            <div className="kpi-card-top">
              <span>{label}</span>
              <i><Icon size={18} /></i>
            </div>
            <strong>{Number(value).toLocaleString()}</strong>
            <small>{label === "Date Range" ? `${formatDateRange(dateRange)} logs shown` : camera?.name || `Camera ${selectedCamera}`}</small>
          </article>
        ))}
      </div>
      <LogTable rows={rows} onDelete={deleteLog} />
    </section>
  );
}
