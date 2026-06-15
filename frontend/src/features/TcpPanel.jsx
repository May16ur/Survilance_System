import { Activity, CalendarDays, CarFront, RefreshCw, Shield } from "lucide-react";
import { SimpleTable, TcpTable } from "../components/Tables.jsx";
import { BarChart, CHART_COLORS, SpeedPieChart } from "../components/Charts.jsx";
import { dateRangeDays, formatDateRange } from "../components/DateRangeSelector.jsx";

export function TcpPanel({ tcpName, tcpOptions, tcpReport, tcpDashboard, remaining, dateRange, loadTcpReport }) {
  const selectedMil = Number(tcpDashboard?.total_mil || 0);
  const selectedCivil = Number(tcpDashboard?.total_civil || 0);
  const periodLabel = formatDateRange(dateRange);
  const days = dateRangeDays(dateRange);
  const cameraBreakdown = tcpDashboard?.camera_breakdown || [];
  const combinedSpeed = cameraBreakdown.reduce(
    (totals, camera) => ({
      milOverspeed: totals.milOverspeed + Number(camera.mil_overspeed || 0),
      milWithinLimit: totals.milWithinLimit + Number(camera.mil_within_limit || 0),
      civilOverspeed: totals.civilOverspeed + Number(camera.civil_overspeed || 0),
      civilWithinLimit: totals.civilWithinLimit + Number(camera.civil_within_limit || 0),
    }),
    { milOverspeed: 0, milWithinLimit: 0, civilOverspeed: 0, civilWithinLimit: 0 }
  );
  const tcpLabel = tcpOptions.find((item) => item.key === tcpName)?.label || tcpName.toUpperCase();
  const kpis = [
    { label: "Selected Vehicles", value: selectedMil + selectedCivil, icon: Activity, tone: "cyan" },
    { label: "Military Vehicles", value: selectedMil, icon: Shield, tone: "emerald" },
    { label: "Civil Vehicles", value: selectedCivil, icon: CarFront, tone: "amber" },
    { label: "Daily Average", value: Math.round((selectedMil + selectedCivil) / Math.max(days, 1)), icon: CalendarDays, tone: "violet" },
  ];

  return (
    <section className="panel stack">
      <div className="panel-toolbar">
        <select value={tcpName} onChange={(e) => loadTcpReport(e.target.value)}>
          {(tcpOptions || []).map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
        </select>
        <button onClick={() => loadTcpReport(tcpName)}><RefreshCw size={17} /> Refresh</button>
      </div>
      <div className="dashboard-summary-grid tcp-summary-grid">
        {kpis.map(({ label, value, icon: Icon, tone }) => (
          <article className={`dashboard-summary-card ${tone}`} key={label}>
            <div className="kpi-card-top">
              <span>{label}</span>
              <i><Icon size={18} /></i>
            </div>
            <strong>{Number(value).toLocaleString()}</strong>
            <small>{tcpLabel}</small>
          </article>
        ))}
      </div>
      <div className="dashboard-chart-grid tcp-dashboard-charts">
        <BarChart
          title={`Military Vehicles (${periodLabel})`}
          labels={tcpDashboard?.dates || []}
          values={tcpDashboard?.mil || []}
          color={CHART_COLORS.military}
          seriesLabel="Military Vehicles"
        />
        <BarChart
          title={`Civil Vehicles (${periodLabel})`}
          labels={tcpDashboard?.dates || []}
          values={tcpDashboard?.civil || []}
          color={CHART_COLORS.civil}
          seriesLabel="Civil Vehicles"
        />
      </div>
      <div className="dashboard-chart-grid tcp-camera-pie-charts">
        <SpeedPieChart
          title={`${tcpLabel} Military Speed Status (${periodLabel})`}
          overspeed={combinedSpeed.milOverspeed}
          withinLimit={combinedSpeed.milWithinLimit}
          accent="#f97316"
        />
        <SpeedPieChart
          title={`${tcpLabel} Civil Speed Status (${periodLabel})`}
          overspeed={combinedSpeed.civilOverspeed}
          withinLimit={combinedSpeed.civilWithinLimit}
          accent="#ef4444"
        />
      </div>
      <TcpTable rows={tcpReport?.rows || []} />
      <SimpleTable
        title="Remaining Vehicles"
        rows={remaining?.rows || []}
        columns={[
          ["license", "License"],
          ["in_camera", "In Camera"],
          ["out_camera", "Out Camera"],
          ["time_in", "Time In"],
          ["remarks", "Remarks"],
        ]}
      />
    </section>
  );
}
