import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CloudDownload,
  Database,
  FileInput,
  FileSearch,
  Inbox,
  KeyRound,
  Upload,
} from "lucide-react";
import { useState } from "react";

import { useSession } from "../../app/SessionContext";
import {
  fetchSources,
  importOfferFile,
  type ImportResponse,
  type SourceStatus,
} from "../../lib/api";

const MAX_IMPORT_BYTES = 2 * 1024 * 1024;

const sourceNames: Record<string, string> = {
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

const healthLabels: Record<string, string> = {
  ok: "Opérationnelle",
  not_run: "Pas encore exécutée",
  skipped: "Ignorée",
  failed: "En erreur",
};

function displayName(name: string) {
  return sourceNames[name] ?? name.replaceAll("_", " ");
}

function lastRun(value: string | null) {
  if (!value) return "Jamais";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date inconnue";
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

type SourceKind = "connector" | "manual" | "stored";

function SourceRow({ source, kind }: { source: SourceStatus; kind: SourceKind }) {
  const manual = kind === "manual";
  const stored = kind === "stored";
  const unavailable = kind === "connector" && !source.available;

  return (
    <article className="source-row">
      <div className="source-identity">
        <span className="source-icon" aria-hidden="true">
          {manual ? <FileInput size={18} /> : stored ? <Database size={18} /> : <CloudDownload size={18} />}
        </span>
        <div>
          <h3>{displayName(source.name)}</h3>
          <p>{manual ? "Import manuel uniquement" : stored ? "Import ou historique local" : unavailable ? "Connecteur configuré" : source.mode === "ats" ? "Flux ATS public" : "API autorisée"}</p>
        </div>
      </div>
      <span className={`source-state source-state-${source.health_status}`}>
        {manual ? "Manuel" : stored ? "Stockée localement" : unavailable ? "Indisponible dans cette version" : source.enabled ? healthLabels[source.health_status] ?? source.health_status : "Désactivée"}
      </span>
      {manual ? (
        <p className="source-policy">Aucune collecte automatique. Les offres sont ajoutées par fichier local.</p>
      ) : stored ? (
        <p className="source-policy">Import ou historique local. Aucun connecteur distant, quota ou clé n’est requis.</p>
      ) : unavailable ? (
        <p className="source-policy">Configuration, quota et identifiants éventuels sont conservés localement. Aucun connecteur distant n’est livré.</p>
      ) : (
        <dl className="source-facts">
          <div><dt>Quota restant</dt><dd>{source.quota_remaining === null ? "Non communiqué" : `${source.quota_remaining} / ${source.quota_per_day}`}</dd></div>
          <div><dt>Dernier succès</dt><dd>{lastRun(source.last_success_at)}</dd></div>
          <div>
            <dt>Accès</dt>
            <dd><KeyRound aria-hidden="true" size={13} /> {source.credential_configured ? "Configuré" : "Variable requise"}</dd>
          </div>
        </dl>
      )}
    </article>
  );
}

function PageHeading() {
  return (
    <header className="secondary-heading">
      <div>
        <p className="eyebrow"><Database aria-hidden="true" size={14} /> Provenance</p>
        <h1>Sources</h1>
        <p>État des connecteurs configurés et des canaux d’import local.</p>
      </div>
    </header>
  );
}

export function SourcesPage() {
  const query = useQuery({ queryKey: ["sources"], queryFn: fetchSources });
  const session = useSession();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResponse | null>(null);
  const importMutation = useMutation({
    mutationFn: async ({ preview }: { preview: boolean }) => {
      if (!file) throw new Error("Sélectionnez un fichier JSON.");
      if (file.size > MAX_IMPORT_BYTES) throw new Error("Le fichier dépasse 2 MiB.");
      return session.runAuthenticated((token) => importOfferFile(file, token, preview));
    },
    onSuccess: (payload) => {
      setClientError(null);
      setResult(payload);
      if (!payload.preview) {
        void Promise.all([
          queryClient.invalidateQueries({ queryKey: ["offers"] }),
          queryClient.invalidateQueries({ queryKey: ["market-insights"] }),
          queryClient.invalidateQueries({ queryKey: ["sources"] }),
        ]);
      }
    },
  });

  function chooseFile(next: File | null) {
    setFile(next);
    setResult(null);
    importMutation.reset();
    setClientError(
      next && next.size > MAX_IMPORT_BYTES ? "Le fichier dépasse 2 MiB." : null,
    );
  }

  function runImport(preview: boolean) {
    if (clientError) return;
    importMutation.mutate({ preview });
  }
  const importError = clientError ?? importMutation.error?.message ?? null;

  if (query.isPending) {
    return (
      <section className="secondary-page">
        <PageHeading />
        <div className="secondary-state secondary-loading" role="status" aria-label="Chargement des sources">
          <span aria-hidden="true" />
          <p>Lecture de la santé des sources…</p>
        </div>
      </section>
    );
  }

  if (query.isError) {
    return (
      <section className="secondary-page">
        <PageHeading />
        <div className="secondary-state" role="alert">
          <AlertTriangle aria-hidden="true" size={24} />
          <h2>Impossible de charger les sources</h2>
          <p>Le service local n’a pas répondu.</p>
          <button type="button" onClick={() => void query.refetch()}>Réessayer</button>
        </div>
      </section>
    );
  }

  if (query.data.length === 0) {
    return (
      <section className="secondary-page">
        <PageHeading />
        <div className="secondary-state" role="status" aria-label="Aucune source configurée">
          <Inbox aria-hidden="true" size={25} />
          <h2>Aucune source configurée</h2>
          <p>Ajoutez une source depuis la configuration locale.</p>
        </div>
      </section>
    );
  }

  const connectors = query.data.filter((source) => source.mode === "api" || source.mode === "ats");
  const manual = query.data.filter((source) => source.mode === "manual_only");
  const stored = query.data.filter((source) => source.mode === "stored");

  return (
    <section className="secondary-page sources-page">
      <PageHeading />
      <div className="source-summary" aria-label="Résumé des sources">
        <span><strong>{connectors.length}</strong> connecteurs configurés</span>
        <span><strong>{manual.length}</strong> imports manuels</span>
        <span><strong>{stored.length}</strong> sources locales</span>
        <span><strong>{connectors.filter((source) => source.automated).length}</strong> actifs</span>
      </div>

      <section className="source-group" aria-label="Connecteurs configurés">
        <div className="section-heading">
          <div>
            <p className="section-kicker">Connecteurs configurés</p>
            <h2>Connecteurs configurés</h2>
          </div>
          <CloudDownload aria-hidden="true" size={20} />
        </div>
        <div className="source-list">
          {connectors.length ? connectors.map((source) => <SourceRow key={source.name} source={source} kind="connector" />) : <p className="inline-empty">Aucun connecteur configuré.</p>}
        </div>
      </section>

      {stored.length ? (
        <section className="source-group" aria-label="Sources stockées localement">
          <div className="section-heading">
            <div>
              <p className="section-kicker">Données locales</p>
              <h2>Sources stockées localement</h2>
            </div>
            <Database aria-hidden="true" size={20} />
          </div>
          <p className="group-note">Ces sources viennent d’un import ou de l’historique local et ne déclenchent aucun connecteur distant.</p>
          <div className="source-list">
            {stored.map((source) => <SourceRow key={source.name} source={source} kind="stored" />)}
          </div>
        </section>
      ) : null}

      <section className="source-group manual-source-group" aria-label="Imports manuels">
        <div className="section-heading">
          <div>
            <p className="section-kicker">Canaux protégés</p>
            <h2>Imports manuels</h2>
          </div>
          <FileInput aria-hidden="true" size={20} />
        </div>
        <p className="group-note">Ces plateformes ne sont jamais interrogées automatiquement.</p>
        <div className="manual-import-tool">
          <label className="import-file-field">
            <span>Fichier JSON d’offres</span>
            <input
              type="file"
              accept=".json,application/json"
              aria-label="Fichier JSON d’offres"
              onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
            />
            <small>{file ? file.name : "JSON · 2 MiB max · 500 offres"}</small>
          </label>
          <div className="import-actions">
            <button
              className="secondary-button"
              type="button"
              disabled={!file || !session.isAvailable || importMutation.isPending || Boolean(clientError)}
              onClick={() => runImport(true)}
            >
              <FileSearch aria-hidden="true" size={15} /> Prévisualiser l’import
            </button>
            <button
              className="primary-button"
              type="button"
              disabled={!file || !session.isAvailable || importMutation.isPending || Boolean(clientError)}
              onClick={() => runImport(false)}
            >
              <Upload aria-hidden="true" size={15} /> Importer les offres
            </button>
          </div>
          {importError ? (
            <p className="import-message import-error" role="alert">
              {importError}
            </p>
          ) : result ? (
            <p className="import-message" role="status" aria-label="Résultat de l’import">
              {result.preview
                ? `${result.offers_seen} offre${result.offers_seen > 1 ? "s" : ""} valide${result.offers_seen > 1 ? "s" : ""}, ${result.offers_saved} serait${result.offers_saved > 1 ? "ent" : ""} enregistrée${result.offers_saved > 1 ? "s" : ""}.`
                : `${result.offers_saved} offre${result.offers_saved > 1 ? "s" : ""} importée${result.offers_saved > 1 ? "s" : ""}.`}
            </p>
          ) : null}
        </div>
        <div className="source-list">
          {manual.length ? manual.map((source) => <SourceRow key={source.name} source={source} kind="manual" />) : <p className="inline-empty">Aucun canal manuel configuré.</p>}
        </div>
      </section>
    </section>
  );
}
