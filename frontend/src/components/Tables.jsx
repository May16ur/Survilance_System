import { Trash2 } from "lucide-react";

function imagePath(row, keys) {
  for (const key of keys) {
    if (row?.[key]) return row[key];
  }
  return "";
}

export function displayUnit(row) {
  const unit = String(row?.unit || "").trim();
  if (unit && unit.toLowerCase() !== "no record found") return unit;
  const className = String(row?.["Class Name"] || row?.class_name || "").toLowerCase();
  const classId = String(row?.class_id ?? "");
  if (classId === "0" || className.includes("mil")) return "Mil";
  if (classId === "1" || className.includes("civil")) return "Civil";
  return "";
}

export function LogTable({ rows, onDelete }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Track</th>
            <th>Class</th>
            <th>Speed</th>
            <th>License</th>
            <th>Unit</th>
            <th>Time</th>
            <th>Camera</th>
            <th>Source</th>
            <th>Plate</th>
            <th>Vehicle</th>
            {onDelete && <th>Action</th>}
          </tr>
        </thead>
        <tbody>
          {(rows || []).map((row, index) => {
            const plate = imagePath(row, ["plate", "license_img", "plate_feature"]);
            const vehicle = imagePath(row, ["vehicle", "veh_img", "vehicle_body_matting"]);
            return (
              <tr key={`${row.id || row["Track ID"] || row.track_id}-${index}`}>
                <td>{row["Track ID"] || row.track_id || ""}</td>
                <td>{row["Class Name"] || row.class_name || ""}</td>
                <td>{row["Avg Speed"] || row.avg_speed || row.speed || ""}</td>
                <td>{row["License"] || row.license || row.plate_no || ""}</td>
                <td>{displayUnit(row)}</td>
                <td>{row["Time"] || row.time || row.timestamp || row.time_in || ""}</td>
                <td>{row.camera_name || row.camera || ""}</td>
                <td>{row.source_type || row.source_table || ""}</td>
                <td>{plate ? <a href={plate} target="_blank"><img className="thumb" src={plate} alt="Plate" /></a> : "No image"}</td>
                <td>{vehicle ? <a href={vehicle} target="_blank"><img className="thumb" src={vehicle} alt="Vehicle" /></a> : "No image"}</td>
                {onDelete && <td><button onClick={() => onDelete(row)}><Trash2 size={15} /> Delete</button></td>}
              </tr>
            );
          })}
          {!rows?.length && <tr><td colSpan={onDelete ? 11 : 10} className="empty-table">No logs loaded.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export function TcpTable({ rows }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Ser</th><th>TCP</th><th>License</th><th>Unit</th><th>Class</th><th>Track</th>
            <th>In Camera</th><th>Out Camera</th><th>Time In</th><th>Time Out</th>
            <th>Status</th><th>Remarks</th><th>Plate</th><th>Vehicle</th>
          </tr>
        </thead>
        <tbody>
          {(rows || []).map((row, index) => (
            <tr key={`${row.license}-${row.time_in}-${index}`}>
              <td>{row.ser_no || index + 1}</td>
              <td>{row.tcp}</td>
              <td>{row.license}</td>
              <td>{displayUnit(row)}</td>
              <td>{row.class_name}</td>
              <td>{row.track_id}</td>
              <td>{row.in_camera}</td>
              <td>{row.out_camera}</td>
              <td>{row.time_in}</td>
              <td>{row.time_out}</td>
              <td>{row.matched ? "Matched" : "Waiting"}</td>
              <td>{row.remarks || ""}</td>
              <td>{row.plate ? <img className="thumb" src={row.plate} alt="Plate" /> : "No image"}</td>
              <td>{row.vehicle ? <img className="thumb" src={row.vehicle} alt="Vehicle" /> : "No image"}</td>
            </tr>
          ))}
          {!rows?.length && <tr><td colSpan="14" className="empty-table">No TCP rows loaded.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export function SimpleTable({ title, rows, columns }) {
  return (
    <div className="list-block">
      <h2>{title}</h2>
      <div className="table-wrap no-max">
        <table>
          <thead>
            <tr>{columns.map(([, label]) => <th key={label}>{label}</th>)}</tr>
          </thead>
          <tbody>
            {(rows || []).map((row, index) => (
              <tr key={index}>
                {columns.map(([key]) => <td key={key}>{String(row?.[key] ?? "")}</td>)}
              </tr>
            ))}
            {!rows?.length && <tr><td colSpan={columns.length} className="empty-table">No rows.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
