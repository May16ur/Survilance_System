import { Download, RefreshCw } from "lucide-react";
import { LogTable } from "../components/Tables.jsx";

export function ReportsPanel({ cameras, filters, setFilters, rows, loadReport, downloadReport }) {
  return (
    <section className="panel stack">
      <form className="filter-bar" onSubmit={loadReport}>
        <select value={filters.vehicle_type} onChange={(e) => setFilters({ ...filters, vehicle_type: e.target.value })}>
          <option value="all">All Vehicles</option>
          <option value="mil">Military</option>
          <option value="civil">Civil</option>
        </select>
        <select value={filters.camera_id} onChange={(e) => setFilters({ ...filters, camera_id: e.target.value })}>
          <option value="">All Cameras</option>
          {cameras.map((camera) => <option key={camera.id} value={camera.id}>{camera.id}. {camera.name}</option>)}
        </select>
        <input type="date" value={filters.start_date} onChange={(e) => setFilters({ ...filters, start_date: e.target.value })} />
        <input type="date" value={filters.end_date} onChange={(e) => setFilters({ ...filters, end_date: e.target.value })} />
        <button><RefreshCw size={17} /> Load</button>
        <button type="button" onClick={downloadReport}><Download size={17} /> PDF</button>
      </form>
      <LogTable rows={rows} />
    </section>
  );
}
