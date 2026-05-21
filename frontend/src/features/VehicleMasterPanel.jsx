import { RefreshCw, Save } from "lucide-react";
import { SimpleTable } from "../components/Tables.jsx";

export function VehicleMasterPanel({ rows, saveVehicleMaster, refresh }) {
  return (
    <section className="panel stack">
      <form className="vehicle-form" onSubmit={saveVehicleMaster}>
        <input name="license_plate" placeholder="License plate" />
        <input name="make_model" placeholder="Make / model" />
        <input name="vehicle_type" placeholder="Vehicle type" />
        <input name="unit" placeholder="Unit" />
        <input name="driver_name" placeholder="Driver name" />
        <input name="remarks" placeholder="Remarks" />
        <button><Save size={17} /> Save Vehicle</button>
        <button type="button" onClick={refresh}><RefreshCw size={17} /> Refresh</button>
      </form>
      <SimpleTable
        title="Vehicle Master"
        rows={rows}
        columns={[
          ["license_plate", "License"],
          ["make_model", "Make / Model"],
          ["vehicle_type", "Type"],
          ["unit", "Unit"],
          ["driver_name", "Driver"],
          ["remarks", "Remarks"],
        ]}
      />
    </section>
  );
}
