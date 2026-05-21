import { Search, ShieldAlert } from "lucide-react";
import { List } from "../components/List.jsx";

export function AlertsPanel({
  blacklist,
  alerts,
  searchResults,
  plateSearch,
  setPlateSearch,
  addBlacklist,
  deleteBlacklist,
  searchPlate,
}) {
  return (
    <section className="panel two-column">
      <div>
        <form className="inline-form" onSubmit={addBlacklist}>
          <input name="license_plate" placeholder="License plate" />
          <input name="remarks" placeholder="Remarks" />
          <button><ShieldAlert size={17} /> Add</button>
        </form>
        <List title="Blacklist" rows={blacklist} empty="No blacklisted vehicles." onDelete={deleteBlacklist} />
      </div>
      <div>
        <form className="inline-form" onSubmit={searchPlate}>
          <input value={plateSearch} onChange={(event) => setPlateSearch(event.target.value)} placeholder="Search license" />
          <button><Search size={17} /> Search</button>
        </form>
        <List title="Recent Alerts & Search" rows={[...alerts, ...searchResults]} empty="No alert/search rows." />
      </div>
    </section>
  );
}
