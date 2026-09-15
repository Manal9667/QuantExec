import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { BarChart } from "../charts.jsx";

/**
 * Strategy comparison (spec section 22 / 34): pick a handful of experiments
 * the user already ran and compare them side by side. Deliberately does
 * NOT re-run anything or invent numbers - it only reads back what
 * /experiments/{id} already has stored, so the comparison is only as fair
 * as the experiments the user chose to hold constant (same dataset/window/
 * quantity/costs) when creating them. That responsibility is called out
 * in the UI rather than silently assumed.
 */
export default function Compare({ onOpenExperiment }) {
  const [experiments, setExperiments] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [details, setDetails] = useState({});
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listExperiments().then(setExperiments).catch((e) => setError(e.message));
  }, []);

  function toggle(id) {
    setSelectedIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  }

  useEffect(() => {
    selectedIds.forEach((id) => {
      if (!details[id]) {
        api.getExperiment(id).then((d) => setDetails((prev) => ({ ...prev, [id]: d })));
      }
    });
  }, [selectedIds]); // eslint-disable-line react-hooks/exhaustive-deps

  const selected = selectedIds.map((id) => details[id]).filter((d) => d && d.metrics);

  const datasets = new Set(selected.map((d) => d.dataset));
  const quantities = new Set(selected.map((d) => d.quantity));
  const sides = new Set(selected.map((d) => d.side));
  const notHeldConstant =
    selected.length > 1 && (datasets.size > 1 || quantities.size > 1 || sides.size > 1);

  const slippageBars = selected.map((d) => ({
    label: `#${d.id} ${d.strategy}`,
    value: d.metrics.slippage * 100,
  }));
  const costBars = selected.map((d) => ({
    label: `#${d.id} ${d.strategy}`,
    value: d.costs ? d.costs.total_cost_bps : 0,
    color: "#1a7f37",
  }));

  return (
    <div>
      <div className="panel">
        <strong>Select experiments to compare</strong>
        <p className="muted">
          The strongest use of this is holding dataset, side, quantity, execution window, and
          costs fixed, and only changing the strategy (spec section 22) - the goal is a
          reproducible comparison environment, not a claim that one strategy is universally
          better.
        </p>
        {error && <div className="error-text">{error}</div>}
        <table>
          <thead>
            <tr><th></th><th>ID</th><th>Symbol</th><th>Strategy</th><th>Side/Qty</th><th>Dataset</th></tr>
          </thead>
          <tbody>
            {experiments.filter((e) => e.status === "completed").map((e) => (
              <tr key={e.id} className="clickable" onClick={() => toggle(e.id)}>
                <td><input type="checkbox" checked={selectedIds.includes(e.id)} readOnly /></td>
                <td>{e.id}</td>
                <td>{e.symbol}</td>
                <td>{e.strategy}</td>
                <td>{e.side} {e.quantity}</td>
                <td className="muted">{e.dataset}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected.length > 0 && (
        <>
          {notHeldConstant && (
            <div className="panel">
              <p className="error-text" style={{ marginTop: 0 }}>
                These experiments differ in dataset, side, and/or quantity - this comparison is
                not apples-to-apples (spec section 22). Pick experiments that only differ by
                strategy for a fair comparison.
              </p>
            </div>
          )}

          <div className="panel">
            <strong>Slippage (%)</strong>
            <BarChart bars={slippageBars} valueSuffix="%" />
          </div>

          <div className="panel">
            <strong>Total cost (bps)</strong>
            <BarChart bars={costBars} valueSuffix=" bps" />
          </div>

          <div className="panel">
            <strong>Metrics</strong>
            <table>
              <thead>
                <tr>
                  <th>ID</th><th>Strategy</th><th>Fill rate</th><th>Avg price</th>
                  <th>Slippage</th><th>Impl. shortfall</th><th>Cost (bps)</th>
                </tr>
              </thead>
              <tbody>
                {selected.map((d) => (
                  <tr key={d.id} className="clickable" onClick={() => onOpenExperiment(d.id)}>
                    <td>{d.id}</td>
                    <td>{d.strategy}</td>
                    <td>{(d.metrics.fill_rate * 100).toFixed(1)}%</td>
                    <td>{d.metrics.average_execution_price.toFixed(4)}</td>
                    <td>{(d.metrics.slippage * 100).toFixed(3)}%</td>
                    <td>{d.metrics.implementation_shortfall.toFixed(2)}</td>
                    <td>{d.costs ? d.costs.total_cost_bps.toFixed(2) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}