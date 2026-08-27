import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../../app/App";
import type { AppConfig } from "../../lib/api";

const initialConfig = {
  profile: {
    roles: ["Product Operations Specialist"],
    skills: ["workflow design", "data quality"],
    evidence: ["operational case study"],
    languages: ["English"],
    seniority: "mid",
  },
  search: {
    locations: ["Central District"],
    contracts: ["permanent"],
    remote: "hybrid",
    salary_minimum: 0,
    include_terms: ["operations"],
    exclude_terms: ["commission-only"],
  },
  scoring: {
    axes: [
      { name: "role_fit", weight: 60 },
      { name: "skills", weight: 40 },
    ],
    decisions: [
      { name: "reject", min_score: 0 },
      { name: "monitor", min_score: 30 },
      { name: "review", min_score: 55 },
      { name: "prioritize", min_score: 85 },
    ],
    thresholds: { minimum_confidence: 40 },
    caps: { bonus: 10 },
    bonuses: [],
    penalties: [],
    blockers: [],
  },
  sources: {
    sources: {
      france_travail: { mode: "api", enabled: true, quota_per_day: 100, api_key_env: null },
      linkedin: { mode: "manual_only", enabled: true, quota_per_day: 0, api_key_env: null },
    },
  },
  taxonomy: {
    aliases: { workflow: ["operations"] },
    required: ["workflow"],
    preferred: [],
    mentioned: [],
  },
};

function response(payload: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function mockConfig(
  validation: { valid: boolean; errors: Array<{ path: string; message: string }> } = {
    valid: true,
    errors: [],
  },
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (path === "/api/session") return response({ token: "runtime-session-token" });
    if (path === "/api/config" && init?.method === "PUT") {
      return response(JSON.parse(String(init.body)));
    }
    if (path === "/api/rescore" && init?.method === "POST") {
      return response({ offers_scored: 42, score_version: "public-v1" });
    }
    if (path === "/api/config") return response(initialConfig);
    if (path === "/api/config/validate") return response(validation);
    return response({ detail: "Not found" }, 404);
  });
}

async function openPreview(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("heading", { name: "Profil" });
  await user.click(screen.getByRole("button", { name: /suivant/i }));
  await user.click(screen.getByRole("button", { name: /suivant/i }));
  await user.click(screen.getByRole("button", { name: /suivant/i }));
  await user.click(screen.getByRole("button", { name: /valider et afficher/i }));
  return screen.findByRole("region", { name: /aperçu yaml/i });
}

