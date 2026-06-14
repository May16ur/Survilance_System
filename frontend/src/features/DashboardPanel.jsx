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

function TcpReportGroup({ title, pairs, type }) {
  const isMilitary = type === "mil";
  return (
    <div className={`dashboard-section tcp-report-section ${isMilitary ? "military-tcp-section" : "civil-tcp-section"}`}>
      <h2>{title}</h2>
      <div className="tcp-report-grid">
        {pairs.map((pair) => {
          const total = isMilitary ? pair.mil_total : pair.civil_total;
          const matched = isMilitary ? pair.mil_matched : pair.civil_matched;
          const remaining = isMilitary ? pair.mil_remaining : pair.civil_remaining;
          return (
            <article className="tcp-report-card" key={`${type}-${pair.key}`}>
              <span>{pair.label}</span>
              <strong>{Number(total || 0).toLocaleString()}</strong>
              <small>Veh Out: {matched || 0}</small>
              <small>Local Veh: {remaining || 0}</small>
            </article>
          );
        })}
      </div>
    </div>
  );
}

export function DashboardPanel({ dashboard, comparison, diagnostic, cameras, cameraStats, refresh, openCameraLogs }) {
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
            <button
              className="dashboard-camera-chip"
              key={camera.id}
              onClick={() => openCameraLogs(camera.id)}
              title={`Open ${camera.name} logs`}
            >
              <span>{camera.name}</span>
              <b>{cameraStats[camera.id]?.today_total || 0}</b>
            </button>
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

      <TcpReportGroup title="TCP Reports (Military Vehicles)" pairs={pairs} type="mil" />
      <TcpReportGroup title="TCP Reports (Civil Vehicles)" pairs={pairs} type="civil" />

      <p className="tcp-report-note dashboard-total-note">
        Dashboard total is the sum of all seven TCP trips. Diagnostic total: {diagnostic?.dashboard_total ?? diagnostic?.today_total ?? 0}.
      </p>

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
