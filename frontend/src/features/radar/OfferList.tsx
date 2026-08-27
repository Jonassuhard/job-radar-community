import { Building2, ChevronRight, Clock3, MapPin } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

import type { Offer } from "../../lib/api";

const decisionLabels: Record<string, string> = {
  prioritize: "À prioriser",
  review: "À examiner",
  monitor: "À surveiller",
  reject: "Écartée",
};

const sourceLabels: Record<string, string> = {
  france_travail: "France Travail",
  public_ats: "ATS public",
  adzuna: "Adzuna",
  jooble: "Jooble",
  remotive: "Remotive",
};

type OfferListProps = {
  offers: Offer[];
  selectedId: number | null;
  comparedIds: number[];
  onOpen: (id: number, trigger: HTMLButtonElement) => void;
  onToggleCompare: (id: number) => void;
};

export function OfferList({ offers, selectedId, comparedIds, onOpen, onToggleCompare }: OfferListProps) {
  const reduceMotion = useReducedMotion();

  return (
    <div className="offer-list" aria-label="Offres classées">
      {offers.map((offer, index) => {
        const isCompared = comparedIds.includes(offer.id);
        const compareLimitReached = comparedIds.length >= 3 && !isCompared;
        return (
          <motion.article
            className={`offer-row${selectedId === offer.id ? " selected" : ""}`}
            data-decision={offer.decision}
            data-offer-id={offer.id}
            key={offer.id}
            initial={reduceMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, delay: reduceMotion ? 0 : Math.min(index * 0.035, 0.2) }}
          >
            <div className="offer-score" aria-label={`Pertinence ${offer.relevance} sur 100`}>
              <strong>{offer.relevance}</strong>
              <span>/100</span>
            </div>

            <button className="offer-open" type="button" onClick={(event) => onOpen(offer.id, event.currentTarget)} aria-label={`Ouvrir ${offer.title}`}>
              <span className="offer-title-line">
                <strong>{offer.title}</strong>
                <span className="decision-label">{decisionLabels[offer.decision] ?? offer.decision}</span>
              </span>
              <span className="offer-meta">
                <span><Building2 aria-hidden="true" size={14} />{offer.company}</span>
                <span><MapPin aria-hidden="true" size={14} />{offer.location}</span>
                <span><Clock3 aria-hidden="true" size={14} />{offer.freshness_days === 0 ? "Aujourd'hui" : `${offer.freshness_days} j`}</span>
              </span>
              <span className="offer-reason">
                {offer.axes[0]?.explanation ?? "Score calculé selon la grille locale."}
              </span>
              <span className="offer-source">{sourceLabels[offer.source] ?? offer.source}</span>
              <ChevronRight className="row-chevron" aria-hidden="true" size={18} />
            </button>

            <label className="compare-check">
              <input
                type="checkbox"
                checked={isCompared}
                disabled={compareLimitReached}
                onChange={() => onToggleCompare(offer.id)}
              />
              <span>Comparer {offer.title}</span>
            </label>
          </motion.article>
        );
      })}
    </div>
  );
}