describe("ConfigurationPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("guide les quatre étapes, valide le document et montre le YAML avant toute écriture", async () => {
    const fetchMock = mockConfig();
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    expect(await screen.findByRole("heading", { name: "Profil" })).toBeVisible();
    await user.clear(screen.getByRole("textbox", { name: /rôles visés/i }));
    await user.type(screen.getByRole("textbox", { name: /rôles visés/i }), "Data Analyst");
    await user.click(screen.getByRole("button", { name: /suivant/i }));

    expect(screen.getByRole("heading", { name: "Recherche" })).toBeVisible();
    await user.selectOptions(screen.getByRole("combobox", { name: /télétravail/i }), "remote");
    await user.click(screen.getByRole("button", { name: /suivant/i }));

    expect(screen.getByRole("heading", { name: "Poids" })).toBeVisible();
    await user.clear(screen.getByRole("spinbutton", { name: /poids role fit/i }));
    await user.type(screen.getByRole("spinbutton", { name: /poids role fit/i }), "55");
    await user.clear(screen.getByRole("spinbutton", { name: /poids skills/i }));
    await user.type(screen.getByRole("spinbutton", { name: /poids skills/i }), "45");
    await user.click(screen.getByRole("button", { name: /suivant/i }));

    expect(screen.getByRole("heading", { name: "Sources" })).toBeVisible();
    expect(screen.getByText(/import manuel uniquement/i)).toBeVisible();
    await user.click(screen.getByRole("button", { name: /valider et afficher/i }));

    const preview = await screen.findByRole("region", { name: /aperçu yaml/i });
    expect(within(preview).getByText("profile.yml", { exact: false })).toBeVisible();
    expect(within(preview).getByText("roles:", { exact: false })).toBeVisible();
    expect(within(preview).getByText("Data Analyst", { exact: false })).toBeVisible();
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT"),
    ).toHaveLength(0);

    const validateCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/api/config/validate"),
    );
    const validated = JSON.parse(String(validateCall?.[1]?.body));
    expect(validated.profile.roles).toEqual(["Data Analyst"]);
    expect(validated.search.remote).toBe("remote");
    expect(validated.taxonomy).toEqual(initialConfig.taxonomy);
  });

  it("conserve la saisie brute puis parse deux valeurs séparées par une virgule", async () => {
    const fetchMock = mockConfig();
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    const roles = await screen.findByRole("textbox", { name: /rôles visés/i });
    await user.clear(roles);
    await user.type(roles, "Data Analyst, Product Manager");

    expect(roles).toHaveValue("Data Analyst, Product Manager");
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /valider et afficher/i }));
    await screen.findByRole("region", { name: /aperçu yaml/i });

    const validateCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/api/config/validate"),
    );
    expect(JSON.parse(String(validateCall?.[1]?.body)).profile.roles).toEqual([
      "Data Analyst",
      "Product Manager",
    ]);
  });

  it("ignore une validation devenue obsolète après modification du draft", async () => {
    let resolveValidation: ((value: Response) => void) | undefined;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session-token" });
      if (path === "/api/config") return response(initialConfig);
      if (path === "/api/config/validate") {
        return new Promise<Response>((resolve) => {
          resolveValidation = resolve;
        });
      }
      if (path === "/api/config" && init?.method === "PUT") {
        return response(JSON.parse(String(init.body)));
      }
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    await screen.findByRole("heading", { name: "Profil" });
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /valider et afficher/i }));
    await user.click(screen.getByRole("button", { name: /^Profil$/i }));
    await user.clear(screen.getByRole("textbox", { name: /séniorité/i }));
    await user.type(screen.getByRole("textbox", { name: /séniorité/i }), "senior");
    await user.click(
      within(screen.getByRole("navigation", { name: /étapes de configuration/i }))
        .getByRole("button", { name: /Sources$/i }),
    );

    resolveValidation?.(new Response(JSON.stringify({ valid: true, errors: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /valider et afficher/i })).toBeEnabled();
    });

    expect(screen.queryByRole("region", { name: /aperçu yaml/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /enregistrer localement/i })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === "PUT")).toHaveLength(0);
  });

  it("invalide immédiatement une validation en vol dès la saisie brute d'une liste", async () => {
    let resolveFirstValidation: ((value: Response) => void) | undefined;
    let validationAttempts = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session-token" });
      if (path === "/api/config" && init?.method === "PUT") {
        return response(JSON.parse(String(init.body)));
      }
      if (path === "/api/config") return response(initialConfig);
      if (path === "/api/config/validate") {
        validationAttempts += 1;
        if (validationAttempts === 1) {
          return new Promise<Response>((resolve) => {
            resolveFirstValidation = resolve;
          });
        }
        return response({ valid: true, errors: [] });
      }
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    await screen.findByRole("heading", { name: "Profil" });
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /valider et afficher/i }));
    await user.click(screen.getByRole("button", { name: /^Profil$/i }));

    const roles = screen.getByRole("textbox", { name: /rôles visés/i });
    await user.type(roles, ", Visible raw change during validation");
    expect(roles).toHaveFocus();
    expect(roles).toHaveValue(
      "Product Operations Specialist, Visible raw change during validation",
    );

    resolveFirstValidation?.(new Response(JSON.stringify({ valid: true, errors: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(roles).toHaveFocus();
    expect(screen.queryByRole("region", { name: /aperçu yaml/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /enregistrer localement/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(
      within(screen.getByRole("navigation", { name: /étapes de configuration/i }))
        .getByRole("button", { name: /Sources$/i }),
    );
    await user.click(screen.getByRole("button", { name: /valider et afficher/i }));
    await screen.findByRole("region", { name: /aperçu yaml/i });
    expect(screen.getByRole("button", { name: /enregistrer localement/i })).toBeEnabled();

    const validateCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).includes("/api/config/validate"),
    );
    expect(validateCalls).toHaveLength(2);
    expect(JSON.parse(String(validateCalls[1]?.[1]?.body)).profile.roles).toEqual([
      "Product Operations Specialist",
      "Visible raw change during validation",
    ]);
  });

  it("affiche les erreurs de validation et ne propose aucune confirmation", async () => {
    mockConfig({
      valid: false,
      errors: [{ path: "scoring.axes", message: "axis weights must total 100" }],
    });
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    await screen.findByRole("heading", { name: "Profil" });
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /valider et afficher/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("scoring.axes");
    expect(screen.queryByRole("button", { name: /enregistrer/i })).not.toBeInTheDocument();
  });

  it("désactive les connecteurs indisponibles et les enregistre désactivés sans toucher aux imports manuels", async () => {
    const config = structuredClone(initialConfig) as AppConfig;
    config.sources.sources = {
      local_demo: { mode: "api", enabled: true, quota_per_day: 100, api_key_env: "DEMO_API_KEY" },
      adzuna: { mode: "api", enabled: true, quota_per_day: 25, api_key_env: "ADZUNA_API_KEY" },
      linkedin: { mode: "manual_only", enabled: true, quota_per_day: 0, api_key_env: null },
    };
    const writes: unknown[] = [];
    const validations: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session-token" });
      if (path === "/api/sources") {
        return response([
          { name: "local_demo", mode: "api", enabled: true, available: false, automated: false, quota_per_day: 100, credential_configured: true, health_status: "skipped", last_success_at: null, quota_remaining: 100 },
          { name: "adzuna", mode: "api", enabled: true, available: false, automated: false, quota_per_day: 25, credential_configured: true, health_status: "not_run", last_success_at: null, quota_remaining: 25 },
          { name: "linkedin", mode: "manual_only", enabled: true, available: false, automated: false, quota_per_day: 0, credential_configured: true, health_status: "not_run", last_success_at: null, quota_remaining: null },
        ]);
      }
      if (path === "/api/config" && init?.method === "PUT") {
        writes.push(JSON.parse(String(init.body)));
        return response(JSON.parse(String(init.body)));
      }
      if (path === "/api/rescore" && init?.method === "POST") {
        return response({ offers_scored: 42, score_version: "public-v1" });
      }
      if (path === "/api/config") return response(config);
      if (path === "/api/config/validate") {
        validations.push(JSON.parse(String(init?.body)));
        return response({ valid: true, errors: [] });
      }
      return response({ detail: "Not found" }, 404);
    });
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    await screen.findByRole("heading", { name: "Profil" });
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));

    expect(screen.getByRole("checkbox", { name: "Activer Démonstration locale" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Activer Adzuna" })).toBeDisabled();
    expect(screen.getAllByText("Indisponible dans cette version")).toHaveLength(2);
    expect(screen.queryByText(/API · quota/i)).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Activer LinkedIn" })).toBeEnabled();
    expect(screen.getByText("Import manuel uniquement")).toBeVisible();

    await user.click(screen.getByRole("button", { name: /valider et afficher/i }));
    await screen.findByRole("region", { name: /aperçu yaml/i });
    await user.click(screen.getByRole("button", { name: /enregistrer localement/i }));
    const dialog = await screen.findByRole("dialog", { name: /confirmer l.enregistrement/i });
    await user.click(within(dialog).getByRole("button", { name: /^confirmer$/i }));
    await screen.findByRole("status");

    expect(writes).toHaveLength(1);
    expect(validations).toHaveLength(1);
    const saved = writes[0] as typeof config;
    const previewed = validations[0] as typeof config;
    expect(saved.sources.sources.local_demo.enabled).toBe(false);
    expect(saved.sources.sources.adzuna.enabled).toBe(false);
    expect(saved.sources.sources.linkedin.enabled).toBe(true);
    expect(previewed.sources.sources).toEqual(saved.sources.sources);
  });

  it("demande confirmation avant le PUT et garde le jeton uniquement en mémoire", async () => {
    const fetchMock = mockConfig();
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    await screen.findByRole("heading", { name: "Profil" });
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /valider et afficher/i }));
    await user.click(await screen.findByRole("button", { name: /enregistrer localement/i }));

    const dialog = await screen.findByRole("dialog", { name: /confirmer l.enregistrement/i });
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: /^confirmer$/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      /configuration enregistrée et 42 offres recalculées/i,
    );
    const putCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    const rescoreCall = fetchMock.mock.calls.find(([input, init]) =>
      String(input).includes("/api/rescore") && init?.method === "POST",
    );
    const validateCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/api/config/validate"),
    );
    expect(JSON.parse(String(putCall?.[1]?.body))).toEqual(
      JSON.parse(String(validateCall?.[1]?.body)),
    );
    expect(new Headers(putCall?.[1]?.headers).get("X-Job-Radar-Token")).toBe(
      "runtime-session-token",
    );
    expect(new Headers(rescoreCall?.[1]?.headers).get("X-Job-Radar-Token")).toBe(
      "runtime-session-token",
    );
    const putIndex = fetchMock.mock.calls.indexOf(putCall!);
    const rescoreIndex = fetchMock.mock.calls.indexOf(rescoreCall!);
    expect(putIndex).toBeLessThan(rescoreIndex);
    expect(storageWrite).not.toHaveBeenCalled();
    expect(window.location.href).not.toContain("runtime-session-token");
    expect(document.documentElement.textContent).not.toContain("runtime-session-token");
  });

  it("affiche l'erreur PUT et la reprise dans le dialogue actif", async () => {
    let putAttempts = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session-token" });
      if (path === "/api/config" && init?.method === "PUT") {
        putAttempts += 1;
        return putAttempts === 1
          ? response({ detail: "Configuration update failed" }, 500)
          : response(JSON.parse(String(init.body)));
      }
      if (path === "/api/rescore" && init?.method === "POST") {
        return response({ offers_scored: 42, score_version: "public-v1" });
      }
      if (path === "/api/config") return response(initialConfig);
      if (path === "/api/config/validate") return response({ valid: true, errors: [] });
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    await openPreview(user);
    await user.click(screen.getByRole("button", { name: /enregistrer localement/i }));
    const dialog = await screen.findByRole("dialog", { name: /confirmer l.enregistrement/i });
    await user.click(within(dialog).getByRole("button", { name: /^confirmer$/i }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent(/enregistrement local a échoué/i);
    await user.click(within(alert).getByRole("button", { name: /réessayer/i }));
    expect(await screen.findByRole("status")).toHaveTextContent(/configuration enregistrée/i);
    expect(putAttempts).toBe(2);
  });

  it("signale un recalcul échoué et le reprend sans réécrire la configuration", async () => {
    let rescoreAttempts = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session-token" });
      if (path === "/api/config" && init?.method === "PUT") {
        return response(JSON.parse(String(init.body)));
      }
      if (path === "/api/rescore" && init?.method === "POST") {
        rescoreAttempts += 1;
        return rescoreAttempts === 1
          ? response({ detail: "Rescore failed" }, 500)
          : response({ offers_scored: 42, score_version: "public-v1" });
      }
      if (path === "/api/config") return response(initialConfig);
      if (path === "/api/config/validate") return response({ valid: true, errors: [] });
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    await openPreview(user);
    await user.click(screen.getByRole("button", { name: /enregistrer localement/i }));
    const dialog = await screen.findByRole("dialog", { name: /confirmer l.enregistrement/i });
    await user.click(within(dialog).getByRole("button", { name: /^confirmer$/i }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent(/configuration enregistrée, mais le recalcul a échoué/i);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
    await user.click(within(alert).getByRole("button", { name: /réessayer le recalcul/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/42 offres recalculées/i);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
    expect(rescoreAttempts).toBe(2);
  });

  it("restaure le focus au bouton Enregistrer après Escape, Annuler et succès", async () => {
    mockConfig();
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    await openPreview(user);
    const saveButton = screen.getByRole("button", { name: /enregistrer localement/i });

    await user.click(saveButton);
    await screen.findByRole("dialog", { name: /confirmer l.enregistrement/i });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(saveButton).toHaveFocus());

    await user.click(saveButton);
    const cancelDialog = await screen.findByRole("dialog", { name: /confirmer l.enregistrement/i });
    await user.click(within(cancelDialog).getByRole("button", { name: /annuler/i }));
    await waitFor(() => expect(saveButton).toHaveFocus());

    await user.click(saveButton);
    const successDialog = await screen.findByRole("dialog", { name: /confirmer l.enregistrement/i });
    await user.click(within(successDialog).getByRole("button", { name: /^confirmer$/i }));
    await screen.findByText(/configuration enregistrée et 42 offres recalculées/i);
    await waitFor(() => expect(saveButton).toHaveFocus());
  });

  it("garde la confirmation visible pendant l’enregistrement, puis réactive sa fermeture après le résultat", async () => {
    const writes = [deferred<Response>(), deferred<Response>()];
    let putAttempts = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session-token" });
      if (path === "/api/config" && init?.method === "PUT") return writes[putAttempts++]!.promise;
      if (path === "/api/rescore" && init?.method === "POST") {
        return response({ offers_scored: 42, score_version: "public-v1" });
      }
      if (path === "/api/config") return response(initialConfig);
      if (path === "/api/config/validate") return response({ valid: true, errors: [] });
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    await openPreview(user);
    const saveButton = screen.getByRole("button", { name: /enregistrer localement/i });
    await user.click(saveButton);
    const dialog = await screen.findByRole("dialog", { name: /confirmer l.enregistrement/i });
    await user.click(within(dialog).getByRole("button", { name: /^confirmer$/i }));

    const close = within(dialog).getByRole("button", { name: "Fermer" });
    const cancel = within(dialog).getByRole("button", { name: "Annuler" });
    await waitFor(() => {
      expect(close).toBeDisabled();
      expect(cancel).toBeDisabled();
      expect(within(dialog).getByRole("button", { name: /enregistrement/i })).toBeDisabled();
    });
    await user.click(close);
    await user.click(cancel);
    await user.keyboard("{Escape}");
    await user.click(document.querySelector(".dialog-overlay") as HTMLElement);
    expect(screen.getByRole("dialog", { name: /confirmer l.enregistrement/i })).toBeVisible();

    writes[0]!.resolve(new Response(JSON.stringify(initialConfig), { status: 200 }));
    expect(await screen.findByRole("status")).toHaveTextContent(/42 offres recalculées/i);
    expect(screen.queryByRole("dialog", { name: /confirmer l.enregistrement/i })).not.toBeInTheDocument();

    await user.click(saveButton);
    const rejectedDialog = await screen.findByRole("dialog", { name: /confirmer l.enregistrement/i });
    await user.click(within(rejectedDialog).getByRole("button", { name: /^confirmer$/i }));
    await waitFor(() => expect(within(rejectedDialog).getByRole("button", { name: "Annuler" })).toBeDisabled());
    writes[1]!.reject(new Error("Configuration update failed"));

    expect(await within(rejectedDialog).findByRole("alert")).toHaveTextContent(/enregistrement local a échoué/i);
    expect(within(rejectedDialog).getByRole("button", { name: "Fermer" })).toBeEnabled();
    expect(within(rejectedDialog).getByRole("button", { name: "Annuler" })).toBeEnabled();
  });

  it("désactive l'écriture quand la session locale est indisponible", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ detail: "Unavailable" }, 404);
      if (path === "/api/config") return response(initialConfig);
      if (path === "/api/config/validate") return response({ valid: true, errors: [] });
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    await screen.findByRole("heading", { name: "Profil" });
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.click(screen.getByRole("button", { name: /valider et afficher/i }));

    const save = await screen.findByRole("button", { name: /enregistrer localement/i });
    expect(save).toBeDisabled();
    expect(screen.getByText(/session locale indisponible/i)).toBeVisible();
  });

  it("rend les états de chargement et d'erreur récupérable", async () => {
    let resolveConfig: ((value: Response) => void) | undefined;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session-token" });
      if (path === "/api/config") {
        return new Promise<Response>((resolve) => {
          resolveConfig = resolve;
        });
      }
      return response({}, 404);
    });
    window.history.replaceState({}, "", "/configuration");
    const user = userEvent.setup();

    render(<App />);
    expect(await screen.findByRole("status", { name: /chargement de la configuration/i })).toBeVisible();
    resolveConfig?.(
      new Response(JSON.stringify({ detail: "Unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/impossible de charger/i);

    fetchMock.mockImplementation((input) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/session") return response({ token: "runtime-session-token" });
      if (path === "/api/config") return response(initialConfig);
      return response({}, 404);
    });
    await user.click(screen.getByRole("button", { name: /réessayer/i }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Profil" })).toBeVisible());
  });
});
