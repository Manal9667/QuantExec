import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Dashboard({ onOpenExperiment, onNewExperiment }) {
  const [experiments, setExperiments] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listExperiments().then(setExperiments).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="panel error-text">Failed to load experiments: {error}</div>;
  if (!experiments) return <div className="panel muted">Loading...</div>;

  const completed = experiments.filter((e) => e.status === "completed");
  const avgFillRate =
    completed.length > 0
      ? completed.reduce((sum, e) => sum + (e.fill_rate ?? 0), 0) / completed.length
      : null;
  const avgCostBps =
    completed.filter((e) => e.total_cost_bps != null).length > 0
      ? completed.reduce((sum, e) => sum + (e.total_cost_bps ?? 0), 0) /
        completed.filter((e) => e.total_cost_bps != null).length
      : null;

  return (
    <div>
      <div className="stat-row">
        <div className="stat">
          <div className="label">Experiments</div>
          <div className="value">{experiments.length}</div>
        </div>
        <div className="stat">
          <div className="label">Completed</div>
          <div className="value">{completed.length}</div>
        </div>
        <div className="stat">
          <div className="label">Avg fill rate</div>
          <div className="value">{avgFillRate != null ? `${(avgFillRate * 100).toFixed(1)}%` : "—"}</div>
        </div>
        <div className="stat">
          <div className="label">Avg cost (bps)</div>
          <div className="value">{avgCostBps != null ? avgCostBps.toFixed(2) : "—"}</div>
        </div>
      </div>

      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <strong>Recent experiments</strong>
          <button className="primary" style={{ marginTop: 0 }} onClick={onNewExperiment}>
            + New experiment
          </button>
        </div>
        {experiments.length === 0 ? (
          <div className="muted">
            No experiments yet. Run one from "New experiment", or via the CLI:{" "}
            <code>python3 python/run_experiment.py configs/example_experiment.yaml</code>
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Symbol</th>
                <th>Strategy</th>
                <th>Side / Qty</th>
                <th>Fill rate</th>
                <th>Avg exec price</th>
                <th>Slippage</th>
                <th>Cost (bps)</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {experiments.map((e) => (
                <tr key={e.id} className="clickable" onClick={() => onOpenExperiment(e.id)}>
                  <td>{e.id}</td>
                  <td>{e.symbol}</td>
                  <td>{e.strategy}</td>
                  <td>{e.side} {e.quantity}</td>
                  <td>{e.fill_rate != null ? `${(e.fill_rate * 100).toFixed(1)}%` : "—"}</td>
                  <td>{e.average_execution_price != null ? e.average_execution_price.toFixed(4) : "—"}</td>
                  <td>{e.slippage != null ? `${(e.slippage * 100).toFixed(3)}%` : "—"}</td>
                  <td>{e.total_cost_bps != null ? e.total_cost_bps.toFixed(2) : "—"}</td>
                  <td><span className={`pill ${e.status}`}>{e.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}