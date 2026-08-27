import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeftRight, ChevronLeft, ChevronRight, Inbox, Radar as RadarIcon, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchOffer, fetchOffers, fetchSources } from "../../lib/api";
import { CompareDialog } from "./CompareDialog";
import { Filters, type RadarFilters } from "./Filters";
import { OfferDetail } from "./OfferDetail";
import { OfferList } from "./OfferList";

const PAGE_SIZE = 25;
const filterKeys: (keyof RadarFilters)[] = ["q", "decision", "source", "min_score", "remote", "sort"];

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const media = window.matchMedia(query);
    const update = (event: MediaQueryListEvent) => setMatches(event.matches);
    setMatches(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);

  return matches;
}

function LoadingState() {
  return (
    <div className="loading-state" role="status" aria-label="Chargement des offres">
      <span className="sr-only">Chargement des offres</span>
      {Array.from({ length: 5 }, (_, index) => (
        <div className="offer-skeleton" data-testid="offer-skeleton" key={index}>
          <span /><div><i /><i /><i /></div>
        </div>
      ))}
    </div>
  );
}

export function RadarPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [comparedIds, setComparedIds] = useState<number[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const compactDetail = useMediaQuery("(max-width: 1020px)");
  const detailCloseRef = useRef<HTMLButtonElement>(null);
  const detailTriggerRef = useRef<HTMLButtonElement | null>(null);

  const filters = useMemo<RadarFilters>(
    () => ({
      q: searchParams.get("q") ?? "",
      decision: searchParams.get("decision") ?? "",
      source: searchParams.get("source") ?? "",
      min_score: searchParams.get("min_score") ?? "",
      remote: searchParams.get("remote") ?? "",
      sort: searchParams.get("sort") ?? "relevance_desc",
    }),
    [searchParams],
  );
  const offset = Math.max(0, Number.parseInt(searchParams.get("offset") ?? "0", 10) || 0);

  const apiSearch = useMemo(() => {
    const params = new URLSearchParams();
    for (const key of filterKeys) {
      const value = filters[key];
      if (value && !(key === "sort" && value === "relevance_desc")) params.set(key, value);
    }
    params.set("limit", String(PAGE_SIZE));
    if (offset) params.set("offset", String(offset));
    return params.toString();
  }, [filters, offset]);

  const offersQuery = useQuery({
    queryKey: ["offers", apiSearch],
    queryFn: () => fetchOffers(apiSearch),
  });
  const sourcesQuery = useQuery({ queryKey: ["sources"], queryFn: fetchSources });
  const detailQuery = useQuery({
    queryKey: ["offer", selectedId],
    queryFn: () => fetchOffer(selectedId!),
    enabled: selectedId !== null,
  });

  function updateFilter(key: keyof RadarFilters, value: string) {
    const next = new URLSearchParams(searchParams);
    if (!value || (key === "sort" && value === "relevance_desc")) next.delete(key);
    else next.set(key, value);
    next.delete("offset");
    setSearchParams(next, { replace: true });
  }

  function clearFilters() {
    setSearchParams({}, { replace: true });
  }

  function changePage(nextOffset: number) {
    const next = new URLSearchParams(searchParams);
    if (nextOffset <= 0) next.delete("offset");
    else next.set("offset", String(nextOffset));
    setSearchParams(next);
  }

  function toggleComparison(id: number) {
    setComparedIds((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id);
      return current.length < 3 ? [...current, id] : current;
    });
  }

  function openDetail(id: number, trigger: HTMLButtonElement) {
    detailTriggerRef.current = trigger;
    setSelectedId(id);
  }

  function closeDetail() {
    setSelectedId(null);
  }

  const page = offersQuery.data;
  const sourceOptions = useMemo(() => {
    const configuredSources = Array.isArray(sourcesQuery.data) ? sourcesQuery.data : [];
    const names = new Set(configuredSources.map((source) => source.name));
    for (const offer of page?.items ?? []) {
      names.add(offer.source);
      for (const provenance of offer.provenance) names.add(provenance.source);
    }
    if (filters.source) names.add(filters.source);
    return [...names].sort((left, right) => left.localeCompare(right, "fr"));
  }, [filters.source, page?.items, sourcesQuery.data]);
  const shownFrom = page && page.total > 0 ? page.offset + 1 : 0;
  const shownTo = page ? Math.min(page.offset + page.items.length, page.total) : 0;
  const isDemo = page?.items.some((offer) => offer.score_version.startsWith("demo"));
  const selectedTitle =
    detailQuery.data?.title ??
    page?.items.find((offer) => offer.id === selectedId)?.title ??
    "Offre";
  const detailContent =
    selectedId === null ? null : detailQuery.isPending ? (
      <div className="detail-loading" role="status">Chargement du détail…</div>
    ) : detailQuery.isError ? (
      <div className="state-panel error-state" role="alert"><AlertTriangle aria-hidden="true" size={20} /><h3>Détail indisponible</h3><button type="button" onClick={() => detailQuery.refetch()}>Réessayer</button></div>
    ) : detailQuery.data ? (
      <OfferDetail offer={detailQuery.data} onClose={closeDetail} hideCloseButton={compactDetail} />
    ) : null;

  return (
    <div className={`radar-page${selectedId !== null ? " has-detail" : ""}`}>
      <header className="radar-heading">
        <div>
          <p className="eyebrow"><RadarIcon aria-hidden="true" size={15} />Classement local</p>
          <div className="title-line">
            <h1>Radar</h1>
            {isDemo && <span className="demo-badge">Mode démo</span>}
          </div>
          <p>Des offres comparables, classées et expliquées par votre grille.</p>
        </div>
        {page && (
          <div className="corpus-count" aria-label={`${page.total} offres trouvées`}>
            <strong>{page.total}</strong><span>offres actives</span>
          </div>
        )}
      </header>

      <Filters values={filters} sources={sourceOptions} onChange={updateFilter} onReset={clearFilters} />

      <div className="radar-workspace">
        <section className="results-panel" aria-labelledby="results-title">
          <header className="results-toolbar">
            <div>
              <h2 id="results-title">Résultats</h2>
              {page && <span>{shownFrom}–{shownTo} sur {page.total}</span>}
            </div>
            {comparedIds.length > 0 && (
              <div className="compare-bar">
                <button className="clear-selection" type="button" onClick={() => setComparedIds([])} aria-label="Vider la sélection" title="Vider la sélection"><X aria-hidden="true" size={15} /></button>
                <span>{comparedIds.length} sur 3 sélectionnées</span>
                <button className="primary-button" type="button" onClick={() => setCompareOpen(true)}>
                  <ArrowLeftRight aria-hidden="true" size={16} />Comparer {comparedIds.length} offre{comparedIds.length > 1 ? "s" : ""}
                </button>
              </div>
            )}
          </header>

          {offersQuery.isPending && <LoadingState />}
          {offersQuery.isError && (
            <div className="state-panel error-state" role="alert">
              <AlertTriangle aria-hidden="true" size={22} />
              <div><h3>Impossible de charger le radar</h3><p>Vérifiez que l’API locale est démarrée.</p></div>
              <button type="button" onClick={() => offersQuery.refetch()}>Réessayer</button>
            </div>
          )}
          {page && page.items.length === 0 && (
            <div className="state-panel empty-state">
              <Inbox aria-hidden="true" size={24} />
              <h3>Aucune offre dans ce secteur du radar</h3>
              <p>Élargissez les critères pour retrouver des résultats.</p>
              <button type="button" onClick={clearFilters}>Effacer les filtres</button>
            </div>
          )}
          {page && page.items.length > 0 && (
            <OfferList
              offers={page.items}
              selectedId={selectedId}
              comparedIds={comparedIds}
              onOpen={openDetail}
              onToggleCompare={toggleComparison}
            />
          )}

          {page && page.total > page.limit && (
            <nav className="pagination" aria-label="Pagination des offres">
              <button type="button" onClick={() => changePage(Math.max(0, offset - page.limit))} disabled={offset === 0} aria-label="Page précédente"><ChevronLeft aria-hidden="true" size={17} />Précédente</button>
              <span>Page {Math.floor(offset / page.limit) + 1} / {Math.ceil(page.total / page.limit)}</span>
              <button type="button" onClick={() => changePage(offset + page.limit)} disabled={offset + page.limit >= page.total} aria-label="Page suivante">Suivante<ChevronRight aria-hidden="true" size={17} /></button>
            </nav>
          )}
        </section>

        {!compactDetail && (
          <aside className="detail-panel" aria-live="polite">
            {selectedId === null ? (
              <div className="detail-placeholder"><RadarIcon aria-hidden="true" size={25} /><p>Sélectionnez une offre pour lire les raisons du score.</p></div>
            ) : detailContent}
          </aside>
        )}
      </div>

      {compactDetail && (
        <Dialog.Root open={selectedId !== null} onOpenChange={(open) => !open && closeDetail()}>
          <Dialog.Portal>
            <Dialog.Overlay className="detail-dialog-overlay" />
            <Dialog.Content
              className="mobile-detail-content"
              onOpenAutoFocus={(event) => {
                event.preventDefault();
                detailCloseRef.current?.focus();
              }}
              onCloseAutoFocus={(event) => {
                event.preventDefault();
                detailTriggerRef.current?.focus();
              }}
            >
              <Dialog.Title className="sr-only">Détail de l'offre : {selectedTitle}</Dialog.Title>
              <Dialog.Description className="sr-only">Score, faits et provenance de l'offre sélectionnée.</Dialog.Description>
              <Dialog.Close asChild>
                <button ref={detailCloseRef} className="icon-button mobile-detail-close" type="button" aria-label="Fermer le détail" title="Fermer">
                  <X aria-hidden="true" size={19} />
                </button>
              </Dialog.Close>
              {detailContent}
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      )}

      <CompareDialog ids={comparedIds} open={compareOpen} onOpenChange={setCompareOpen} />
    </div>
  );
}
