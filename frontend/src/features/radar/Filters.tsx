import { RotateCcw, Search } from "lucide-react";

export type RadarFilters = {
  q: string;
  decision: string;
  source: string;
  min_score: string;
  remote: string;
  sort: string;
};

type FiltersProps = {
  values: RadarFilters;
  sources: string[];
  onChange: (key: keyof RadarFilters, value: string) => void;
  onReset: () => void;
};

const sourceLabels: Record<string, string> = {
  france_travail: "France Travail",
  public_ats: "ATS public",
  linkedin: "LinkedIn",
  indeed: "Indeed",
  wttj: "Welcome to the Jungle",
};

export function Filters({ values, sources, onChange, onReset }: FiltersProps) {
  const hasFilters = Boolean(
    values.q || values.decision || values.source || values.min_score || values.remote,
  );

  return (
    <form className="filters" onSubmit={(event) => event.preventDefault()}>
      <label className="search-field">
        <span>Rechercher</span>
        <Search aria-hidden="true" size={18} />
        <input
          type="search"
          value={values.q}
          onChange={(event) => onChange("q", event.target.value)}
          placeholder="Métier, entreprise, lieu"
        />
      </label>

      <label className="filter-field decision-field">
        <span>Décision</span>
        <select value={values.decision} onChange={(event) => onChange("decision", event.target.value)}>
          <option value="">Toutes</option>
          <option value="prioritize">À prioriser</option>
          <option value="review">À examiner</option>
          <option value="monitor">À surveiller</option>
          <option value="reject">Écartée</option>
        </select>
      </label>

      <label className="filter-field source-field">
        <span>Source</span>
        <select value={values.source} onChange={(event) => onChange("source", event.target.value)}>
          <option value="">Toutes</option>
          {sources.map((source) => (
            <option value={source} key={source}>
              {sourceLabels[source] ?? source.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </label>

      <label className="filter-field remote-field">
        <span>Télétravail</span>
        <select value={values.remote} onChange={(event) => onChange("remote", event.target.value)}>
          <option value="">Tous</option>
          <option value="remote">À distance</option>
          <option value="hybrid">Hybride</option>
          <option value="onsite">Sur site</option>
        </select>
      </label>

      <label className="score-filter">
        <span>Score min. <strong>{values.min_score || "0"}</strong></span>
        <input
          aria-label="Score minimum"
          type="range"
          min="0"
          max="100"
          step="5"
          value={values.min_score || "0"}
          onChange={(event) => onChange("min_score", event.target.value === "0" ? "" : event.target.value)}
        />
      </label>

      <label className="filter-field sort-field">
        <span>Tri</span>
        <select value={values.sort} onChange={(event) => onChange("sort", event.target.value)}>
          <option value="relevance_desc">Pertinence</option>
          <option value="confidence_desc">Confiance</option>
          <option value="freshness_asc">Plus récentes</option>
          <option value="published_desc">Publication</option>
          <option value="relevance_asc">Score croissant</option>
        </select>
      </label>

      <button className="icon-button reset-filters" type="button" onClick={onReset} disabled={!hasFilters} aria-label="Effacer les filtres" title="Effacer les filtres">
        <RotateCcw aria-hidden="true" size={17} />
      </button>
    </form>
  );
}
