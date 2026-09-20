// Smoke / interaction test for the primary dashboard workflow: configuring
// and submitting an experiment (spec section 38). Confirms the form talks to
// the backend API wrapper with a correctly shaped payload and reacts to the
// response - the frontend never computes results itself, so "does it call the
// API correctly and render what comes back" is exactly what matters here.
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

import NewExperiment from "./newexperiment.jsx";
import { api } from "../api.js";

// Mock the API wrapper so the test never touches a real backend.
vi.mock("../api.js", () => ({
  api: {
    listStrategies: vi.fn(),
    createExperiment: vi.fn(),
  },
}));

describe("NewExperiment", () => {
  beforeEach(() => {
    api.listStrategies.mockResolvedValue([
      { name: "TWAP", description: "Time-weighted", required_fields: [], optional_fields: [] },
      { name: "POV", description: "Percent of volume", required_fields: [], optional_fields: [] },
    ]);
    api.createExperiment.mockResolvedValue({ id: 42 });
  });

  it("loads the strategy list from the backend on mount", async () => {
    render(<NewExperiment onCreated={() => {}} />);
    await waitFor(() => expect(api.listStrategies).toHaveBeenCalledTimes(1));
    // The selected strategy's description is rendered once strategies load.
    expect(await screen.findByText("Time-weighted")).toBeInTheDocument();
  });

  it("submits a correctly shaped payload and reports the created id", async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    render(<NewExperiment onCreated={onCreated} />);

    await user.click(screen.getByRole("button", { name: /run experiment/i }));

    await waitFor(() => expect(api.createExperiment).toHaveBeenCalledTimes(1));
    const payload = api.createExperiment.mock.calls[0][0];
    // Core parent-order fields.
    expect(payload).toMatchObject({
      symbol: "SYN",
      dataset: "datasets/sample_synthetic.csv",
      side: "BUY",
      quantity: 1000,
      strategy: "TWAP",
      slices: 6,
    });
    // Numbers must be sent as numbers, not form strings.
    expect(typeof payload.quantity).toBe("number");
    expect(typeof payload.slices).toBe("number");
    // Nested cost/impact config is included.
    expect(payload.costs).toMatchObject({ commission_bps: 0.5, exchange_fee_bps: 0.1 });
    expect(payload.impact).toMatchObject({ enabled: false });
    // POV-only fields are not sent for a TWAP run.
    expect(payload).not.toHaveProperty("participation_rate");

    // The returned experiment id is handed back to the parent.
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42));
  });

  it("sends POV-specific fields when the POV strategy is selected", async () => {
    const user = userEvent.setup();
    render(<NewExperiment onCreated={() => {}} />);

    await user.selectOptions(screen.getByLabelText(/strategy/i), "POV");
    await user.click(screen.getByRole("button", { name: /run experiment/i }));

    await waitFor(() => expect(api.createExperiment).toHaveBeenCalledTimes(1));
    const payload = api.createExperiment.mock.calls[0][0];
    expect(payload.strategy).toBe("POV");
    expect(payload).toHaveProperty("participation_rate");
    expect(typeof payload.participation_rate).toBe("number");
    // TWAP/VWAP slicing fields are not sent for POV.
    expect(payload).not.toHaveProperty("slices");
  });

  it("sends VWAP volume_profile and price overrides only when provided", async () => {
    const user = userEvent.setup();
    render(<NewExperiment onCreated={() => {}} />);

    await user.selectOptions(screen.getByLabelText(/strategy/i), "VWAP");
    await user.type(screen.getByLabelText(/volume profile/i), "0.4, 0.3, 0.2, 0.1");
    await user.type(screen.getByLabelText(/arrival price/i), "101.5");
    await user.click(screen.getByRole("button", { name: /run experiment/i }));

    await waitFor(() => expect(api.createExperiment).toHaveBeenCalledTimes(1));
    const payload = api.createExperiment.mock.calls[0][0];
    expect(payload.strategy).toBe("VWAP");
    expect(payload.volume_profile).toEqual([0.4, 0.3, 0.2, 0.1]);
    expect(payload.arrival_price).toBe(101.5);
    // limit_price was left blank -> must not be sent (backend auto-derives).
    expect(payload).not.toHaveProperty("limit_price");
  });

  it("omits optional overrides when the fields are left blank (TWAP)", async () => {
    const user = userEvent.setup();
    render(<NewExperiment onCreated={() => {}} />);
    await user.click(screen.getByRole("button", { name: /run experiment/i }));
    await waitFor(() => expect(api.createExperiment).toHaveBeenCalledTimes(1));
    const payload = api.createExperiment.mock.calls[0][0];
    expect(payload).not.toHaveProperty("arrival_price");
    expect(payload).not.toHaveProperty("limit_price");
    expect(payload).not.toHaveProperty("volume_profile");
  });

  it("shows a backend error instead of crashing when the run fails", async () => {
    const user = userEvent.setup();
    api.createExperiment.mockRejectedValue(new Error("dataset not found"));
    render(<NewExperiment onCreated={() => {}} />);

    await user.click(screen.getByRole("button", { name: /run experiment/i }));

    expect(await screen.findByText("dataset not found")).toBeInTheDocument();
  });
});
