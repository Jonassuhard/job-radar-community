export type OfferFact = {
  name: string;
  value: string;
  citation: string;
  confidence: number;
};

export type ScoreAxis = {
  name: string;
  points: number;
  explanation: string;
};

export type Provenance = {
  source: string;
  external_id: string;
  url: string;
};

export type Offer = {
  id: number;
  source: string;
  url: string;
  title: string;
  company: string;
  location: string;
  contract: string;
  remote: string;
  description: string;
  published_at: string;
  facts: OfferFact[];
  axes: ScoreAxis[];
  relevance: number;
  confidence: number;
  freshness_days: number;
  decision: string;
  score_version: string;
  blocker: string | null;
  provenance: Provenance[];
};

export type OfferPage = {
  items: Offer[];
  total: number;
  limit: number;
  offset: number;
};

export type CompareResponse = {
  offers: Offer[];
  missing: number[];
};

export type FeedbackResponse = {
  id: number;
  offer_id: number;
  value: string;
  note: string | null;
  created_at: string;
};

export type MarketInsights = {
  total_offers: number;
  decisions: Record<string, number>;
  skills: Array<{ name: string; count: number }>;
};

export type SourceStatus = {
  name: string;
  mode: "api" | "ats" | "manual_only" | "stored";
  enabled: boolean;
  available: boolean;
  automated: boolean;
  quota_per_day: number;
  credential_configured: boolean;
  health_status: string;
  last_success_at: string | null;
  quota_remaining: number | null;
};

export type ProfileConfig = {
  roles: string[];
  skills: string[];
  evidence: string[];
  languages: string[];
  seniority: string;
};

export type SearchConfig = {
  locations: string[];
  contracts: string[];
  remote: "any" | "remote" | "hybrid" | "onsite";
  salary_minimum: number;
  include_terms: string[];
  exclude_terms: string[];
};

export type ScoreAxisName =
  | "role_fit"
  | "skills"
  | "location"
  | "contract"
  | "work_mode"
  | "language"
  | "seniority"
  | "required_terms"
  | "include_terms"
  | "salary";
export type DecisionName = "reject" | "monitor" | "review" | "prioritize";
export type ScoreAxisConfig = { name: ScoreAxisName; weight: number };
export type DecisionConfig = { name: DecisionName; min_score: number };
export type BonusConfig = { name: "salary_transparency"; points: number };
export type PenaltyConfig = {
  name: "missing_salary" | "missing_role_detail";
  points: number;
};
export type BlockerConfig = {
  name: string;
  condition: "excluded_term" | "required_term_missing";
};

export type ScoringConfig = {
  axes: ScoreAxisConfig[];
  decisions: DecisionConfig[];
  thresholds: Partial<Record<"minimum_confidence" | "deduplication_similarity", number>>;
  caps: Partial<Record<"bonus" | "penalty", number>>;
  bonuses: BonusConfig[];
  penalties: PenaltyConfig[];
  blockers: BlockerConfig[];
};

export type SourceConfig = {
  mode: "api" | "ats" | "manual_only";
  enabled: boolean;
  quota_per_day: number;
  api_key_env: string | null;
};

export type AppConfig = {
  profile: ProfileConfig;
  search: SearchConfig;
  scoring: ScoringConfig;
  sources: { sources: Record<string, SourceConfig> };
  taxonomy: {
    aliases: Record<string, string[]>;
    required: string[];
    preferred: string[];
    mentioned: string[];
  };
};

export type ValidationIssue = { path: string; message: string };
export type ConfigValidation = { valid: boolean; errors: ValidationIssue[] };
export type ImportResponse = {
  preview: boolean;
  offers_received: number;
  offers_seen: number;
  offers_saved: number;
  errors: ValidationIssue[];
};
export type RescoreResponse = {
  offers_scored: number;
  score_version: string | null;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail = `Erreur API ${response.status}`;
    try {
      const payload = (await response.json()) as {
        detail?: string | ValidationIssue[];
      };
      if (typeof payload.detail === "string") detail = payload.detail;
      else if (Array.isArray(payload.detail)) {
        detail = payload.detail.map((issue) => `${issue.path}: ${issue.message}`).join(" · ");
      }
    } catch {
      // The public error remains deliberately generic for non-JSON failures.
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as T;
}

export function fetchOffers(search: string): Promise<OfferPage> {
  return request(`/api/offers${search ? `?${search}` : ""}`);
}

export function fetchOffer(id: number): Promise<Offer> {
  return request(`/api/offers/${id}`);
}

export function compareOffers(ids: number[]): Promise<CompareResponse> {
  return request("/api/offers/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
}

export async function fetchSessionToken(): Promise<string> {
  const session = await request<{ token: string }>("/api/session");
  const token = session.token.trim();
  if (!token) throw new ApiError("Session locale invalide", 503);
  return token;
}

export function createFeedback(
  offerId: number,
  value: string,
  token: string,
): Promise<FeedbackResponse> {
  return request(`/api/offers/${offerId}/feedback`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Job-Radar-Token": token,
    },
    body: JSON.stringify({ value }),
  });
}

export function fetchMarketInsights(): Promise<MarketInsights> {
  return request("/api/insights/market");
}

export function fetchSources(): Promise<SourceStatus[]> {
  return request("/api/sources");
}

function readLocalFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result ?? "")), { once: true });
    reader.addEventListener("error", () => reject(new ApiError("Fichier local illisible", 422)), {
      once: true,
    });
    reader.readAsText(file, "utf-8");
  });
}

export async function importOfferFile(
  file: File,
  token: string,
  preview: boolean,
): Promise<ImportResponse> {
  const payload = await readLocalFile(file);
  return request(`/api/import${preview ? "?preview=true" : ""}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Job-Radar-Token": token,
    },
    body: payload,
  });
}

export function fetchConfig(): Promise<AppConfig> {
  return request("/api/config");
}

export function validateConfig(config: AppConfig): Promise<ConfigValidation> {
  return request("/api/config/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

export function writeConfig(config: AppConfig, token: string): Promise<AppConfig> {
  return request("/api/config", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "X-Job-Radar-Token": token,
    },
    body: JSON.stringify(config),
  });
}

export function rescoreOffers(token: string): Promise<RescoreResponse> {
  return request("/api/rescore", {
    method: "POST",
    headers: { "X-Job-Radar-Token": token },
  });
}
