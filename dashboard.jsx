import React, { useState } from "react";
import {
  ComposedChart, Area, Line, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, Legend, ReferenceLine,
} from "recharts";

/* ------------------------------------------------------------------------
   REAL DATA, pulled from the actual compiled C++ engine (pybind11) by
   running MarketSimulator + TWAPAlgorithm/VWAPAlgorithm + ExecutionSession
   with a fixed seed (synthetic) and a fixed CSV (historical). Nothing here
   is invented — these are the literal numbers those runs produced.
------------------------------------------------------------------------- */

const SYNTHETIC = {
  label: "Synthetic Market",
  sub: "MarketSimulator · seeded random walk · Phase 1",
  twap: {
    path: [
      { t: 0, mid: 182.1136, bid: 182.0686, ask: 182.1586 },
      { t: 1, mid: 181.7685, bid: 181.7235, ask: 181.8135 },
      { t: 2, mid: 181.9631, bid: 181.9181, ask: 182.0081 },
      { t: 3, mid: 182.2304, bid: 182.1854, ask: 182.2754 },
      { t: 4, mid: 182.2986, bid: 182.2536, ask: 182.3436 },
      { t: 5, mid: 181.8463, bid: 181.8013, ask: 181.8913 },
      { t: 6, mid: 181.7613, bid: 181.7163, ask: 181.8063 },
      { t: 7, mid: 181.5017, bid: 181.4567, ask: 181.5467 },
      { t: 8, mid: 181.5384, bid: 181.4934, ask: 181.5834 },
      { t: 9, mid: 181.5676, bid: 181.5226, ask: 181.6126 },
      { t: 10, mid: 181.7414, bid: 181.6964, ask: 181.7864 },
      { t: 11, mid: 181.6385, bid: 181.5935, ask: 181.6835 },
    ],
    fills: [500, 500, 500, 500, 500, 500, 500, 500, 500, 500, 500, 500],
    metrics: {
      requested: 6000, filled: 6000, fill_rate: 100.0,
      avg_exec_price: 181.8758, market_vwap: 181.7682, arrival_price: 182.4,
      slippage_pct: -0.2874, vwap_deviation_pct: 0.0592, shortfall: -3145.30,
      drift_pct: -0.2609, spread_cost_pct: 0.0247, exec_cost_pct: -0.3121,
    },
  },
  vwap: {
    path: null, // identical price path to TWAP (same seed) - reused below
    fills: [900, 661, 485, 352, 264, 264, 264, 264, 352, 485, 661, 900],
    metrics: {
      requested: 6000, filled: 5852, fill_rate: 97.53,
      avg_exec_price: 181.872, market_vwap: 181.7682, arrival_price: 182.4,
      slippage_pct: -0.2895, vwap_deviation_pct: 0.0571, shortfall: -3089.85,
      drift_pct: -0.2609, spread_cost_pct: 0.0247, exec_cost_pct: -0.3142,
    },
  },
};

