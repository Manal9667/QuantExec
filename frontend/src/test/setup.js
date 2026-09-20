// Vitest setup: adds jest-dom matchers (toBeInTheDocument, toBeDisabled, ...)
// and clears mocks between tests so state never leaks across cases.
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
