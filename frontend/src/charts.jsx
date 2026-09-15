import React from "react";

// Deliberately no charting library (recharts/d3/etc.) - spec section 34
// says not to spend much time on frontend polish, and these two chart
// shapes (a price/qty line, a cost bar comparison) are simple enough that
// a dependency isn't justified (Rule 9). Pure SVG, driven entirely by
// real backend data passed in as props.

export function LineChart({ points, width = 600, height = 220, yLabel, color = "#2451c9" }) {
  if (!points || points.length === 0) {
    return <div className="muted">No data to plot.</div>;
  }
  const pad = 36;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;

  const sx = (x) => pad + ((x - xMin) / xSpan) * (width - pad * 2);
  const sy = (y) => height - pad - ((y - yMin) / ySpan) * (height - pad * 2);

  const path = points.map((p, i) => `${i === 0 ? "M" : "L"} ${sx(p.x)} ${sy(p.y)}`).join(" ");

  return (
    <svg width={width} height={height} role="img" aria-label={yLabel || "line chart"}>
      <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="#e2e2e5" />
      <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="#e2e2e5" />
      <path d={path} fill="none" stroke={color} strokeWidth={2} />
      {points.map((p, i) => (
        <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={2.5} fill={color} />
      ))}
      <text x={pad} y={16} fontSize="11" fill="#6b6b73">{yLabel}</text>
      <text x={pad} y={height - pad + 14} fontSize="10" fill="#6b6b73">{xMin}</text>
      <text x={width - pad - 24} y={height - pad + 14} fontSize="10" fill="#6b6b73">{xMax}</text>
    </svg>
  );
}

export function BarChart({ bars, width = 600, height = 220, valueSuffix = "" }) {
  if (!bars || bars.length === 0) {
    return <div className="muted">No data to plot.</div>;
  }
  const pad = 40;
  const max = Math.max(...bars.map((b) => b.value), 0.0001);
  const barWidth = (width - pad * 2) / bars.length - 16;

  return (
    <svg width={width} height={height} role="img" aria-label="bar chart">
      <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="#e2e2e5" />
      {bars.map((b, i) => {
        const h = (b.value / max) * (height - pad * 2);
        const x = pad + i * ((width - pad * 2) / bars.length) + 8;
        const y = height - pad - h;
        return (
          <g key={b.label}>
            <rect x={x} y={y} width={barWidth} height={h} fill={b.color || "#2451c9"} rx={3} />
            <text x={x + barWidth / 2} y={height - pad + 14} fontSize="11" fill="#6b6b73" textAnchor="middle">
              {b.label}
            </text>
            <text x={x + barWidth / 2} y={y - 6} fontSize="11" fill="#1c1c1f" textAnchor="middle">
              {b.value.toFixed(2)}{valueSuffix}
            </text>
          </g>
        );
      })}
    </svg>
  );
}