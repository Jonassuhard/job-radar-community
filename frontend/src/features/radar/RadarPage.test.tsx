import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../app/App";

const offer = (id: number, title: string, overrides = {}) => ({
  id,
  source: "france_travail",
  url: `https://france-travail.example/offers/demo-${id}`,
  title,
  company: `Entreprise ${id}`,
  location: "Paris",
  contract: "permanent",
  remote: "hybrid",
  description: `${title}, environnement produit et automatisation.`,
  published_at: "2026-08-25T08:00:00Z",
  facts: [
    {
      name: "skill",
      value: "automatisation",
      citation: "L'offre mentionne explicitement l'automatisation.",
      confidence: 94,
    },
  ],
  axes: [
    { name: "role", points: 48, explanation: "Le rôle correspond à la recherche." },
    { name: "skills", points: 44, explanation: "Les compétences attendues sont présentes." },
  ],
  relevance: 92,
  confidence: 94,
  freshness_days: 1,
  decision: "prioritize",
  score_version: "demo-v1",
  blocker: null,
  provenance: [
    {
      source: "france_travail",
      external_id: `demo-${id}`,
      url: `https://france-travail.example/offers/demo-${id}`,
    },
  ],
  ...overrides,
});

const offers = [
  offer(1, "Product Operations Analyst"),
  offer(2, "Growth Systems Manager", { relevance: 87 }),
  offer(3, "AI Product Specialist", { relevance: 83 }),
  offer(4, "Revenue Operations Lead", { relevance: 79 }),
];

const page = (items = offers, overrides = {}) => ({
  items,
  total: items.length,
  limit: 25,
  offset: 0,
  ...overrides,
});

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockApi(initialPage = page(), sessionStatus = 200) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = new URL(String(input), "http://localhost");

    if (url.pathname === "/api/session") {
      return jsonResponse(
        sessionStatus === 200 ? { token: "bootstrapped-runtime-token" } : { detail: "Unavailable" },
        sessionStatus,
      );
    }

    if (url.pathname === "/api/offers" && init?.method !== "POST") {
      return jsonResponse(initialPage);
    }

    if (url.pathname === "/api/sources") {
      return jsonResponse([
        { name: "france_travail", mode: "api", enabled: false, automated: false, quota_per_day: 0, credential_configured: false, health_status: "unavailable", last_success_at: null, quota_remaining: null },
        { name: "indeed", mode: "manual_only", enabled: true, automated: false, quota_per_day: 0, credential_configured: false, health_status: "manual", last_success_at: null, quota_remaining: null },
        { name: "custom_ats", mode: "ats", enabled: true, automated: true, quota_per_day: 0, credential_configured: false, health_status: "ready", last_success_at: null, quota_remaining: null },
      ]);
    }

    if (url.pathname === "/api/offers/compare") {
      const ids = JSON.parse(String(init?.body)).ids as number[];
      return jsonResponse({ offers: offers.filter((item) => ids.includes(item.id)), missing: [] });
    }

    const feedbackMatch = url.pathname.match(/^\/api\/offers\/(\d+)\/feedback$/);
    if (feedbackMatch) {
      const body = JSON.parse(String(init?.body));
      return jsonResponse(
        {
          id: 1,
          offer_id: Number(feedbackMatch[1]),
          value: body.value,
          note: body.note ?? null,
          created_at: "2026-08-26T08:00:00Z",
        },
        201,
      );
    }

    const detailMatch = url.pathname.match(/^\/api\/offers\/(\d+)$/);
    if (detailMatch) {
      return jsonResponse(offers.find((item) => item.id === Number(detailMatch[1])));
    }

    return jsonResponse({ detail: "Not found" }, 404);
  });
}

