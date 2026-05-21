import { RefreshCw } from "lucide-react";
import { Metric } from "../components/Metric.jsx";
import { SimpleTable } from "../components/Tables.jsx";

export function DashboardPanel({ dashboard, comparison, diagnostic, cameras, cameraStats, refresh }) {
  const pairs = comparison?.pairs ? Object.values(comparison.pairs) : [];
  return (
    <section className="panel stack">
      <div className="panel-toolbar">
        <button onClick={refresh}><RefreshCw size={17} /> Refresh Dashboard</button>
      </div>
      <div className="metric-row">
        <Metric label="Dashboard Total" value={dashboard?.today_total ?? comparison?.today_total ?? 0} />
        <Metric label="Dashboard Mil" value={dashboard?.today_mil ?? 0} />
        <Metric label="Dashboard Civil" value={dashboard?.today_civil ?? 0} />
        <Metric label="Diagnostic Total" value={diagnostic?.dashboard_total ?? diagnostic?.today_total ?? 0} />
      </div>
      <div className="camera-grid compact">
        {cameras.map((camera) => (
          <article className="camera-card" key={camera.id}>
            <div className="camera-card-head">
              <div>
                <strong>{camera.name}</strong>
                <span>Mil {cameraStats[camera.id]?.today_mil || 0} | Civil {cameraStats[camera.id]?.today_civil || 0}</span>
              </div>
              <b>{cameraStats[camera.id]?.today_total || 0}</b>
            </div>
          </article>
        ))}
      </div>
      <SimpleTable
        title="TCP Comparison"
        rows={pairs}
        columns={[
          ["label", "TCP"],
          ["in_camera", "In Camera"],
          ["out_camera", "Out Camera"],
          ["veh_in", "Total"],
          ["matched", "Matched"],
          ["remaining", "Remaining"],
        ]}
      />
    </section>
  );
}
