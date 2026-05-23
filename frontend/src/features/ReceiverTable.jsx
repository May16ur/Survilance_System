export function ReceiverTable({ events }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Plate</th><th>Unit</th><th>Confidence</th><th>Vehicle</th><th>Class</th><th>Color</th>
            <th>Speed</th><th>Camera</th><th>Received</th><th>Camera Time</th><th>Vehicle Image</th><th>Plate Image</th>
          </tr>
        </thead>
        <tbody>
          {(events || []).map((event) => {
            const row = event.parsed || {};
            return (
              <tr key={event.event_file || event.fingerprint || `${row.camera_id}-${row.time}-${row.license}`}>
                <td>{row.plate_number || row.license || "UNKNOWN"}</td>
                <td>{row.unit || ""}</td>
                <td>{row.plate_confidence ?? ""}</td>
                <td>{row.vehicle_type || row.class_name || ""}</td>
                <td>{row.class_name || ""}</td>
                <td>{row.vehicle_color || row.plate_color || ""}</td>
                <td>{row.speed || ""}</td>
                <td>{row.camera_name || ""}</td>
                <td>{event.received_at || event.saved_at || ""}</td>
                <td>{row.time || ""}</td>
                <td>{row.veh_img ? <a href={row.veh_img} target="_blank"><img className="thumb" src={row.veh_img} alt="ANPR vehicle" /></a> : "No image"}</td>
                <td>{row.license_img ? <a href={row.license_img} target="_blank"><img className="thumb" src={row.license_img} alt="ANPR plate" /></a> : "No crop"}</td>
              </tr>
            );
          })}
          {!events?.length && <tr><td colSpan="12" className="empty-table">No receiver events found.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
