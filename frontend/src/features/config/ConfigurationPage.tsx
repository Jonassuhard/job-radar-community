import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  FileCheck2,
  Save,
  Settings2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useSession } from "../../app/SessionContext";
import {
  fetchConfig,
  fetchSources,
  rescoreOffers,
  validateConfig,
  writeConfig,
  type AppConfig,
  type SourceStatus,
  type ValidationIssue,
} from "../../lib/api";

const steps = ["Profil", "Recherche", "Poids", "Sources"];

const sourceLabels: Record<string, string> = {
  france_travail: "France Travail",
  adzuna: "Adzuna",
  jooble: "Jooble",
  remotive: "Remotive",
  public_ats: "ATS public",
  linkedin: "LinkedIn",
  indeed: "Indeed",
  wttj: "Welcome to the Jungle",
  local_demo: "Démonstration locale",
};

function cloneConfig(config: AppConfig): AppConfig {
  return structuredClone(config);
}

function parseList(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function listValue(value: string[]): string {
  return value.join(", ");
}

function normalizeEditableLists(config: AppConfig): AppConfig {
  const normalized = cloneConfig(config);
  for (const field of ["roles", "skills", "evidence", "languages"] as const) {
    normalized.profile[field] = normalized.profile[field].map((item) => item.trim()).filter(Boolean);
  }
  for (const field of ["locations", "contracts", "include_terms", "exclude_terms"] as const) {
    normalized.search[field] = normalized.search[field].map((item) => item.trim()).filter(Boolean);
  }
  return normalized;
}

async function yamlDocuments(config: AppConfig): Promise<Array<{ name: string; content: string }>> {
  const { stringify } = await import("yaml");
  return [
    { name: "profile.yml", content: stringify(config.profile) },
    { name: "search.yml", content: stringify(config.search) },
    { name: "scoring.yml", content: stringify(config.scoring) },
    { name: "sources.yml", content: stringify(config.sources) },
    { name: "taxonomy.yml", content: stringify(config.taxonomy) },
  ];
}

function PageHeading() {
  return (
    <header className="secondary-heading config-heading">
      <div>
        <p className="eyebrow"><Settings2 aria-hidden="true" size={14} /> Réglages locaux</p>
        <h1>Configuration</h1>
        <p>Quatre étapes avant validation et enregistrement sur cette machine.</p>
      </div>
    </header>
  );
}

function ListField({
  label,
  value,
  onChange,
  onRawChange,
  hint,
}: {
  label: string;
  value: string[];
  onChange: (value: string[]) => void;
  onRawChange: () => void;
  hint?: string;
}) {
  const [rawValue, setRawValue] = useState(() => listValue(value));

  useEffect(() => {
    setRawValue(listValue(value));
  }, [value]);

  const commit = () => {
    const parsed = parseList(rawValue);
    setRawValue(listValue(parsed));
    onChange(parsed);
  };

  return (
    <label className="config-field config-field-wide">
      <span>{label}</span>
      <textarea
        value={rawValue}
        onChange={(event) => {
          setRawValue(event.target.value);
          onRawChange();
        }}
        onBlur={commit}
        rows={2}
      />
      {hint ? <small>{hint}</small> : null}
    </label>
  );
}

type DraftChange = (config: AppConfig, invalidate?: boolean) => void;

function ProfileStep({
  config,
  onChange,
  onRawListChange,
}: {
  config: AppConfig;
  onChange: DraftChange;
  onRawListChange: () => void;
}) {
  const update = (
    field: keyof AppConfig["profile"],
    value: string | string[],
    invalidate = true,
  ) => {
    const next = cloneConfig(config);
    Object.assign(next.profile, { [field]: value });
    onChange(next, invalidate);
  };
  return (
    <div className="config-step">
      <div className="config-step-heading">
        <span>01</span><div><h2>Profil</h2><p>Décris le terrain professionnel à comparer.</p></div>
      </div>
      <div className="config-fields">
        <ListField label="Rôles visés" value={config.profile.roles} onChange={(value) => update("roles", value, false)} onRawChange={onRawListChange} hint="Sépare les valeurs par une virgule." />
        <ListField label="Compétences" value={config.profile.skills} onChange={(value) => update("skills", value, false)} onRawChange={onRawListChange} />
        <ListField label="Éléments de preuve" value={config.profile.evidence} onChange={(value) => update("evidence", value, false)} onRawChange={onRawListChange} />
        <ListField label="Langues" value={config.profile.languages} onChange={(value) => update("languages", value, false)} onRawChange={onRawListChange} />
        <label className="config-field">
          <span>Séniorité</span>
          <input value={config.profile.seniority} onChange={(event) => update("seniority", event.target.value)} />
        </label>
      </div>
    </div>
  );
}

function SearchStep({
  config,
  onChange,
  onRawListChange,
}: {
  config: AppConfig;
  onChange: DraftChange;
  onRawListChange: () => void;
}) {
  const update = (
    field: keyof AppConfig["search"],
    value: string | string[] | number,
    invalidate = true,
  ) => {
    const next = cloneConfig(config);
    Object.assign(next.search, { [field]: value });
    onChange(next, invalidate);
  };
  return (
    <div className="config-step">
      <div className="config-step-heading">
        <span>02</span><div><h2>Recherche</h2><p>Délimite les offres utiles sans opacifier les filtres.</p></div>
      </div>
      <div className="config-fields">
        <ListField label="Localisations" value={config.search.locations} onChange={(value) => update("locations", value, false)} onRawChange={onRawListChange} />
        <ListField label="Contrats" value={config.search.contracts} onChange={(value) => update("contracts", value, false)} onRawChange={onRawListChange} />
        <ListField label="Termes inclus" value={config.search.include_terms} onChange={(value) => update("include_terms", value, false)} onRawChange={onRawListChange} />
        <ListField label="Termes exclus" value={config.search.exclude_terms} onChange={(value) => update("exclude_terms", value, false)} onRawChange={onRawListChange} />
        <label className="config-field">
          <span>Télétravail</span>
          <select value={config.search.remote} onChange={(event) => update("remote", event.target.value)}>
            <option value="any">Indifférent</option>
            <option value="remote">À distance</option>
            <option value="hybrid">Hybride</option>
            <option value="onsite">Sur site</option>
          </select>
        </label>
        <label className="config-field">
          <span>Salaire minimum</span>
          <input type="number" min="0" step="1000" value={config.search.salary_minimum} onChange={(event) => update("salary_minimum", Number(event.target.value))} />
        </label>
      </div>
    </div>
  );
}

function WeightsStep({ config, onChange }: { config: AppConfig; onChange: (config: AppConfig) => void }) {
  const total = config.scoring.axes.reduce((sum, axis) => sum + axis.weight, 0);
  const update = (index: number, value: number) => {
    const next = cloneConfig(config);
    next.scoring.axes[index].weight = value;
    onChange(next);
  };
  return (
    <div className="config-step">
      <div className="config-step-heading">
        <span>03</span><div><h2>Poids</h2><p>Répartis exactement 100 points entre les axes existants.</p></div>
      </div>
      <div className="weight-total" data-valid={total === 100}>
        <span>Total</span><strong>{total}</strong><small>/ 100</small>
      </div>
      <div className="axis-list">
        {config.scoring.axes.map((axis, index) => (
          <label className="axis-field" key={axis.name}>
            <span>{axis.name.replaceAll("_", " ")}</span>
            <input aria-label={`Poids ${axis.name.replaceAll("_", " ")}`} type="number" min="0" max="100" value={axis.weight} onChange={(event) => update(index, Number(event.target.value))} />
          </label>
        ))}
      </div>
      {total !== 100 ? <p className="local-warning" role="status">Le total devra atteindre 100 pour être validé.</p> : null}
    </div>
  );
}

function disableUnavailableConnectors(
  config: AppConfig,
  sourceStatuses: Map<string, SourceStatus>,
): AppConfig {
  const safeConfig = cloneConfig(config);
  for (const [name, source] of Object.entries(safeConfig.sources.sources)) {
    if (source.mode !== "manual_only" && sourceStatuses.get(name)?.available === false) {
      source.enabled = false;
    }
  }
  return safeConfig;
}

function SourcesStep({
  config,
  onChange,
  sourceStatuses,
}: {
  config: AppConfig;
  onChange: (config: AppConfig) => void;
  sourceStatuses: Map<string, SourceStatus>;
}) {
  const update = (name: string, enabled: boolean) => {
    const next = cloneConfig(config);
    next.sources.sources[name].enabled = enabled;
    onChange(next);
  };
  const entries = Object.entries(config.sources.sources);
  return (
    <div className="config-step">
      <div className="config-step-heading">
        <span>04</span><div><h2>Sources</h2><p>Active les connecteurs locaux sans modifier leur politique.</p></div>
      </div>
      {entries.length ? (
        <div className="config-source-list">
          {entries.map(([name, source]) => {
            const unavailable = source.mode !== "manual_only" && sourceStatuses.get(name)?.available === false;
            return (
            <label className="config-source" key={name}>
              <input type="checkbox" checked={unavailable ? false : source.enabled} disabled={unavailable} onChange={(event) => update(name, event.target.checked)} aria-label={`Activer ${sourceLabels[name] ?? name}`} />
              <span aria-hidden="true" className="toggle-track"><i /></span>
              <span className="config-source-copy">
                <strong>{sourceLabels[name] ?? name.replaceAll("_", " ")}</strong>
                <small>{source.mode === "manual_only" ? "Import manuel uniquement" : unavailable ? "Indisponible dans cette version" : source.mode === "ats" ? "ATS public" : `API · quota ${source.quota_per_day}/jour`}</small>
              </span>
            </label>
            );
          })}
        </div>
      ) : (
        <p className="inline-empty">Aucune source dans ce document.</p>
      )}
    </div>
  );
}

function ValidationErrors({ errors }: { errors: ValidationIssue[] }) {
  return (
    <div className="validation-errors" role="alert">
      <strong>Le document doit être corrigé</strong>
      <ul>{errors.map((error) => <li key={`${error.path}-${error.message}`}><code>{error.path || "configuration"}</code> {error.message}</li>)}</ul>
    </div>
  );
}

export function ConfigurationPage() {
  const session = useSession();
  const queryClient = useQueryClient();
  const configQuery = useQuery({ queryKey: ["config"], queryFn: fetchConfig });
  const sourcesQuery = useQuery({ queryKey: ["sources"], queryFn: fetchSources });
  const [draft, setDraft] = useState<AppConfig | null>(null);
  const [step, setStep] = useState(0);
  const [preview, setPreview] = useState<Array<{ name: string; content: string }> | null>(null);
  const [validatedDraft, setValidatedDraft] = useState<AppConfig | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationIssue[]>([]);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [saved, setSaved] = useState<number | null>(null);
  const [configWritten, setConfigWritten] = useState(false);
  const draftRevision = useRef(0);
  const saveTriggerRef = useRef<HTMLButtonElement>(null);
  const sourceStatuses = useMemo(
    () => new Map((sourcesQuery.data ?? []).map((source) => [source.name, source])),
    [sourcesQuery.data],
  );

  useEffect(() => {
    if (configQuery.data && !draft) setDraft(cloneConfig(configQuery.data));
  }, [configQuery.data, draft]);

  const validation = useMutation({
    mutationFn: ({ config }: { config: AppConfig; revision: number }) => validateConfig(config),
    onMutate: () => {
      setPreview(null);
      setValidatedDraft(null);
      setValidationErrors([]);
      setSaved(null);
    },
    onSuccess: async (result, request) => {
      if (request.revision !== draftRevision.current) return;
      if (!result.valid) {
        setValidationErrors(result.errors);
        return;
      }
      const documents = await yamlDocuments(request.config);
      if (request.revision !== draftRevision.current) return;
      setValidationErrors(result.errors);
      setValidatedDraft(cloneConfig(request.config));
      setPreview(documents);
    },
  });
  const save = useMutation({
    mutationFn: async ({
      config,
      rescoreOnly = false,
    }: {
      config: AppConfig;
      rescoreOnly?: boolean;
    }) =>
      session.runAuthenticated(async (token) => {
        if (!rescoreOnly) {
          await writeConfig(config, token);
          setConfigWritten(true);
        }
        return rescoreOffers(token);
      }),
    onMutate: ({ rescoreOnly = false }) => {
      if (!rescoreOnly) setConfigWritten(false);
      setSaved(null);
    },
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["config"] }),
        queryClient.invalidateQueries({ queryKey: ["offers"] }),
        queryClient.invalidateQueries({ queryKey: ["offer"] }),
        queryClient.invalidateQueries({ queryKey: ["market-insights"] }),
      ]);
      setConfirmOpen(false);
      setConfigWritten(false);
      setSaved(result.offers_scored);
    },
  });

  const invalidateDraft = () => {
    draftRevision.current += 1;
    setPreview(null);
    setValidatedDraft(null);
    setValidationErrors([]);
    setSaved(null);
  };

  const activeStep = useMemo(() => {
    if (!draft) return null;
    const onChange: DraftChange = (next, invalidate = true) => {
      if (invalidate) invalidateDraft();
      setDraft(next);
    };
    if (step === 0) {
      return <ProfileStep config={draft} onChange={onChange} onRawListChange={invalidateDraft} />;
    }
    if (step === 1) {
      return <SearchStep config={draft} onChange={onChange} onRawListChange={invalidateDraft} />;
    }
    if (step === 2) return <WeightsStep config={draft} onChange={onChange} />;
    return <SourcesStep config={draft} onChange={onChange} sourceStatuses={sourceStatuses} />;
  }, [draft, sourceStatuses, step]);

  if (configQuery.isError) {
    return (
      <section className="secondary-page">
        <PageHeading />
        <div className="secondary-state" role="alert">
          <AlertTriangle aria-hidden="true" size={24} />
          <h2>Impossible de charger la configuration</h2>
          <p>Le service local n’a pas répondu.</p>
          <button type="button" onClick={() => void configQuery.refetch()}>Réessayer</button>
        </div>
      </section>
    );
  }

  if (configQuery.isPending || !draft) {
    return (
      <section className="secondary-page">
        <PageHeading />
        <div className="secondary-state secondary-loading" role="status" aria-label="Chargement de la configuration">
          <span aria-hidden="true" /><p>Lecture des fichiers locaux…</p>
        </div>
      </section>
    );
  }

  return (
    <section className="secondary-page configuration-page">
      <PageHeading />
      <div className="wizard-layout">
        <nav className="step-navigation" aria-label="Étapes de configuration">
          <ol>
            {steps.map((label, index) => (
              <li key={label} data-active={index === step} data-complete={index < step || Boolean(preview)}>
                <button type="button" onClick={() => setStep(index)} aria-current={index === step ? "step" : undefined}>
                  <span>{index < step || preview ? <Check aria-hidden="true" size={13} /> : index + 1}</span>
                  {label}
                </button>
              </li>
            ))}
          </ol>
          <p><FileCheck2 aria-hidden="true" size={15} /> Les sections non affichées restent inchangées.</p>
        </nav>

        <div className="wizard-main">
          <form onSubmit={(event) => event.preventDefault()}>{activeStep}</form>

          {validationErrors.length ? <ValidationErrors errors={validationErrors} /> : null}
          {validation.isError ? <div className="validation-errors" role="alert">La validation locale a échoué.</div> : null}

          {preview ? (
            <section className="yaml-preview" aria-label="Aperçu YAML">
              <div className="section-heading">
                <div><p className="section-kicker">Validation réussie</p><h2>Aperçu YAML</h2></div>
                <FileCheck2 aria-hidden="true" size={20} />
              </div>
              <div className="yaml-files">
                {preview.map((document) => (
                  <details key={document.name} open={document.name === "profile.yml"}>
                    <summary>{document.name}</summary>
                    <pre>{document.content}</pre>
                  </details>
                ))}
              </div>
              <div className="preview-actions">
                <p>{session.isAvailable ? "Prêt pour l’écriture locale." : "Session locale indisponible : écriture désactivée."}</p>
                <button
                  ref={saveTriggerRef}
                  className="primary-button"
                  type="button"
                  disabled={!session.isAvailable || !validatedDraft || save.isPending}
                  onClick={() => {
                    save.reset();
                    setConfigWritten(false);
                    setConfirmOpen(true);
                  }}
                >
                  <Save aria-hidden="true" size={16} /> Enregistrer localement
                </button>
              </div>
            </section>
          ) : null}

          {saved !== null ? <p className="save-success" role="status"><Check aria-hidden="true" size={16} /> Configuration enregistrée et {saved} offres recalculées.</p> : null}

          <div className="wizard-actions">
            <button type="button" className="secondary-button" disabled={step === 0} onClick={() => setStep((current) => Math.max(0, current - 1))}>
              <ChevronLeft aria-hidden="true" size={16} /> Précédent
            </button>
            {step < steps.length - 1 ? (
              <button type="button" className="primary-button" onClick={() => setStep((current) => Math.min(steps.length - 1, current + 1))}>
                Suivant <ChevronRight aria-hidden="true" size={16} />
              </button>
            ) : (
              <button
                type="button"
                className="primary-button"
                disabled={validation.isPending}
                onClick={() => {
                  const snapshot = disableUnavailableConnectors(
                    normalizeEditableLists(draft),
                    sourceStatuses,
                  );
                  validation.mutate({ config: snapshot, revision: draftRevision.current });
                }}
              >
                <FileCheck2 aria-hidden="true" size={16} /> {validation.isPending ? "Validation…" : "Valider et afficher l’aperçu"}
              </button>
            )}
          </div>
        </div>
      </div>

      <Dialog.Root
        open={confirmOpen}
        onOpenChange={(open) => {
          if (!open && save.isPending) return;
          if (open) {
            save.reset();
            setConfigWritten(false);
          }
          setConfirmOpen(open);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content
            className="confirm-dialog"
            aria-describedby="config-confirm-description"
            onEscapeKeyDown={(event) => {
              if (save.isPending) event.preventDefault();
            }}
            onPointerDownOutside={(event) => {
              if (save.isPending) event.preventDefault();
            }}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              saveTriggerRef.current?.focus();
            }}
          >
            <Dialog.Close className="dialog-close" aria-label="Fermer" disabled={save.isPending}><X aria-hidden="true" size={17} /></Dialog.Close>
            <Dialog.Title>Confirmer l’enregistrement</Dialog.Title>
            <Dialog.Description id="config-confirm-description">La configuration active sera remplacée, puis les offres locales seront recalculées avec cette grille.</Dialog.Description>
            {save.isError ? (
              <div className="dialog-save-error" role="alert">
                <p>{configWritten ? "Configuration enregistrée, mais le recalcul a échoué." : "L’enregistrement local a échoué."}</p>
                <button
                  className="secondary-button"
                  type="button"
                  disabled={!session.isAvailable || !validatedDraft || save.isPending}
                  onClick={() => validatedDraft && save.mutate({ config: validatedDraft, rescoreOnly: configWritten })}
                >
                  {configWritten ? "Réessayer le recalcul" : "Réessayer"}
                </button>
              </div>
            ) : null}
            <div className="confirm-actions">
              <Dialog.Close className="secondary-button" disabled={save.isPending}>Annuler</Dialog.Close>
              {!save.isError ? (
                <button
                  className="primary-button"
                  type="button"
                  disabled={!session.isAvailable || !validatedDraft || save.isPending}
                  onClick={() => validatedDraft && save.mutate({ config: validatedDraft })}
                >
                  {save.isPending ? "Enregistrement…" : "Confirmer"}
                </button>
              ) : null}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}
