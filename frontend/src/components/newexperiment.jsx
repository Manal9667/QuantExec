import React, { useEffect, useState } from "react";
import { api } from "../api.js";

const DEFAULTS = {
  symbol: "SYN",
  dataset: "datasets/sample_synthetic.csv",
  side: "BUY",
  quantity: 1000,
  strategy: "TWAP",
  slices: 6,
  participation_rate: 0.1,
  min_order_qty: 1,
  max_order_qty: 0,
  latency_ms: 0,
  // Optional benchmark/limit overrides. Blank = let the backend auto-derive
  // from the dataset's first tick (arrival = first mid, limit = first ask*1.02).
  arrival_price: "",
  limit_price: "",
  // VWAP-only: comma-separated volume weights (e.g. "0.4,0.3,0.2,0.1"). Blank =
  // backend uses a uniform profile.
  volume_profile: "",
  commission_bps: 0.5,
  exchange_fee_bps: 0.1,
  fixed_fee_per_fill: 0,
  impact_enabled: false,
  impact_eta: 0.1,
};

export default function NewExperiment({ onCreated }) {
  const [strategies, setStrategies] = useState([]);
  const [form, setForm] = useState(DEFAULTS);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listStrategies().then(setStrategies).catch(() => {});
  }, []);

  const set = (key) => (e) => {
    const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [key]: value }));
  };

  async function submit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const payload = {
      symbol: form.symbol,
      dataset: form.dataset,
      side: form.side,
      quantity: Number(form.quantity),
      strategy: form.strategy,
      costs: {
        commission_bps: Number(form.commission_bps),
        exchange_fee_bps: Number(form.exchange_fee_bps),
        fixed_fee_per_fill: Number(form.fixed_fee_per_fill),
      },
      impact: { enabled: !!form.impact_enabled, eta: Number(form.impact_eta) },
    };
    if (form.strategy === "TWAP" || form.strategy === "VWAP") {
      payload.slices = Number(form.slices);
      payload.latency_ms = Number(form.latency_ms);
    }
    if (form.strategy === "VWAP" && String(form.volume_profile).trim() !== "") {
      // "0.4, 0.3, 0.2, 0.1" -> [0.4, 0.3, 0.2, 0.1]; the backend normalizes.
      const weights = String(form.volume_profile)
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s !== "")
        .map(Number);
      if (weights.some((w) => Number.isNaN(w))) {
        setSubmitting(false);
        setError("Volume profile must be a comma-separated list of numbers.");
        return;
      }
      payload.volume_profile = weights;
    }
    if (form.strategy === "POV") {
      payload.participation_rate = Number(form.participation_rate);
      payload.min_order_qty = Number(form.min_order_qty);
      payload.max_order_qty = Number(form.max_order_qty);
    }

    // Optional benchmark/limit overrides: send only when the user set them,
    // so a blank field leaves the backend's auto-derivation in place.
    if (String(form.arrival_price).trim() !== "") payload.arrival_price = Number(form.arrival_price);
    if (String(form.limit_price).trim() !== "") payload.limit_price = Number(form.limit_price);

    try {
      const created = await api.createExperiment(payload);
      onCreated(created.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="panel">
      <strong>New experiment</strong>
      <p className="muted">
        Runs the real C++ execution engine against the dataset below. Nothing here is simulated
        in the browser - the numbers you'll see next come back from the backend.
      </p>
      <form onSubmit={submit}>
        <div className="form-grid">
          <label>Symbol
            <input value={form.symbol} onChange={set("symbol")} required />
          </label>
          <label>Dataset (path)
            <input value={form.dataset} onChange={set("dataset")} required />
          </label>
          <label>Side
            <select value={form.side} onChange={set("side")}>
              <option value="BUY">BUY</option>
              <option value="SELL">SELL</option>
            </select>
          </label>
          <label>Quantity
            <input type="number" min="1" value={form.quantity} onChange={set("quantity")} required />
          </label>
          <label>Strategy
            <select value={form.strategy} onChange={set("strategy")}>
              <option value="TWAP">TWAP</option>
              <option value="VWAP">VWAP</option>
              <option value="POV">POV</option>
            </select>
          </label>

          {(form.strategy === "TWAP" || form.strategy === "VWAP") && (
            <>
              <label>Slices
                <input type="number" min="1" value={form.slices} onChange={set("slices")} required />
              </label>
              <label>Latency (ms, 0 = off)
                <input type="number" min="0" value={form.latency_ms} onChange={set("latency_ms")} />
              </label>
            </>
          )}

          {form.strategy === "VWAP" && (
            <label>Volume profile (optional, comma-separated weights)
              <input placeholder="e.g. 0.4, 0.3, 0.2, 0.1" value={form.volume_profile}
                     onChange={set("volume_profile")} />
            </label>
          )}

          {form.strategy === "POV" && (
            <>
              <label>Participation rate (0-1)
                <input type="number" step="0.01" min="0.01" max="1" value={form.participation_rate}
                       onChange={set("participation_rate")} required />
              </label>
              <label>Min order qty
                <input type="number" min="0" value={form.min_order_qty} onChange={set("min_order_qty")} />
              </label>
              <label>Max order qty (0 = unbounded)
                <input type="number" min="0" value={form.max_order_qty} onChange={set("max_order_qty")} />
              </label>
            </>
          )}

          <label>Commission (bps)
            <input type="number" step="0.1" value={form.commission_bps} onChange={set("commission_bps")} />
          </label>
          <label>Exchange fee (bps)
            <input type="number" step="0.1" value={form.exchange_fee_bps} onChange={set("exchange_fee_bps")} />
          </label>
          <label>Fixed fee per fill
            <input type="number" step="0.01" value={form.fixed_fee_per_fill} onChange={set("fixed_fee_per_fill")} />
          </label>
          <label>Arrival price (optional, blank = auto)
            <input type="number" step="0.01" placeholder="auto: first mid" value={form.arrival_price}
                   onChange={set("arrival_price")} />
          </label>
          <label>Limit price (optional, blank = auto)
            <input type="number" step="0.01" placeholder="auto: first ask ×1.02" value={form.limit_price}
                   onChange={set("limit_price")} />
          </label>
          <label>
            <span>
              <input type="checkbox" checked={form.impact_enabled} onChange={set("impact_enabled")}
                     style={{ marginRight: 6 }} />
              Estimate market impact (educational, see docs/PHASE2.md)
            </span>
          </label>
          {form.impact_enabled && (
            <label>Impact eta
              <input type="number" step="0.01" value={form.impact_eta} onChange={set("impact_eta")} />
            </label>
          )}
        </div>

        {strategies.length > 0 && (
          <p className="muted" style={{ marginTop: 12 }}>
            {strategies.find((s) => s.name === form.strategy)?.description}
          </p>
        )}

        {error && <div className="error-text">{error}</div>}

        <button className="primary" type="submit" disabled={submitting}>
          {submitting ? "Running..." : "Run experiment"}
        </button>
      </form>
    </div>
  );
}