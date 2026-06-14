import { Activity, CalendarDays, CarFront, RefreshCw, Shield } from "lucide-react";
import { Metric } from "../components/Metric.jsx";
import { SimpleTable, TcpTable } from "../components/Tables.jsx";
import { BarChart, CHART_COLORS } from "../components/Charts.jsx";

export function TcpPanel({ tcpName, tcpOptions, tcpReport, tcpDashboard, remaining, loadTcpReport }) {
  const kpis = [
    { label: "Today's Vehicles", value: tcpDashboard?.today_total || 0, icon: Activity, tone: "cyan" },
    { label: "Military Vehicles", value: tcpDashboard?.today_mil || 0, icon: Shield, tone: "emerald" },
    { label: "Civil Vehicles", value: tcpDashboard?.today_civil || 0, icon: CarFront, tone: "amber" },
    { label: "Last 7 Days", value: tcpDashboard?.week_total || 0, icon: CalendarDays, tone: "violet" },
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
            <small>{tcpOptions.find((item) => item.key === tcpName)?.label || tcpName.toUpperCase()}</small>
          </article>
        ))}
      </div>
      <div className="dashboard-chart-grid tcp-dashboard-charts">
        <BarChart
          title="Military Vehicles (Last 7 Days)"
          labels={tcpDashboard?.dates || []}
          values={tcpDashboard?.mil || []}
          color={CHART_COLORS.military}
          seriesLabel="Military Vehicles"
        />
        <BarChart
          title="Civil Vehicles (Last 7 Days)"
          labels={tcpDashboard?.dates || []}
          values={tcpDashboard?.civil || []}
          color={CHART_COLORS.civil}
          seriesLabel="Civil Vehicles"
        />
      </div>
      <div className="metric-row">
        <Metric label="Detections" value={tcpReport?.total_detections || 0} />
        <Metric label="Rows" value={tcpReport?.total_rows || 0} />
        <Metric label="Matched" value={tcpReport?.matched_count || 0} />
        <Metric label="Waiting" value={tcpReport?.waiting_count || remaining?.total || 0} />
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
