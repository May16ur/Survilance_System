import { CalendarDays } from "lucide-react";
import { useEffect, useState } from "react";

function localDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function createDateRange(days = 7, endOffset = 0) {
  const end = new Date();
  end.setHours(12, 0, 0, 0);
  end.setDate(end.getDate() - endOffset);
  const start = new Date(end);
  start.setDate(start.getDate() - Math.max(1, days) + 1);
  return { start_date: localDateKey(start), end_date: localDateKey(end) };
}

export function dateRangeDays(range) {
  if (!range?.start_date || !range?.end_date) return 0;
  const start = new Date(`${range.start_date}T12:00:00`);
  const end = new Date(`${range.end_date}T12:00:00`);
  return Math.max(1, Math.round((end - start) / 86400000) + 1);
}

export function formatDateRange(range) {
  if (!range?.start_date || !range?.end_date) return "Selected period";
  const options = { day: "numeric", month: "short", year: "numeric" };
  const start = new Date(`${range.start_date}T12:00:00`).toLocaleDateString("en-IN", options);
  const end = new Date(`${range.end_date}T12:00:00`).toLocaleDateString("en-IN", options);
  return range.start_date === range.end_date ? start : `${start} - ${end}`;
}

const PRESETS = [
  { value: "today", label: "Today", range: () => createDateRange(1) },
  { value: "yesterday", label: "Yesterday", range: () => createDateRange(1, 1) },
  { value: "2", label: "Last 2 Days", range: () => createDateRange(2) },
  { value: "7", label: "Last 7 Days", range: () => createDateRange(7) },
  { value: "30", label: "Last 30 Days", range: () => createDateRange(30) },
];

function matchingPreset(range) {
  return PRESETS.find((preset) => {
    const presetRange = preset.range();
    return presetRange.start_date === range?.start_date && presetRange.end_date === range?.end_date;
  })?.value || "custom";
}

export function DateRangeSelector({ value, onApply, dark = false }) {
  const [draft, setDraft] = useState(value);
  const [preset, setPreset] = useState(() => matchingPreset(value));

  useEffect(() => {
    setDraft(value);
    setPreset(matchingPreset(value));
  }, [value?.start_date, value?.end_date]);

  function choosePreset(event) {
    const nextPreset = event.target.value;
    setPreset(nextPreset);
    if (nextPreset === "custom") return;
    const nextRange = PRESETS.find((item) => item.value === nextPreset).range();
    setDraft(nextRange);
    onApply(nextRange);
  }

  function applyCustom() {
    if (!draft.start_date || !draft.end_date) return;
    const normalized = draft.start_date <= draft.end_date
      ? draft
      : { start_date: draft.end_date, end_date: draft.start_date };
    setDraft(normalized);
    onApply(normalized);
  }

  return (
    <div className={`date-range-selector ${dark ? "dark" : ""}`}>
      <CalendarDays size={16} />
      <select value={preset} onChange={choosePreset} aria-label="Date range preset">
        {PRESETS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        <option value="custom">Custom Range</option>
      </select>
      {preset === "custom" && (
        <>
          <input
            type="date"
            value={draft.start_date}
            max={draft.end_date || undefined}
            onChange={(event) => setDraft({ ...draft, start_date: event.target.value })}
            aria-label="Start date"
          />
          <span>to</span>
          <input
            type="date"
            value={draft.end_date}
            min={draft.start_date || undefined}
            onChange={(event) => setDraft({ ...draft, end_date: event.target.value })}
            aria-label="End date"
          />
          <button type="button" onClick={applyCustom}>Apply</button>
        </>
      )}
    </div>
  );
}
