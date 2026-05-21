import { RefreshCw } from "lucide-react";
import { LogTable } from "../components/Tables.jsx";

export function LogsPanel({ cameras, selectedCamera, loadCameraLogs, rows, deleteLog }) {
  return (
    <section className="panel">
      <div className="panel-toolbar">
        <select value={selectedCamera} onChange={(event) => loadCameraLogs(Number(event.target.value))}>
          {cameras.map((camera) => <option key={camera.id} value={camera.id}>{camera.id}. {camera.name}</option>)}
        </select>
        <button onClick={() => loadCameraLogs(selectedCamera)}><RefreshCw size={17} /> Refresh</button>
      </div>
      <LogTable rows={rows} onDelete={deleteLog} />
    </section>
  );
}