const HISTORICAL = {
  label: "Historical Replay",
  sub: "CsvMarketSource · fixed dataset · Phase 3",
  path: [
    { t: 0, mid: 412.092, bid: 412.0655, ask: 412.1185 },
    { t: 1, mid: 412.153, bid: 412.1293, ask: 412.1767 },
    { t: 2, mid: 412.2613, bid: 412.2406, ask: 412.282 },
    { t: 3, mid: 412.2987, bid: 412.2781, ask: 412.3193 },
    { t: 4, mid: 412.1615, bid: 412.1357, ask: 412.1873 },
    { t: 5, mid: 412.0195, bid: 411.9991, ask: 412.04 },
    { t: 6, mid: 412.0623, bid: 412.0392, ask: 412.0854 },
    { t: 7, mid: 412.1128, bid: 412.0871, ask: 412.1385 },
    { t: 8, mid: 412.0968, bid: 412.0762, ask: 412.1174 },
    { t: 9, mid: 412.1023, bid: 412.0769, ask: 412.1276 },
    { t: 10, mid: 412.1929, bid: 412.1704, ask: 412.2153 },
    { t: 11, mid: 412.1684, bid: 412.1427, ask: 412.1941 },
    { t: 12, mid: 412.1738, bid: 412.144, ask: 412.2036 },
    { t: 13, mid: 412.1153, bid: 412.0936, ask: 412.1369 },
    { t: 14, mid: 411.9274, bid: 411.9066, ask: 411.9482 },
    { t: 15, mid: 412.0512, bid: 412.0252, ask: 412.0771 },
    { t: 16, mid: 412.1621, bid: 412.1354, ask: 412.1887 },
    { t: 17, mid: 412.1423, bid: 412.1165, ask: 412.1681 },
    { t: 18, mid: 412.2203, bid: 412.1909, ask: 412.2498 },
    { t: 19, mid: 412.1812, bid: 412.16, ask: 412.2024 },
    { t: 20, mid: 412.2429, bid: 412.219, ask: 412.2668 },
    { t: 21, mid: 412.3072, bid: 412.2827, ask: 412.3317 },
    { t: 22, mid: 412.37, bid: 412.3458, ask: 412.3941 },
    { t: 23, mid: 412.3301, bid: 412.3005, ask: 412.3596 },
  ],
  twap: {
    fills: [296, 419, 500, 500, 426, 500, 500, 299],
    metrics: {
      requested: 4000, filled: 3440, fill_rate: 86.0,
      avg_exec_price: 412.1726, market_vwap: 412.1636, arrival_price: 412.092,
      slippage_pct: 0.0196, vwap_deviation_pct: 0.0022, shortfall: 277.18,
      drift_pct: 0.0578, spread_cost_pct: 0.0064, exec_cost_pct: 0.0131,
    },
  },
  vwap: {
    fills: [296, 419, 520, 400, 360, 400, 400, 299],
    metrics: {
      requested: 4000, filled: 3094, fill_rate: 77.35,
      avg_exec_price: 412.1753, market_vwap: 412.1636, arrival_price: 412.092,
      slippage_pct: 0.0202, vwap_deviation_pct: 0.0028, shortfall: 257.82,
      drift_pct: 0.0578, spread_cost_pct: 0.0064, exec_cost_pct: 0.0138,
    },
  },
};

const ENVIRONMENTS = {
  synthetic: {
    key: "synthetic",
    name: "Synthetic",
    phase: "Phase 1",
    tagline: "A seeded random-walk market for controlled, repeatable testing.",
    kind: "data",
    data: SYNTHETIC,
  },
  historical: {
    key: "historical",
    name: "Historical",
    phase: "Phase 3",
    tagline: "Chronological CSV replay with no lookahead, for reproducible backtests.",
    kind: "data",
    data: HISTORICAL,
  },
  live: {
    key: "live",
    name: "Real-Time",
    phase: "Phase 2",
    tagline: "Live NBBO from Alpaca's IEX feed, adapted into the same MarketState.",
    kind: "live",
  },
};

