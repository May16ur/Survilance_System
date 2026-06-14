import { RefreshCw } from "lucide-react";
import { BarChart, CHART_COLORS } from "../components/Charts.jsx";

const DEFAULT_TCP_REPORTS = [
  { key: "igoo", label: "IGOO TCP" },
  { key: "kiari", label: "Kiari TCP" },
  { key: "cthang", label: "C/Thang TCP" },
  { key: "nyoma", label: "Nyoma TCP" },
  { key: "loma", label: "Loma TCP" },
  { key: "hanle", label: "Hanle TCP" },
  { key: "chushul", label: "Chushul TCP" },
];

export function DashboardPanel({ dashboard, comparison, diagnostic, cameras, cameraStats, refresh }) {
  const comparisonPairs = comparison?.pairs || {};
  const pairs = DEFAULT_TCP_REPORTS.map((fallback) => {
    const live = comparisonPairs[fallback.key] || {};
    return { ...fallback, ...live, label: fallback.label };
  });
  const summaryCards = [
    ["Today's Total Veh", dashboard?.today_total ?? comparison?.today_total ?? 0],
    ["Today's Mil Veh", dashboard?.today_mil ?? 0],
    ["Today's Civil Veh", dashboard?.today_civil ?? 0],
    ["Total Veh in Last 7 Days", dashboard?.week_total ?? 0],
  ];

  return (
    <section className="dashboard-console">
      <div className="dashboard-section camera-section">
        <div className="dashboard-section-head">
          <h2>Cameras</h2>
          <button className="dashboard-refresh" onClick={refresh}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
        <div className="dashboard-camera-chips">
          {cameras.map((camera) => (
            <div className="dashboard-camera-chip" key={camera.id}>
              <span>{camera.name}</span>
              <b>{cameraStats[camera.id]?.today_total || 0}</b>
            </div>
          ))}
        </div>
      </div>

      <div className="dashboard-summary-grid">
        {summaryCards.map(([label, value]) => (
          <article className="dashboard-summary-card" key={label}>
            <span>{label}</span>
            <strong>{Number(value || 0).toLocaleString()}</strong>
          </article>
        ))}
      </div>

      <div className="dashboard-section tcp-report-section">
        <h2>TCP Reports</h2>
        <div className="tcp-report-grid">
          {pairs.map((pair) => (
            <article className="tcp-report-card" key={pair.label}>
              <span>{pair.label}</span>
              <strong>{Number(pair.veh_in || 0).toLocaleString()}</strong>
              <small>Veh Out: {pair.matched || 0}</small>
              <small>Local Veh: {pair.remaining || 0}</small>
            </article>
          ))}
        </div>
        <p className="tcp-report-note">
          Dashboard total is the sum of the seven TCP report trips. Diagnostic total: {diagnostic?.dashboard_total ?? diagnostic?.today_total ?? 0}.
        </p>
      </div>

      <div className="dashboard-chart-grid">
        <BarChart
          title="Military Vehicles (Last 7 Days)"
          labels={dashboard?.dates || []}
          values={dashboard?.mil || []}
          color={CHART_COLORS.military}
          seriesLabel="Military Vehicles"
        />
        <BarChart
          title="Civil Vehicles (Last 7 Days)"
          labels={dashboard?.dates || []}
          values={dashboard?.civil || []}
          color={CHART_COLORS.civil}
          seriesLabel="Civil Vehicles"
        />
      </div>
    </section>
  );
}
