import { Activity, CalendarDays, CarFront, RefreshCw, Search, Shield, TrendingDown, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { BarChart, CHART_COLORS, SpeedPieChart } from "../components/Charts.jsx";
import { DateRangeSelector, dateRangeDays, formatDateRange } from "../components/DateRangeSelector.jsx";

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
          const matched = isMilitary ? pair.mil_veh_out : pair.civil_matched;
          const remaining = isMilitary ? pair.mil_local : pair.civil_remaining;
          return (
            <article className="tcp-report-card" key={`${type}-${pair.key}`}>
              <span>{pair.label}</span>
              {isMilitary ? (
                <>
                  <strong>{Number(total || 0).toLocaleString()}</strong>
                  <small>Veh Out: {matched || 0}</small>
                  <small>Local Veh: {remaining || 0}</small>
                </>
              ) : (
                <>
                  <strong>{Number(total || 0).toLocaleString()}</strong>
                  <small>Vehicles Crossed</small>
                </>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function SpeedReport({ pairs }) {
  return (
    <div className="dashboard-section speed-report-section">
      <div className="speed-report-heading">
        <div>
          <span className="section-kicker">Speed Monitoring</span>
        </div>
        <strong>&gt; 40 km/h</strong>
      </div>
      <div className="speed-report-table">
        <div className="speed-report-row speed-report-labels">
          <span>Vehicle Type</span>
          {pairs.map((pair) => <b key={pair.key}>{pair.label.replace(" TCP", "")}</b>)}
        </div>
        <div className="speed-report-row">
          <span><i className="mil-speed-dot" /> Military</span>
          {pairs.map((pair) => <strong key={pair.key}>{pair.mil_over_speed || 0}</strong>)}
        </div>
        <div className="speed-report-row">
          <span><i className="civil-speed-dot" /> Civil</span>
          {pairs.map((pair) => <strong key={pair.key}>{pair.civil_over_speed || 0}</strong>)}
        </div>
      </div>
    </div>
  );
}

function SundayMilitaryReport({ report }) {
  const rows = report?.rows || [];
  return (
    <div className="dashboard-section sunday-report-section">
      <div className="sunday-report-heading">
        <div>
          <span className="section-kicker">Weekly Movement Register</span>
          <h2>Sunday Military Vehicle Report</h2>
        </div>
        <div className="sunday-report-meta">
          <strong>{report?.report_date || "Latest Sunday"}</strong>
          <span>{report?.total || 0} movements</span>
        </div>
      </div>
      <div className="sunday-report-table-wrap">
        <table className="sunday-report-table">
          <thead>
            <tr>
              <th>Ser</th>
              <th>Track</th>
              <th>License</th>
              <th>Unit</th>
              <th>Vehicle Type</th>
              <th>Make / Model</th>
              <th>Driver</th>
              <th>Speed</th>
              <th>Time</th>
              <th>Camera</th>
              <th>Source</th>
              <th>Remarks</th>
              <th>Plate</th>
              <th>Vehicle</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const plate = row.plate || row.license_img || row.plate_img;
              const vehicle = row.vehicle || row.veh_img || row.vehicle_img;
              return (
                <tr key={`${row.id || row.track_id || row.license}-${index}`}>
                  <td>{index + 1}</td>
                  <td>{row.track_id || "-"}</td>
                  <td><strong>{row.license || row.license_plate || "Unknown"}</strong></td>
                  <td>{row.unit || "Mil"}</td>
                  <td>{row.vehicle_type_master || row.class_name || "Military"}</td>
                  <td>{row.make_model || "-"}</td>
                  <td>{row.driver_name || "-"}</td>
                  <td>{row.avg_speed || row.speed || "-"}</td>
                  <td>{row.time || row.detection_time || "-"}</td>
                  <td>{row.camera_name || "-"}</td>
                  <td>{row.source_type || "vehicle_logs"}</td>
                  <td>{row.vehicle_remarks || row.remarks || "-"}</td>
                  <td>{plate ? <a href={plate} target="_blank" rel="noreferrer"><img className="thumb" src={plate} alt="Plate" /></a> : "-"}</td>
                  <td>{vehicle ? <a href={vehicle} target="_blank" rel="noreferrer"><img className="thumb" src={vehicle} alt="Vehicle" /></a> : "-"}</td>
                </tr>
              );
            })}
            {!rows.length && (
              <tr>
                <td colSpan="14" className="empty-table">No military vehicle movement recorded for this Sunday.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function DashboardPanel({ dashboard, dashboardTrend, comparison, diagnostic, sundayMilitary, cameras, cameraStats, dateRange, applyDateRange, status, refresh, openCameraLogs }) {
  const [cameraSearch, setCameraSearch] = useState("");
  const comparisonPairs = comparison?.pairs || {};
  const pairs = DEFAULT_TCP_REPORTS.map((fallback) => {
    const live = comparisonPairs[fallback.key] || {};
    return { ...fallback, ...live, label: fallback.label };
  });
  const selectedMil = Number(dashboard?.total_mil ?? 0);
  const selectedCivil = Number(dashboard?.total_civil ?? 0);
  const selectedTotal = selectedMil + selectedCivil;
  const dailyTotals = dashboard?.total || [];
  const previousDayTotal = Number(dailyTotals[dailyTotals.length - 2] || 0);
  const finalDayTotal = Number(dailyTotals[dailyTotals.length - 1] || 0);
  const dailyChange = previousDayTotal ? ((finalDayTotal - previousDayTotal) / previousDayTotal) * 100 : 0;
  const periodDays = dateRangeDays(dateRange);
  const periodLabel = formatDateRange(dateRange);
  const filteredCameras = useMemo(() => {
    const query = cameraSearch.trim().toLowerCase();
    return query ? cameras.filter((camera) => camera.name.toLowerCase().includes(query)) : cameras;
  }, [cameraSearch, cameras]);
  const summaryCards = [
    { label: "Selected Vehicles", value: selectedTotal, detail: periodLabel, trend: 0, icon: Activity, tone: "cyan" },
    { label: "Military Vehicles", value: selectedMil, detail: `${selectedTotal ? Math.round((selectedMil / selectedTotal) * 100) : 0}% of selected traffic`, trend: 0, icon: Shield, tone: "emerald" },
    { label: "Civil Vehicles", value: selectedCivil, detail: `${selectedTotal ? Math.round((selectedCivil / selectedTotal) * 100) : 0}% of selected traffic`, trend: 0, icon: CarFront, tone: "amber" },
    { label: "Daily Average", value: Math.round(selectedTotal / Math.max(periodDays, 1)), detail: `${periodDays} day${periodDays === 1 ? "" : "s"} selected`, trend: dailyChange, icon: CalendarDays, tone: "violet" },
  ];
  const backendOnline = /online|refreshed/i.test(status || "");

  return (
    <section className="dashboard-console">
      <header className="dashboard-command-bar">
        <div className="dashboard-title-block">
          <span className="section-kicker">e-TCP Operations Console</span>
          <h1>Vehicle Intelligence Dashboard</h1>
          <p>Real-time ANPR, traffic movement and TCP monitoring</p>
        </div>
        <div className="dashboard-command-actions">
          <DateRangeSelector value={dateRange} onApply={applyDateRange} dark />
          <label className="dashboard-search">
            <Search size={16} />
            <input
              value={cameraSearch}
              onChange={(event) => setCameraSearch(event.target.value)}
              placeholder="Search cameras..."
            />
          </label>
          <button className="dashboard-refresh" onClick={refresh}>
            <RefreshCw size={16} /> Refresh
          </button>
          <div className={`dashboard-system-status ${backendOnline ? "online" : "offline"}`}>
            <i />
            <span>{backendOnline ? "System Online" : "System Offline"}</span>
          </div>
        </div>
      </header>

      <div className="dashboard-section camera-section">
        <div className="dashboard-section-head">
          <div>
            <span className="section-kicker">Network Status</span>
            <h2>Live Cameras</h2>
          </div>
          <span className="camera-count">{filteredCameras.length} endpoints</span>
        </div>
        <div className="dashboard-camera-chips">
          {filteredCameras.map((camera, index) => (
            <button
              className={`dashboard-camera-chip ${index === 0 && !cameraSearch ? "active" : ""}`}
              key={camera.id}
              onClick={() => openCameraLogs(camera.id)}
              title={`Open ${camera.name} logs`}
            >
              <i className="camera-live-dot" />
              <span>{camera.name}</span>
              <b>{Number(cameraStats[camera.id]?.today_mil || 0) + Number(cameraStats[camera.id]?.today_civil || 0)}</b>
            </button>
          ))}
        </div>
      </div>

      <div className="dashboard-summary-grid">
        {summaryCards.map(({ label, value, detail, trend, icon: Icon, tone }) => (
          <article className={`dashboard-summary-card ${tone}`} key={label}>
            <div className="kpi-card-top">
              <span>{label}</span>
              <i><Icon size={18} /></i>
            </div>
            <strong>{Number(value || 0).toLocaleString()}</strong>
            <small className={trend < 0 ? "negative" : ""}>
              {trend < 0 ? <TrendingDown size={13} /> : trend > 0 ? <TrendingUp size={13} /> : null}
              {detail}
            </small>
          </article>
        ))}
      </div>

      <TcpReportGroup title="TCP Reports (Military Vehicles)" pairs={pairs} type="mil" />
      <TcpReportGroup title="TCP Reports (Civil Vehicles)" pairs={pairs} type="civil" />

      <p className="tcp-report-note dashboard-total-note">
        Dashboard total is the sum of all seven TCP trips. End-date diagnostic: {diagnostic?.dashboard_total ?? diagnostic?.today_total ?? 0}.
      </p>

      <div className="dashboard-chart-grid">
        <BarChart
          title="Military Vehicles (Last 7 Days)"
          labels={dashboardTrend?.dates || []}
          values={dashboardTrend?.mil || []}
          color={CHART_COLORS.military}
          seriesLabel="Military Vehicles"
        />
        <BarChart
          title="Civil Vehicles (Last 7 Days)"
          labels={dashboardTrend?.dates || []}
          values={dashboardTrend?.civil || []}
          color={CHART_COLORS.civil}
          seriesLabel="Civil Vehicles"
        />
      </div>

      <div className="dashboard-chart-grid">
        <SpeedPieChart
          title={`Military Speed Status (${periodLabel})`}
          overspeed={dashboard?.mil_overspeed}
          withinLimit={dashboard?.mil_within_limit}
          accent="#f97316"
        />
        <SpeedPieChart
          title={`Civil Speed Status (${periodLabel})`}
          overspeed={dashboard?.civil_overspeed}
          withinLimit={dashboard?.civil_within_limit}
          accent="#ef4444"
        />
      </div>

      <SpeedReport pairs={pairs} />
      <SundayMilitaryReport report={sundayMilitary} />
    </section>
  );
}
