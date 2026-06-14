const MILITARY_COLOR = "#3d9f78";
const CIVIL_COLOR = "#3987a8";
const GRID_COLOR = "#dfe5eb";

function formatNumber(value) {
  return Number(value || 0).toLocaleString();
}

export function DonutChart({ title, military = 0, civil = 0 }) {
  const militaryValue = Number(military || 0);
  const civilValue = Number(civil || 0);
  const total = militaryValue + civilValue;
  const militaryShare = total ? (militaryValue / total) * 100 : 0;

  return (
    <article className="chart-card">
      <div className="chart-card-head">
        <div>
          <h2>{title}</h2>
          <span>{formatNumber(total)} vehicles</span>
        </div>
        <div className="chart-legend" aria-label="Chart legend">
          <span><i style={{ background: MILITARY_COLOR }} /> Military</span>
          <span><i style={{ background: CIVIL_COLOR }} /> Civil</span>
        </div>
      </div>
      <div className="donut-layout">
        <div
          className="donut-chart"
          style={{
            background: total
              ? `conic-gradient(${MILITARY_COLOR} 0 ${militaryShare}%, ${CIVIL_COLOR} ${militaryShare}% 100%)`
              : `conic-gradient(${GRID_COLOR} 0 100%)`,
          }}
          role="img"
          aria-label={`${title}: ${militaryValue} military and ${civilValue} civil vehicles`}
        >
          <div className="donut-hole">
            <strong>{formatNumber(total)}</strong>
            <span>Total</span>
          </div>
        </div>
        <div className="donut-values">
          <div>
            <i style={{ background: MILITARY_COLOR }} />
            <span>Military</span>
            <strong>{formatNumber(militaryValue)}</strong>
          </div>
          <div>
            <i style={{ background: CIVIL_COLOR }} />
            <span>Civil</span>
            <strong>{formatNumber(civilValue)}</strong>
          </div>
        </div>
      </div>
    </article>
  );
}

export function BarChart({ title, labels = [], values = [], color, seriesLabel }) {
  const points = labels.map((label, index) => ({
    label,
    value: Number(values[index] || 0),
  }));
  const maxValue = Math.max(1, ...points.map((point) => point.value));
  const tickMax = maxValue <= 5 ? 5 : Math.ceil(maxValue / 5) * 5;
  const ticks = [tickMax, Math.round(tickMax * 0.75), Math.round(tickMax * 0.5), Math.round(tickMax * 0.25), 0];

  return (
    <article className="chart-card">
      <div className="chart-card-head">
        <div>
          <h2>{title}</h2>
          <span>Daily vehicle count</span>
        </div>
        <div className="chart-legend">
          <span><i style={{ background: color }} /> {seriesLabel}</span>
        </div>
      </div>
      <div className="bar-chart" role="img" aria-label={`${title}: ${points.map((point) => `${point.label} ${point.value}`).join(", ")}`}>
        <div className="bar-axis">
          {ticks.map((tick, index) => <span key={`${tick}-${index}`}>{tick}</span>)}
        </div>
        <div className="bar-plot">
          <div className="bar-grid" aria-hidden="true">
            {ticks.map((_, index) => <i key={index} />)}
          </div>
          <div className="bar-columns">
            {points.map((point) => (
              <div className="bar-column" key={point.label}>
                <div className="bar-track">
                  <i
                    style={{
                      height: `${(point.value / tickMax) * 100}%`,
                      background: color,
                    }}
                  />
                </div>
                <span className="bar-label">{point.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </article>
  );
}

export function GroupedBarChart({ title, labels = [], military = [], civil = [] }) {
  const points = labels.map((label, index) => ({
    label,
    military: Number(military[index] || 0),
    civil: Number(civil[index] || 0),
  }));
  const maxValue = Math.max(1, ...points.flatMap((point) => [point.military, point.civil]));
  const tickMax = maxValue <= 5 ? 5 : Math.ceil(maxValue / 5) * 5;
  const ticks = [tickMax, Math.round(tickMax * 0.75), Math.round(tickMax * 0.5), Math.round(tickMax * 0.25), 0];

  return (
    <article className="chart-card speed-chart-card">
      <div className="chart-card-head">
        <div>
          <h2>{title}</h2>
          <span>Vehicles recorded above 40 km/h today</span>
        </div>
        <div className="chart-legend">
          <span><i style={{ background: MILITARY_COLOR }} /> Military</span>
          <span><i style={{ background: CIVIL_COLOR }} /> Civil</span>
        </div>
      </div>
      <div className="bar-chart grouped-bar-chart">
        <div className="bar-axis">
          {ticks.map((tick, index) => <span key={`${tick}-${index}`}>{tick}</span>)}
        </div>
        <div className="bar-plot">
          <div className="bar-grid" aria-hidden="true">
            {ticks.map((_, index) => <i key={index} />)}
          </div>
          <div className="bar-columns">
            {points.map((point) => (
              <div className="bar-column grouped-bar-column" key={point.label}>
                <span className="bar-value">{point.military + point.civil}</span>
                <div className="grouped-bar-track">
                  <i style={{ height: `${(point.military / tickMax) * 100}%`, background: MILITARY_COLOR }} />
                  <i style={{ height: `${(point.civil / tickMax) * 100}%`, background: CIVIL_COLOR }} />
                </div>
                <span className="bar-label">{point.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </article>
  );
}

export const CHART_COLORS = {
  military: MILITARY_COLOR,
  civil: CIVIL_COLOR,
};
