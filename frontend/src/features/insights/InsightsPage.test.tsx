import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../../app/App";

function response(payload: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockInsights(payload: unknown, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (path === "/api/session") return response({ token: "runtime-session" });
    if (path === "/api/insights/market") return response(payload, status);
    return response({ detail: "Not found" }, 404);
  });
}

describe("InsightsPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("affiche uniquement les chiffres du marché local et signale l'absence de tendance", async () => {
    mockInsights({
      total_offers: 42,
      decisions: { prioritize: 10, review: 12, monitor: 10, reject: 10 },
      skills: [
        { name: "workflow design", count: 16 },
        { name: "data quality", count: 9 },
      ],
    });
    window.history.replaceState({}, "", "/insights");

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Marché local" })).toBeVisible();
    expect(await screen.findByText("42")).toBeVisible();
    expect(screen.getByText("16")).toBeVisible();
    expect(screen.getByText("workflow design")).toBeVisible();
    expect(screen.getByText(/historique insuffisant/i)).toBeVisible();
    expect(screen.queryByText(/profil personnel/i)).not.toBeInTheDocument();
  });

  it("rend les états de chargement, erreur avec reprise, puis vide", async () => {
    let resolveInsights: ((value: Response) => void) | undefined;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session" });
      if (path === "/api/insights/market") {
        return new Promise<Response>((resolve) => {
          resolveInsights = resolve;
        });
      }
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/insights");
    const user = userEvent.setup();

    render(<App />);
    expect(await screen.findByRole("status", { name: /chargement des indicateurs/i })).toBeVisible();
    resolveInsights?.(
      new Response(JSON.stringify({ detail: "Unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/impossible de charger/i);

    fetchMock.mockImplementation((input) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session" });
      if (path === "/api/insights/market") {
        return response({ total_offers: 0, decisions: {}, skills: [] });
      }
      return response({}, 404);
    });
    await user.click(screen.getByRole("button", { name: /réessayer/i }));

    const empty = await screen.findByRole("status", { name: /aucune donnée de marché/i });
    expect(within(empty).getByText(/alimentez le corpus local/i)).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  });

  it("limite le classement aux douze compétences les plus demandées", async () => {
    mockInsights({
      total_offers: 42,
      decisions: { prioritize: 42 },
      skills: [
        { name: "skill-01", count: 20 }, { name: "skill-02", count: 19 },
        { name: "skill-03", count: 18 }, { name: "skill-04", count: 17 },
        { name: "skill-05", count: 16 }, { name: "skill-06", count: 15 },
        { name: "skill-07", count: 14 }, { name: "skill-08", count: 13 },
        { name: "skill-09", count: 12 }, { name: "skill-10", count: 11 },
        { name: "skill-11", count: 10 }, { name: "skill-12", count: 9 },
        { name: "skill-13", count: 8 },
      ],
    });
    window.history.replaceState({}, "", "/insights");

    render(<App />);

    expect(await screen.findByText("skill-12")).toBeVisible();
    expect(screen.queryByText("skill-13")).not.toBeInTheDocument();
  });
});
