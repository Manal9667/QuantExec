// Unit tests for the fetch wrapper (src/api.js). These lock in the contract
// the components rely on: correct URLs/methods, JSON bodies, and that a failed
// response surfaces the backend's structured `detail` as a thrown Error rather
// than silently returning a bad value (spec section 40, Rule 8).
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "./api.js";

describe("api fetch wrapper", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function okJson(body) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  }

  it("GET /strategies hits the proxied /api base", async () => {
    global.fetch.mockReturnValue(okJson([{ name: "TWAP" }]));
    const result = await api.listStrategies();
    expect(global.fetch).toHaveBeenCalledWith("/api/strategies", expect.any(Object));
    expect(result).toEqual([{ name: "TWAP" }]);
  });

  it("createExperiment POSTs a JSON body", async () => {
    global.fetch.mockReturnValue(okJson({ id: 7 }));
    const payload = { symbol: "SYN", strategy: "TWAP" };
    const result = await api.createExperiment(payload);

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/experiments");
    expect(options.method).toBe("POST");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(options.body)).toEqual(payload);
    expect(result).toEqual({ id: 7 });
  });

  it("builds the per-id fills URL", async () => {
    global.fetch.mockReturnValue(okJson([]));
    await api.getFills(13);
    expect(global.fetch).toHaveBeenCalledWith("/api/experiments/13/fills", expect.any(Object));
  });

  it("throws the backend's `detail` message on a non-OK response", async () => {
    global.fetch.mockReturnValue(
      Promise.resolve({
        ok: false,
        statusText: "Bad Request",
        json: () => Promise.resolve({ error_type: "dataset_not_found", detail: "Dataset not found: x.csv" }),
      })
    );
    await expect(api.getExperiment(99)).rejects.toThrow("Dataset not found: x.csv");
  });

  it("falls back to statusText when the error body is not JSON", async () => {
    global.fetch.mockReturnValue(
      Promise.resolve({
        ok: false,
        statusText: "Internal Server Error",
        json: () => Promise.reject(new Error("not json")),
      })
    );
    await expect(api.listExperiments()).rejects.toThrow("Internal Server Error");
  });
});
