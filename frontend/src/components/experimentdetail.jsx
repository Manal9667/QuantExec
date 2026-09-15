import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { LineChart, BarChart } from "../charts.jsx";

export default function ExperimentDetail({ experimentId, onBack }) {
  const [detail, setDetail] = useState(null);
  const [fills, setFills] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDetail(null);
    setFills(null);
    setError(null);
    Promise.all([api.getExperiment(experimentId), api.getFills(experimentId)])
      .then(([d, f]) => {
        setDetail(d);
        setFills(f);
      })
      .catch((e) => setError(e.message));
  }, [experimentId]);

  if (error) return <div className="panel error-text">{error}</div>;
  if (!detail) return <div className="panel muted">Loading...</div>;

  const m = detail.metrics;
  const c = detail.costs;
  const i = detail.impact;

  const priceSeries = (fills || []).map((f, idx) => ({ x: f.timestamp_ms, y: f.price }));
  const cumQtySeries = (() => {
    let running = 0;
    return (fills || []).map((f) => {
      running += f.qty;
      return { x: f.timestamp_ms, y: running };
    });
  })();

  const costBars = c
    ? [
        { label: "Commission", value: c.commission },
        { label: "Exch. fees", value: c.exchange_fees },
        { label: "Fixed fees", value: c.fixed_fees },
        { label: "Spread", value: c.spread_cost },
      ]
    : [];

  return (
    <div>
      <button onClick={onBack} style={{ marginBottom: 12, background: "none", border: "none", cursor: "pointer", color: "#2451c9" }}>
        ← Back to dashboard
      </button>

      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <strong>Experiment #{detail.id} — {detail.symbol} ({detail.strategy})</strong>
          <span className={`pill ${detail.status}`}>{detail.status}</span>
        </div>
        <p className="muted">
          {detail.side} {detail.quantity} shares · dataset: {detail.dataset} · created {detail.created_at}
        </p>
        {detail.error && <div className="error-text">Engine error: {detail.error}</div>}
      </div>

      {m && (
        <>
          <div className="stat-row">
            <div className="stat">
              <div className="label">Arrival price</div>
              <div className="value">{m.arrival_price.toFixed(4)}</div>
            </div>
            <div className="stat">
              <div className="label">Avg execution price</div>
              <div className="value">{m.average_execution_price.toFixed(4)}</div>
            </div>
            <div className="stat">
              <div className="label">Fill rate</div>
              <div className="value">{(m.fill_rate * 100).toFixed(1)}%</div>
            </div>
            <div className="stat">
              <div className="label">Slippage</div>
              <div className="value">{(m.slippage * 100).toFixed(3)}%</div>
            </div>
          </div>
          <div className="stat-row">
            <div className="stat">
              <div className="label">Market VWAP</div>
              <div className="value">{m.market_vwap.toFixed(4)}</div>
            </div>
            <div className="stat">
              <div className="label">VWAP deviation</div>
              <div className="value">{(m.vwap_deviation * 100).toFixed(3)}%</div>
            </div>
            <div className="stat">
              <div className="label">Impl. shortfall</div>
              <div className="value">{m.implementation_shortfall.toFixed(2)}</div>
            </div>
            <div className="stat">
              <div className="label">Market drift</div>
              <div className="value">{(m.market_price_drift * 100).toFixed(3)}%</div>
            </div>
          </div>

          <div className="panel">
            <strong>Execution price over time</strong>
            <p className="muted">Each point is one fill (from real replay, not interpolated).</p>
            <LineChart points={priceSeries} yLabel="fill price" />
          </div>

          <div className="panel">
            <strong>Cumulative executed quantity</strong>
            <LineChart points={cumQtySeries} yLabel="cumulative qty" color="#1a7f37" />
          </div>
        </>
      )}

      {c && (
        <div className="panel">
          <strong>Transaction costs</strong>
          <p className="muted">
            Total: {c.total_cost.toFixed(4)} ({c.total_cost_bps.toFixed(2)} bps)
          </p>
          <BarChart bars={costBars} />
        </div>
      )}

      {i && (
        <div className="panel">
          <strong>Estimated market impact</strong>
          <p className="muted">
            Educational, square-root participation model - see docs/PHASE2.md for the formula
            and its limitations. Not a measured cost.
          </p>
          <div className="stat-row">
            <div className="stat">
              <div className="label">Participation rate</div>
              <div className="value">{(i.participation_rate * 100).toFixed(2)}%</div>
            </div>
            <div className="stat">
              <div className="label">Impact (bps)</div>
              <div className="value">{i.impact_bps.toFixed(2)}</div>
            </div>
            <div className="stat">
              <div className="label">Impact cost</div>
              <div className="value">{i.impact_cost.toFixed(2)}</div>
            </div>
          </div>
        </div>
      )}

      {fills && fills.length > 0 && (
        <div className="panel">
          <strong>Fills ({fills.length})</strong>
          <table>
            <thead>
              <tr>
                <th>#</th><th>Timestamp (ms)</th><th>Price</th><th>Qty</th><th>Bid</th><th>Ask</th><th>Market vol</th>
              </tr>
            </thead>
            <tbody>
              {fills.map((f) => (
                <tr key={f.seq}>
                  <td>{f.seq}</td>
                  <td>{f.timestamp_ms}</td>
                  <td>{f.price.toFixed(4)}</td>
                  <td>{f.qty}</td>
                  <td>{f.bid.toFixed(4)}</td>
                  <td>{f.ask.toFixed(4)}</td>
                  <td>{f.market_volume}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}