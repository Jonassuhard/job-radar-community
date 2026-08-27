import { render, screen, within } from "@testing-library/react";
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

function source(overrides: Record<string, unknown>) {
  return {
    name: "france_travail",
    mode: "api",
    enabled: true,
    available: true,
    automated: true,
    quota_per_day: 100,
    credential_configured: true,
    health_status: "ok",
    last_success_at: "2026-08-26T08:00:00Z",
    quota_remaining: 72,
    ...overrides,
  };
}

function mockSources(payload: unknown, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (path === "/api/session") return response({ token: "runtime-session" });
    if (path === "/api/sources") return response(payload, status);
    return response({ detail: "Not found" }, 404);
  });
}

describe("SourcesPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("distingue les collectes automatiques des imports manuels", async () => {
    mockSources([
      source({}),
      source({
        name: "linkedin",
        mode: "manual_only",
        automated: false,
        quota_per_day: 0,
        credential_configured: true,
        health_status: "not_run",
        last_success_at: null,
        quota_remaining: null,
      }),
    ]);
    window.history.replaceState({}, "", "/sources");

    render(<App />);

    const automatic = await screen.findByRole("region", { name: /connecteurs configurés/i });
    expect(within(automatic).getByText("France Travail")).toBeVisible();
    expect(within(automatic).getByText("72 / 100")).toBeVisible();
    const manual = screen.getByRole("region", { name: /imports manuels/i });
    expect(within(manual).getByText("LinkedIn")).toBeVisible();
    expect(within(manual).getByText(/aucune collecte automatique/i)).toBeVisible();
  });

  it("indique les connecteurs configurés mais non livrés sans les compter actifs", async () => {
    mockSources([
      source({
        name: "local_demo",
        available: false,
        automated: false,
        quota_per_day: 100,
        credential_configured: true,
        health_status: "skipped",
        last_success_at: null,
        quota_remaining: 100,
      }),
    ]);
    window.history.replaceState({}, "", "/sources");

    render(<App />);

    const connectors = await screen.findByRole("region", { name: /connecteurs configurés/i });
    expect(within(connectors).getByText("Démonstration locale")).toBeVisible();
    expect(within(connectors).getByText("Indisponible dans cette version")).toBeVisible();
    expect(within(connectors).queryByText("Quota restant")).not.toBeInTheDocument();
    expect(within(connectors).queryByText("Accès")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Résumé des sources")).toHaveTextContent("0 actifs");
  });

  it("distingue une source stockée localement des connecteurs distants", async () => {
    mockSources([
      source({
        name: "legacy_import",
        mode: "stored",
        enabled: false,
        available: false,
        automated: false,
        quota_per_day: 0,
        credential_configured: false,
        health_status: "not_run",
        last_success_at: null,
        quota_remaining: null,
      }),
    ]);
    window.history.replaceState({}, "", "/sources");

    render(<App />);

    const stored = await screen.findByRole("region", { name: /sources stockées localement/i });
    expect(within(stored).getByText("legacy import")).toBeVisible();
    expect(within(stored).getByText("Import ou historique local")).toBeVisible();
    expect(within(stored).getByText("Stockée localement")).toBeVisible();
    expect(within(stored).queryByText("API autorisée")).not.toBeInTheDocument();
    expect(within(stored).queryByText("Quota restant")).not.toBeInTheDocument();
    expect(within(stored).queryByText("Accès")).not.toBeInTheDocument();
  });

  it("rend les états de chargement, erreur récupérable et liste vide", async () => {
    let resolveSources: ((value: Response) => void) | undefined;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session" });
      if (path === "/api/sources") {
        return new Promise<Response>((resolve) => {
          resolveSources = resolve;
        });
      }
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/sources");
    const user = userEvent.setup();

    render(<App />);
    expect(await screen.findByRole("status", { name: /chargement des sources/i })).toBeVisible();
    resolveSources?.(
      new Response(JSON.stringify({ detail: "Unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/impossible de charger/i);

    fetchMock.mockImplementation((input) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session" });
      if (path === "/api/sources") return response([]);
      return response({}, 404);
    });
    await user.click(screen.getByRole("button", { name: /réessayer/i }));
    expect(await screen.findByRole("status", { name: /aucune source configurée/i })).toBeVisible();
  });

  it("prévisualise puis importe un fichier JSON local avec la session", async () => {
    const importRequests: Array<{ preview: string | null; token: string | null; body: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/session") return response({ token: "runtime-session" });
      if (url.pathname === "/api/sources") {
        return response([
          source({
            name: "linkedin",
            mode: "manual_only",
            automated: false,
            quota_per_day: 0,
            credential_configured: true,
            health_status: "not_run",
            last_success_at: null,
            quota_remaining: null,
          }),
        ]);
      }
      if (url.pathname === "/api/import") {
        importRequests.push({
          preview: url.searchParams.get("preview"),
          token: new Headers(init?.headers).get("X-Job-Radar-Token"),
          body: String(init?.body),
        });
        return response({
          preview: url.searchParams.get("preview") === "true",
          offers_received: 1,
          offers_seen: 1,
          offers_saved: 1,
          errors: [],
        });
      }
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/sources");
    const user = userEvent.setup();
    const payload = JSON.stringify([{ source: "linkedin", external_id: "manual-001" }]);

    render(<App />);
    const fileInput = await screen.findByLabelText("Fichier JSON d’offres");
    await user.upload(
      fileInput,
      new File([payload], "offres.json", { type: "application/json" }),
    );
    await user.click(screen.getByRole("button", { name: "Prévisualiser l’import" }));
    expect(await screen.findByRole("status", { name: "Résultat de l’import" })).toHaveTextContent(
      /1 offre valide/i,
    );
    await user.click(screen.getByRole("button", { name: "Importer les offres" }));
    expect(await screen.findByRole("status", { name: "Résultat de l’import" })).toHaveTextContent(
      /1 offre importée/i,
    );

    expect(importRequests).toEqual([
      { preview: "true", token: "runtime-session", body: payload },
      { preview: null, token: "runtime-session", body: payload },
    ]);
  });

  it("affiche les erreurs d’import indexées sans perdre le fichier choisi", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/session") return response({ token: "runtime-session" });
      if (url.pathname === "/api/sources") return response([source({ name: "linkedin", mode: "manual_only" })]);
      if (url.pathname === "/api/import") {
        return response(
          { detail: [{ path: "0.title", message: "Field required" }] },
          422,
        );
      }
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/sources");
    const user = userEvent.setup();

    render(<App />);
    const fileInput = await screen.findByLabelText("Fichier JSON d’offres");
    await user.upload(
      fileInput,
      new File(["[{}]"], "invalide.json", { type: "application/json" }),
    );
    await user.click(screen.getByRole("button", { name: "Prévisualiser l’import" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("0.title: Field required");
    expect(screen.getByText("invalide.json")).toBeVisible();
  });

  it("expose un bouton après le retry borné du bootstrap de session", async () => {
    let sessionRequests = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/session") {
        sessionRequests += 1;
        return sessionRequests <= 2
          ? response({ detail: "API restarting" }, 503)
          : response({ token: "recovered-session" });
      }
      if (url.pathname === "/api/sources") return response([source({ name: "linkedin", mode: "manual_only" })]);
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/sources");
    const user = userEvent.setup();

    render(<App />);
    const retry = await screen.findByRole("button", { name: "Réessayer la session locale" });
    expect(sessionRequests).toBe(2);
    await user.click(retry);

    expect(await screen.findByLabelText("Session locale active")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Réessayer la session locale" })).not.toBeInTheDocument();
    expect(sessionRequests).toBe(3);
  });

  it("récupère une nouvelle session après 401 et rejoue l’import une fois", async () => {
    let sessionRequests = 0;
    const mutationTokens: Array<string | null> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/session") {
        sessionRequests += 1;
        return response({ token: sessionRequests === 1 ? "expired-session" : "fresh-session" });
      }
      if (url.pathname === "/api/sources") return response([source({ name: "linkedin", mode: "manual_only" })]);
      if (url.pathname === "/api/import") {
        mutationTokens.push(new Headers(init?.headers).get("X-Job-Radar-Token"));
        return mutationTokens.length === 1
          ? response({ detail: "Unauthorized" }, 401)
          : response({
              preview: false,
              offers_received: 1,
              offers_seen: 1,
              offers_saved: 1,
              errors: [],
            });
      }
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/sources");
    const user = userEvent.setup();

    render(<App />);
    const fileInput = await screen.findByLabelText("Fichier JSON d’offres");
    await user.upload(
      fileInput,
      new File(["[]"], "offres.json", { type: "application/json" }),
    );
    await user.click(screen.getByRole("button", { name: "Importer les offres" }));

    expect(await screen.findByRole("status", { name: "Résultat de l’import" })).toHaveTextContent(
      /1 offre importée/i,
    );
    expect(sessionRequests).toBe(2);
    expect(mutationTokens).toEqual(["expired-session", "fresh-session"]);
  });

  it("ne rejoue pas indéfiniment une mutation toujours refusée", async () => {
    let sessionRequests = 0;
    let importRequests = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/session") {
        sessionRequests += 1;
        return response({ token: `session-${sessionRequests}` });
      }
      if (url.pathname === "/api/sources") return response([source({ name: "linkedin", mode: "manual_only" })]);
      if (url.pathname === "/api/import") {
        importRequests += 1;
        return response({ detail: "Unauthorized" }, 401);
      }
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/sources");
    const user = userEvent.setup();

    render(<App />);
    await user.upload(
      await screen.findByLabelText("Fichier JSON d’offres"),
      new File(["[]"], "offres.json", { type: "application/json" }),
    );
    await user.click(screen.getByRole("button", { name: "Importer les offres" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Unauthorized");
    expect(sessionRequests).toBe(2);
    expect(importRequests).toBe(2);
  });
});