function fmt(n, digits = 4) {
  return Number(n).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function pct(n, digits = 4) {
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}
function money(n) {
  const sign = n >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function ChartPanel({ env, strategy }) {
  const dataset = env.data;
  const fallbackPath = dataset.twap.path || dataset.path;
  const path = strategy === "twap" ? (dataset.twap.path || dataset.path) : (dataset.vwap.path || fallbackPath);
  const fills = dataset[strategy].fills;
  const chartData = path.map((row, i) => ({
    ...row,
    fillQty: i < fills.length ? fills[i] : null,
    fillPrice: i < fills.length ? row.ask : null,
  }));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart data={chartData} margin={{ top: 10, right: 18, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="bandFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2F6FED" stopOpacity={0.16} />
            <stop offset="100%" stopColor="#2F6FED" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#E4EAF3" vertical={false} />
        <XAxis type="number" dataKey="t" domain={[0, "dataMax"]} tick={{ fill: "#7488A8", fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }}
               axisLine={{ stroke: "#D8E2F0" }} tickLine={false} label={{ value: "tick", position: "insideBottomRight", fill: "#9FB0C9", fontSize: 10, dy: 10 }} />
        <YAxis domain={["auto", "auto"]} tick={{ fill: "#7488A8", fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }}
               axisLine={false} tickLine={false} width={64} tickFormatter={(v) => v.toFixed(2)} />
        <Tooltip
          contentStyle={{ background: "#0A1F3D", border: "none", borderRadius: 4, fontFamily: "IBM Plex Mono, monospace", fontSize: 12 }}
          labelStyle={{ color: "#9FB0C9" }}
          itemStyle={{ color: "#EAF1FF" }}
          formatter={(v, name) => [typeof v === "number" ? v.toFixed(4) : v, name]}
        />
        <Area type="monotone" dataKey="ask" stroke="none" fill="url(#bandFill)" isAnimationActive={false} />
        <Line type="monotone" dataKey="bid" stroke="#AFC6E8" strokeWidth={1} dot={false} isAnimationActive={false} name="bid" />
        <Line type="monotone" dataKey="ask" stroke="#AFC6E8" strokeWidth={1} dot={false} isAnimationActive={false} name="ask" />
        <Line type="monotone" dataKey="mid" stroke="#1D4ED8" strokeWidth={2.25} dot={false} isAnimationActive={false} name="mid" />
        <Scatter dataKey="fillPrice" fill="#0A1F3D" shape="circle" isAnimationActive={false} name="fill" />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function MetricCard({ label, value, sub, tone }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${tone || ""}`}>{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

function ImpactBars({ m }) {
  const rows = [
    { label: "market drift", value: m.drift_pct, note: "total market movement over the window" },
    { label: "spread cost", value: m.spread_cost_pct, note: "cost of crossing the book once" },
    { label: "residual", value: m.exec_cost_pct, note: "slippage minus spread cost - not a clean causal split" },
  ];
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 0.05);
  return (
    <div className="impact">
      {rows.map((r) => (
        <div className="impact-row" key={r.label}>
          <div className="impact-label">{r.label}</div>
          <div className="impact-track">
            <div
              className={`impact-fill ${r.value < 0 ? "neg" : "pos"}`}
              style={{ width: `${(Math.abs(r.value) / max) * 100}%`, marginLeft: r.value < 0 ? "auto" : 0 }}
            />
          </div>
          <div className="impact-value">{pct(r.value)}</div>
        </div>
      ))}
      <div className="impact-caveat">Heuristic decomposition, not a causal estimate — see execution.h.</div>
    </div>
  );
}

function ComparisonChart() {
  const data = [
    { name: "Synth. slippage", TWAP: SYNTHETIC.twap.metrics.slippage_pct, VWAP: SYNTHETIC.vwap.metrics.slippage_pct },
    { name: "Synth. fill rate", TWAP: SYNTHETIC.twap.metrics.fill_rate, VWAP: SYNTHETIC.vwap.metrics.fill_rate },
    { name: "Hist. slippage", TWAP: HISTORICAL.twap.metrics.slippage_pct, VWAP: HISTORICAL.vwap.metrics.slippage_pct },
    { name: "Hist. fill rate", TWAP: HISTORICAL.twap.metrics.fill_rate, VWAP: HISTORICAL.vwap.metrics.fill_rate },
  ];
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }} barGap={6}>
        <CartesianGrid stroke="#E4EAF3" vertical={false} />
        <XAxis dataKey="name" tick={{ fill: "#55698A", fontSize: 11.5 }} axisLine={{ stroke: "#D8E2F0" }} tickLine={false} interval={0} />
        <YAxis tick={{ fill: "#7488A8", fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }} axisLine={false} tickLine={false} width={40} />
        <Tooltip
          contentStyle={{ background: "#0A1F3D", border: "none", borderRadius: 4, fontFamily: "IBM Plex Mono, monospace", fontSize: 12 }}
          labelStyle={{ color: "#9FB0C9" }} itemStyle={{ color: "#EAF1FF" }}
        />
        <Legend wrapperStyle={{ fontSize: 12.5, fontFamily: "Inter, sans-serif" }} />
        <ReferenceLine y={0} stroke="#C7D4E8" />
        <Bar dataKey="TWAP" fill="#AFC6E8" radius={[2, 2, 0, 0]} />
        <Bar dataKey="VWAP" fill="#1D4ED8" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function ExecutionEngineDashboard() {
  const [envKey, setEnvKey] = useState("synthetic");
  const [strategy, setStrategy] = useState("twap");
  const env = ENVIRONMENTS[envKey];
  const metrics = env.kind === "data" ? env.data[strategy].metrics : null;

  const heroPath = SYNTHETIC.twap.path;

  return (
    <div className="app">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,380..600&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

        :root{
          --paper:#F5F8FC; --white:#ffffff; --ink:#0A1F3D; --navy-deep:#071427;
          --blue:#1D4ED8; --blue-mid:#2F6FED; --sky:#AFC6E8; --sky-pale:#E7EFFB;
          --line:#DCE5F1; --slate:#55698A; --slate-light:#8598B8;
        }
        *{box-sizing:border-box;}
        .app{
          background:var(--paper); color:var(--ink); min-height:100vh;
          font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
          line-height:1.5;
        }
        .wrap{max-width:1160px; margin:0 auto; padding:0 28px;}

        /* ---- status strip ---- */
        .status-strip{
          background:var(--navy-deep); color:#B9CBE8; font-family:'IBM Plex Mono',monospace;
          font-size:12px; letter-spacing:0.02em; padding:9px 0; overflow:hidden;
        }
        .status-row{display:flex; align-items:center; gap:22px; flex-wrap:wrap;}
        .status-item{display:flex; align-items:center; gap:8px; white-space:nowrap;}
        .status-dot{width:6px; height:6px; border-radius:50%; background:#4ADE80; box-shadow:0 0 0 3px rgba(74,222,128,0.18);}
        .status-div{width:1px; height:12px; background:#2A3E5C;}

        /* ---- hero ---- */
        .hero{padding:64px 0 48px; border-bottom:1px solid var(--line);}
        .hero-grid{display:grid; grid-template-columns:1.15fr 0.85fr; gap:56px; align-items:center;}
        .eyebrow-line{display:flex; align-items:center; gap:10px; margin-bottom:18px;}
        .eyebrow-line .bar{width:28px; height:2px; background:var(--blue);}
        .eyebrow-line span{font-size:13px; color:var(--slate); font-weight:500;}
        h1{
          font-family:'Fraunces',Georgia,serif; font-weight:480; font-size:44px;
          line-height:1.12; letter-spacing:-0.01em; margin:0 0 20px; max-width:560px;
        }
        h1 em{font-style:italic; color:var(--blue);}
        .hero-desc{font-size:16.5px; color:var(--slate); max-width:480px; margin:0 0 30px;}
        .hero-stats{display:flex; gap:36px; flex-wrap:wrap;}
        .hero-stat .num{font-family:'IBM Plex Mono',monospace; font-size:26px; font-weight:500; color:var(--ink);}
        .hero-stat .cap{font-size:12.5px; color:var(--slate-light); margin-top:2px;}
        .hero-chart-card{
          background:var(--white); border:1px solid var(--line); border-radius:6px;
          padding:20px 20px 8px;
        }
        .hero-chart-label{font-size:12px; color:var(--slate); font-family:'IBM Plex Mono',monospace; margin-bottom:6px; display:flex; justify-content:space-between;}

        /* ---- section shell ---- */
        section{padding:56px 0;}
        section.tight{padding:44px 0;}
        .section-head{display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:28px; gap:24px; flex-wrap:wrap;}
        .section-head h2{font-family:'Fraunces',Georgia,serif; font-weight:480; font-size:28px; margin:0;}
        .section-head p{color:var(--slate); font-size:14.5px; margin:6px 0 0; max-width:480px;}

        /* ---- architecture ---- */
        .arch-band{background:var(--navy-deep); color:#EAF1FF;}
        .arch-band .section-head h2, .arch-band .section-head p{color:#EAF1FF;}
        .arch-band .section-head p{color:#9FB0C9;}
        .arch-row{display:flex; align-items:center; gap:0; overflow-x:auto; padding-bottom:8px;}
        .arch-node{
          flex:0 0 auto; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.14);
          border-radius:5px; padding:16px 18px; min-width:150px;
        }
        .arch-node .k{font-size:11px; color:#7C93BC; font-family:'IBM Plex Mono',monospace; margin-bottom:4px;}
        .arch-node .v{font-size:14.5px; font-weight:500;}
        .arch-arrow{flex:0 0 auto; padding:0 14px; color:#4E6690; font-size:18px;}
        .arch-note{margin-top:18px; font-size:13.5px; color:#8FA5CB; max-width:640px;}

        /* ---- tabs ---- */
        .tabs{display:flex; gap:6px; border-bottom:1px solid var(--line); margin-bottom:26px;}
        .tab{
          padding:10px 4px; margin-right:26px; background:none; border:none; cursor:pointer;
          font-family:'Inter',sans-serif; font-size:14.5px; font-weight:500; color:var(--slate-light);
          border-bottom:2px solid transparent; position:relative; top:1px;
        }
        .tab.active{color:var(--ink); border-bottom-color:var(--blue);}
        .tab .ph{font-size:11px; color:var(--slate-light); font-weight:400; margin-left:6px;}

        .explorer-grid{display:grid; grid-template-columns:1fr 300px; gap:24px; align-items:start;}
        .card{background:var(--white); border:1px solid var(--line); border-radius:6px; padding:22px;}
        .env-tagline{font-size:13.5px; color:var(--slate); margin:0 0 16px;}

        .strategy-toggle{display:inline-flex; border:1px solid var(--line); border-radius:5px; overflow:hidden; margin-bottom:16px;}
        .strategy-toggle button{
          padding:7px 16px; font-family:'IBM Plex Mono',monospace; font-size:12.5px; border:none;
          background:var(--white); color:var(--slate); cursor:pointer;
        }
        .strategy-toggle button.active{background:var(--blue); color:#fff;}

        .metrics-col{display:flex; flex-direction:column; gap:12px;}
        .metric-card{border:1px solid var(--line); border-radius:5px; padding:12px 14px; background:var(--sky-pale);}
        .metric-label{font-size:11px; color:var(--slate); text-transform:lowercase;}
        .metric-value{font-family:'IBM Plex Mono',monospace; font-size:18px; font-weight:500; margin-top:2px;}
        .metric-value.neg{color:#1D4ED8;}
        .metric-sub{font-size:11px; color:var(--slate-light); margin-top:1px;}

        .impact{margin-top:18px; border-top:1px solid var(--line); padding-top:16px;}
        .impact-row{display:grid; grid-template-columns:80px 1fr 64px; align-items:center; gap:10px; margin-bottom:9px;}
        .impact-label{font-size:11.5px; color:var(--slate);}
        .impact-track{height:6px; background:var(--sky-pale); border-radius:3px; position:relative; overflow:hidden;}
        .impact-fill{height:100%; border-radius:3px;}
        .impact-fill.pos{background:var(--blue-mid);}
        .impact-fill.neg{background:var(--sky);}
        .impact-value{font-family:'IBM Plex Mono',monospace; font-size:11.5px; text-align:right; color:var(--ink);}
        .impact-caveat{font-size:11px; color:var(--slate-light); margin-top:4px;}

        .live-card{
          background:linear-gradient(180deg, var(--navy-deep), #0D2748); color:#EAF1FF;
          border-radius:6px; padding:32px; display:grid; grid-template-columns:1fr 1fr; gap:36px; align-items:center;
        }
        .live-card h3{font-family:'Fraunces',Georgia,serif; font-weight:480; font-size:22px; margin:0 0 10px;}
        .live-card p{color:#9FB0C9; font-size:14px; margin:0 0 14px; max-width:420px;}
        .live-badge{display:inline-flex; align-items:center; gap:7px; font-size:12px; color:#F4C77A; font-family:'IBM Plex Mono',monospace; margin-bottom:14px;}
        .live-badge .dot{width:6px; height:6px; border-radius:50%; background:#F4C77A;}
        .code-block{
          background:#050E1F; border:1px solid rgba(255,255,255,0.1); border-radius:5px;
          padding:16px 18px; font-family:'IBM Plex Mono',monospace; font-size:12.5px; color:#B9CBE8;
          overflow-x:auto; line-height:1.7;
        }
        .code-block .c1{color:#7C93BC;}
        .code-block .c2{color:#8FD6FF;}
        .code-block .c3{color:#F4C77A;}

        /* ---- reliability strip ---- */
        .rel-grid{display:grid; grid-template-columns:repeat(4,1fr); gap:20px;}
        .rel-card{border:1px solid var(--line); border-radius:6px; padding:20px; background:var(--white);}
        .rel-num{font-family:'IBM Plex Mono',monospace; font-size:28px; color:var(--blue); font-weight:500;}
        .rel-label{font-size:13px; color:var(--slate); margin-top:4px;}

        .chip-row{display:flex; flex-wrap:wrap; gap:8px; margin-top:24px;}
        .chip{
          font-family:'IBM Plex Mono',monospace; font-size:12px; padding:6px 11px;
          border:1px solid var(--line); border-radius:20px; color:var(--slate); background:var(--white);
        }

        footer{border-top:1px solid var(--line); padding:28px 0 40px;}
        footer p{font-size:13px; color:var(--slate-light); margin:0;}

        @media (max-width:860px){
          .hero-grid{grid-template-columns:1fr;}
          h1{font-size:34px;}
          .explorer-grid{grid-template-columns:1fr;}
          .rel-grid{grid-template-columns:1fr 1fr;}
          .live-card{grid-template-columns:1fr;}
          .arch-row{flex-wrap:nowrap;}
        }

        @keyframes riseIn{from{opacity:0; transform:translateY(10px);} to{opacity:1; transform:translateY(0);}}
        .rise{animation:riseIn 0.6s ease both;}
        .rise-2{animation:riseIn 0.6s 0.1s ease both;}
        .rise-3{animation:riseIn 0.6s 0.2s ease both;}
      `}</style>

      {/* status strip */}
      <div className="status-strip">
        <div className="wrap status-row">
          <div className="status-item"><span className="status-dot" /> ENGINE ONLINE</div>
          <div className="status-div" />
          <div className="status-item">6 / 6 C++ TEST SUITES PASSING</div>
          <div className="status-div" />
          <div className="status-item">C++17 · pybind11 · CMake</div>
          <div className="status-div" />
          <div className="status-item">SYNTHETIC · REAL-TIME · HISTORICAL</div>
        </div>
      </div>

      {/* hero */}
      <div className="wrap">
        <section className="hero">
          <div className="hero-grid">
            <div className="rise">
              <div className="eyebrow-line"><div className="bar" /><span>Execution engine</span></div>
              <h1>One matching engine, <em>three market realities</em>, and TWAP/VWAP that never change between them.</h1>
              <p className="hero-desc">
                A C++ order book and execution engine that runs the same TWAP and VWAP
                strategies against a synthetic market, live Alpaca quotes, and historical
                replay — and measures how each one actually performed.
              </p>
              <div className="hero-stats">
                <div className="hero-stat"><div className="num">6,000 / 6,000</div><div className="cap">shares filled, synthetic TWAP</div></div>
                <div className="hero-stat"><div className="num">-0.29%</div><div className="cap">slippage vs. arrival price</div></div>
                <div className="hero-stat"><div className="num">6 / 6</div><div className="cap">test suites passing</div></div>
              </div>
            </div>
            <div className="hero-chart-card rise-2">
              <div className="hero-chart-label"><span>AAPL-shaped synthetic mid, 12 ticks</span><span>seed 1337</span></div>
              <ResponsiveContainer width="100%" height={190}>
                <ComposedChart data={heroPath} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
                  <YAxis hide domain={["auto", "auto"]} />
                  <XAxis hide dataKey="t" />
                  <Line type="monotone" dataKey="mid" stroke="#1D4ED8" strokeWidth={2} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>
      </div>

      {/* architecture */}
      <div className="arch-band">
        <div className="wrap">
          <section className="tight">
            <div className="section-head">
              <div>
                <h2>One engine. Three markets.</h2>
                <p>Synthetic and real sources feed the same order book, matching engine, and strategy classes — nothing downstream knows which market it's looking at.</p>
              </div>
            </div>
            <div className="arch-row">
              <div className="arch-node"><div className="k">01</div><div className="v">Synthetic / Real / Historical</div></div>
              <div className="arch-arrow">→</div>
              <div className="arch-node"><div className="k">02</div><div className="v">Market Data Adapter</div></div>
              <div className="arch-arrow">→</div>
              <div className="arch-node"><div className="k">03</div><div className="v">MarketState</div></div>
              <div className="arch-arrow">→</div>
              <div className="arch-node"><div className="k">04</div><div className="v">Order Book</div></div>
              <div className="arch-arrow">→</div>
              <div className="arch-node"><div className="k">05</div><div className="v">Matching Engine</div></div>
              <div className="arch-arrow">→</div>
              <div className="arch-node"><div className="k">06</div><div className="v">TWAP / VWAP</div></div>
              <div className="arch-arrow">→</div>
              <div className="arch-node"><div className="k">07</div><div className="v">Execution Analytics</div></div>
            </div>
            <p className="arch-note">
              The Alpaca adapter and the CSV replay adapter both produce the identical
              MarketState struct — TWAPAlgorithm and VWAPAlgorithm are the same compiled
              C++ classes in every environment, exposed to Python once via pybind11.
            </p>
          </section>
        </div>
      </div>

      {/* explorer */}
      <div className="wrap">
        <section>
          <div className="section-head">
            <div>
              <h2>Run the strategies yourself</h2>
              <p>Real output from the engine — pick an environment and a strategy to see how the fills, slippage, and market-impact breakdown change.</p>
            </div>
          </div>

          <div className="tabs">
            {Object.values(ENVIRONMENTS).map((e) => (
              <button key={e.key} className={`tab ${envKey === e.key ? "active" : ""}`} onClick={() => setEnvKey(e.key)}>
                {e.name}<span className="ph">{e.phase}</span>
              </button>
            ))}
          </div>

          {env.kind === "data" ? (
            <div className="explorer-grid">
              <div className="card">
                <p className="env-tagline">{env.tagline}</p>
                <div className="strategy-toggle">
                  <button className={strategy === "twap" ? "active" : ""} onClick={() => setStrategy("twap")}>TWAP</button>
                  <button className={strategy === "vwap" ? "active" : ""} onClick={() => setStrategy("vwap")}>VWAP</button>
                </div>
                <ChartPanel env={env} strategy={strategy} />
              </div>
              <div>
                <div className="metrics-col">
                  <MetricCard label="filled / requested" value={`${metrics.filled.toLocaleString()} / ${metrics.requested.toLocaleString()}`} sub={`${metrics.fill_rate.toFixed(2)}% fill rate`} />
                  <MetricCard label="avg execution price" value={fmt(metrics.avg_exec_price)} sub={`arrival ${fmt(metrics.arrival_price)}`} />
                  <MetricCard label="market vwap" value={fmt(metrics.market_vwap)} sub={`deviation ${pct(metrics.vwap_deviation_pct)}`} />
                  <MetricCard label="slippage" value={pct(metrics.slippage_pct)} tone="neg" sub={money(metrics.shortfall) + " shortfall"} />
                </div>
                <ImpactBars m={metrics} />
              </div>
            </div>
          ) : (
            <div className="live-card">
              <div>
                <div className="live-badge"><span className="dot" /> AWAITING CREDENTIALS</div>
                <h3>Connect your Alpaca keys to trade this live.</h3>
                <p>
                  The real-market adapter converts Alpaca's IEX snapshot (bid, ask, sizes,
                  minute volume) into the same MarketState the synthetic and historical
                  sources produce — TWAP and VWAP don't need to know the difference.
                </p>
                <p style={{ fontSize: 12.5, color: "#7C93BC" }}>
                  export ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY, then run
                  run_phase2_live.py — no code changes needed above the adapter.
                </p>
              </div>
              <div className="code-block">
                <div><span className="c1">$</span> python3 run_phase2_live.py <span className="c2">AAPL</span> --qty <span className="c3">500</span> --algo <span className="c3">twap</span></div>
                <div style={{ marginTop: 10 }}><span className="c1">TWAP split 500 shares into 5 slices: [100, 100, 100, 100, 100]</span></div>
                <div><span className="c1">--- Execution Result (Phase 2: real market) ---</span></div>
                <div><span className="c1">Fill rate:</span> <span className="c2">—</span>&nbsp;&nbsp;<span className="c1">Slippage:</span> <span className="c2">—</span></div>
              </div>
            </div>
          )}
        </section>

        {/* comparison */}
        <section className="tight">
          <div className="section-head">
            <div>
              <h2>TWAP vs. VWAP, same conditions</h2>
              <p>Every strategy replays the identical market data — the only variable is how the parent order gets sliced.</p>
            </div>
          </div>
          <div className="card">
            <ComparisonChart />
          </div>
        </section>

        {/* reliability */}
        <section className="tight">
          <div className="section-head">
            <div>
              <h2>Built to be trusted, not just to run</h2>
              <p>Every phase shipped with regression tests and reproducibility checks — not added after the fact.</p>
            </div>
          </div>
          <div className="rel-grid">
            <div className="rel-card"><div className="rel-num">6 / 6</div><div className="rel-label">C++ test suites (book, engine, simulator, algorithms, integration, phases)</div></div>
            <div className="rel-card"><div className="rel-num">8</div><div className="rel-label">offline Python tests for the Alpaca adapters — zero network calls, zero flakiness</div></div>
            <div className="rel-card"><div className="rel-num">0</div><div className="rel-label">duplicated TWAP/VWAP logic — one C++ implementation, shared across all three phases</div></div>
            <div className="rel-card"><div className="rel-num">2×</div><div className="rel-label">identical results verified across independent replays of the same dataset</div></div>
          </div>
          <div className="chip-row">
            {["C++17", "pybind11", "CMake", "Python 3", "Alpaca Market Data API", "CTest", "Order Book", "TWAP", "VWAP"].map((c) => (
              <div className="chip" key={c}>{c}</div>
            ))}
          </div>
        </section>
      </div>

      <footer>
        <div className="wrap">
          <p>Execution engine — synthetic, real-time, and historical markets on one codebase. Built as a personal project.</p>
        </div>
      </footer>
    </div>
  );
}