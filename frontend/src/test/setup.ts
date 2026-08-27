import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/radar");
  document.querySelector('meta[name="job-radar-session-token"]')?.remove();
});
