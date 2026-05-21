import { Trash2 } from "lucide-react";

export function List({ title, rows, empty, onDelete }) {
  return (
    <div className="list-block">
      <h2>{title}</h2>
      {(rows || []).map((row, index) => {
        const plate = row.license_plate || row.license || row.plate_no || "Unknown";
        return (
          <article key={`${plate}-${index}`} className="list-row action-row">
            <div>
              <strong>{plate}</strong>
              <span>{row.remarks || row.camera_name || row.type || row.class_name || ""}</span>
              <small>{row.created_at || row.time || row.timestamp || ""}</small>
            </div>
            {onDelete && <button onClick={() => onDelete(plate)}><Trash2 size={15} /> Delete</button>}
          </article>
        );
      })}
      {!rows?.length && <div className="empty-table">{empty}</div>}
    </div>
  );
}