function setMobileViewport(matches: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: matches && query === "(max-width: 1020px)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

describe("Radar public", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/radar");
    setMobileViewport(false);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("affiche un chargement stable avant le contrat paginé", () => {
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));

    render(<App />);

    expect(screen.getByRole("status", { name: /chargement des offres/i })).toBeVisible();
    expect(screen.getAllByTestId("offer-skeleton")).toHaveLength(5);
  });

  it("rend l'erreur récupérable puis relance la requête", async () => {
    let offerAttempts = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/session") {
        return jsonResponse({ token: "bootstrapped-runtime-token" });
      }
      offerAttempts += 1;
      return offerAttempts === 1
        ? Promise.reject(new Error("API hors ligne"))
        : jsonResponse(page());
    });
    const user = userEvent.setup();

    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Impossible de charger le radar");

    await user.click(screen.getByRole("button", { name: /réessayer/i }));

    const recoveredOffer = await screen.findByText("Product Operations Analyst");
    await waitFor(() => expect(recoveredOffer).toBeVisible());
    expect(
      fetchMock.mock.calls.filter(([input]) => String(input).includes("/api/offers")),
    ).toHaveLength(2);
  });

  it("distingue un résultat vide et permet d'effacer les filtres", async () => {
    mockApi(page([], { total: 0 }));
    window.history.replaceState({}, "", "/radar?q=introuvable");
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByText("Aucune offre dans ce secteur du radar")).toBeVisible();
    const emptyState = screen
      .getByText("Aucune offre dans ce secteur du radar")
      .closest<HTMLElement>(".state-panel")!;
    await user.click(within(emptyState).getByRole("button", { name: /effacer les filtres/i }));
    expect(window.location.search).toBe("");
  });

  it("synchronise filtres, tri et pagination avec l'URL et l'API", async () => {
    const fetchMock = mockApi(page([offers[0]], { total: 42 }));
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Product Operations Analyst");
    await user.type(screen.getByRole("searchbox", { name: /rechercher/i }), "product");
    await user.selectOptions(screen.getByRole("combobox", { name: /décision/i }), "prioritize");
    await user.selectOptions(screen.getByRole("combobox", { name: /tri/i }), "freshness_asc");

    await waitFor(() => {
      expect(window.location.search).toContain("q=product");
      expect(window.location.search).toContain("decision=prioritize");
      expect(window.location.search).toContain("sort=freshness_asc");
    });

    await user.click(screen.getByRole("button", { name: /page suivante/i }));
    await waitFor(() => expect(window.location.search).toContain("offset=25"));

    const offerRequests = fetchMock.mock.calls
      .map(([input]) => new URL(String(input), "http://localhost"))
      .filter((url) => url.pathname === "/api/offers");
    expect(offerRequests.at(-1)?.searchParams.get("q")).toBe("product");
    expect(offerRequests.at(-1)?.searchParams.get("decision")).toBe("prioritize");
    expect(offerRequests.at(-1)?.searchParams.get("sort")).toBe("freshness_asc");
    expect(offerRequests.at(-1)?.searchParams.get("offset")).toBe("25");
  });

  it("propose les sources manuelles et personnalisées dans le filtre", async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Product Operations Analyst");
    const source = screen.getByRole("combobox", { name: /source/i });

    expect(within(source).getByRole("option", { name: "Indeed" })).toBeInTheDocument();
    expect(within(source).getByRole("option", { name: "custom ats" })).toBeInTheDocument();
    await user.selectOptions(source, "indeed");

    await waitFor(() => {
      const offerRequests = fetchMock.mock.calls
        .map(([input]) => new URL(String(input), "http://localhost"))
        .filter((url) => url.pathname === "/api/offers");
      expect(offerRequests.at(-1)?.searchParams.get("source")).toBe("indeed");
    });
  });

  it("ouvre un détail explicable sans action de candidature", async () => {
    mockApi();
    const user = userEvent.setup();

    render(<App />);
    await user.click(await screen.findByRole("button", { name: /ouvrir product operations analyst/i }));

    const detail = await screen.findByRole("region", { name: /détail de l'offre/i });
    expect(within(detail).getByText("Le rôle correspond à la recherche.")).toBeVisible();
    expect(within(detail).getByText("L'offre mentionne explicitement l'automatisation.")).toBeVisible();
    const sourceLink = within(detail).getByRole("link", { name: /voir l'annonce source/i });
    expect(sourceLink).toHaveAttribute(
      "href",
      "https://france-travail.example/offers/demo-1",
    );
    expect(sourceLink).toHaveAttribute("target", "_blank");
    expect(
      within(detail).getByRole("link", { name: /france travail · demo-1/i }),
    ).toHaveAttribute("href", "https://france-travail.example/offers/demo-1");
    expect(screen.queryByRole("button", { name: /candid/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /postuler/i })).not.toBeInTheDocument();
  });

  it("rend le détail mobile modal et restaure le focus après Escape", async () => {
    setMobileViewport(true);
    mockApi();
    const user = userEvent.setup();

    render(<App />);
    const trigger = await screen.findByRole("button", {
      name: /ouvrir product operations analyst/i,
    });
    await user.click(trigger);

    const dialog = await screen.findByRole("dialog", { name: /détail de l'offre/i });
    const close = within(dialog).getByRole("button", { name: /fermer le détail/i });
    await waitFor(() => expect(close).toHaveFocus());

    await user.tab({ shift: true });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("limite la comparaison à trois offres et affiche le contrat comparé", async () => {
    mockApi();
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Product Operations Analyst");
    const compareChecks = screen.getAllByRole("checkbox", { name: /comparer/i });
    await user.click(compareChecks[0]);
    await user.click(compareChecks[1]);
    await user.click(compareChecks[2]);

    expect(compareChecks[3]).toBeDisabled();
    expect(screen.getByText("3 sur 3 sélectionnées")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /comparer 3 offres/i }));

    const dialog = await screen.findByRole("dialog", { name: /comparaison/i });
    expect(within(dialog).getByText("Product Operations Analyst")).toBeVisible();
    expect(within(dialog).getByText("Growth Systems Manager")).toBeVisible();
    expect(within(dialog).getByText("AI Product Specialist")).toBeVisible();
  });

  it("signale le mode démo et enregistre un feedback explicite", async () => {
    mockApi();
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    const user = userEvent.setup();

    render(<App />);
    expect(await screen.findByText("Mode démo")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /ouvrir product operations analyst/i }));
    expect(await screen.findByRole("heading", { name: /donner un avis/i })).toBeVisible();
    expect(screen.getByText(/cet avis n'influence pas encore le score/i)).toBeVisible();
    await user.click(await screen.findByRole("button", { name: /^pertinente$/i }));

    expect(await screen.findByText("Avis enregistré localement")).toBeVisible();
    const feedbackCall = vi.mocked(fetch).mock.calls.find(([input]) =>
      String(input).includes("/feedback"),
    );
    expect(new Headers(feedbackCall?.[1]?.headers).get("X-Job-Radar-Token")).toBe(
      "bootstrapped-runtime-token",
    );
    expect(storageWrite).not.toHaveBeenCalled();
    expect(window.location.href).not.toContain("bootstrapped-runtime-token");
    expect(document.documentElement.textContent).not.toContain("bootstrapped-runtime-token");
  });

  it("désactive le feedback lorsque la session locale est indisponible", async () => {
    mockApi(page(), 404);
    const user = userEvent.setup();

    render(<App />);
    await user.click(await screen.findByRole("button", { name: /ouvrir product operations analyst/i }));

    expect(await screen.findByText("Feedback indisponible sans session locale.")).toBeVisible();
    expect(screen.getByRole("button", { name: /^pertinente$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^à revoir$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^non pertinente$/i })).toBeDisabled();
  });
});
