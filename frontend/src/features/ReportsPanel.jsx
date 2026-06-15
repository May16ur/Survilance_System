import { Download, RefreshCw } from "lucide-react";
import { LogTable } from "../components/Tables.jsx";

export function ReportsPanel({ cameras, filters, setFilters, rows, loading, error, loadReport, downloadReport }) {
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
        <button disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={17} /> {loading ? "Loading..." : "Load"}</button>
        <button type="button" disabled={loading} onClick={downloadReport}><Download size={17} /> PDF</button>
      </form>
      {error && <div className="report-message error">{error}</div>}
      {!error && !loading && !rows.length && (
        <div className="report-message">No records found for the selected camera and date range.</div>
      )}
      <LogTable rows={rows} />
    </section>
  );
}
