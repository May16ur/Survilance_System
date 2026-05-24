import { RefreshCw } from "lucide-react";
import { Metric } from "../components/Metric.jsx";
import { SimpleTable, TcpTable } from "../components/Tables.jsx";

export function TcpPanel({ tcpName, tcpOptions, tcpReport, remaining, loadTcpReport }) {
  return (
    <section className="panel stack">
      <div className="panel-toolbar">
        <select value={tcpName} onChange={(e) => loadTcpReport(e.target.value)}>
          {(tcpOptions || []).map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
        </select>
        <button onClick={() => loadTcpReport(tcpName)}><RefreshCw size={17} /> Refresh</button>
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
