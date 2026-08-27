import { useMutation } from "@tanstack/react-query";
import { Check, CircleAlert, Database, ExternalLink, MapPin, MessageSquare, X } from "lucide-react";

import { useSession } from "../../app/SessionContext";
import { createFeedback, type Offer } from "../../lib/api";

const humanize: Record<string, string> = {
  role: "Métier",
  skills: "Compétences",
  permanent: "CDI",
  fixed_term: "CDD",
  contract: "Contrat",
  apprenticeship: "Alternance",
  remote: "À distance",
  hybrid: "Hybride",
  onsite: "Sur site",
};

type OfferDetailProps = {
  offer: Offer;
  onClose: () => void;
  hideCloseButton?: boolean;
};

export function OfferDetail({
  offer,
  onClose,
  hideCloseButton = false,
}: OfferDetailProps) {
  const session = useSession();
  const feedback = useMutation({
    mutationFn: (value: string) =>
      session.runAuthenticated((token) => createFeedback(offer.id, value, token)),
  });

  return (
    <section className="offer-detail" role="region" aria-label="Détail de l'offre">
      <header className="detail-header">
        <div>
          <p className="eyebrow">Explication du score</p>
          <h2>{offer.title}</h2>
          <p>{offer.company}</p>
        </div>
        {!hideCloseButton && (
          <button className="icon-button detail-close" type="button" onClick={onClose} aria-label="Fermer le détail" title="Fermer">
            <X aria-hidden="true" size={19} />
          </button>
        )}
      </header>

      <div className="detail-summary">
        <div className="detail-score">
          <strong>{offer.relevance}</strong>
          <span>pertinence</span>
        </div>
        <dl>
          <div><dt>Confiance</dt><dd>{offer.confidence}%</dd></div>
          <div><dt>Fraîcheur</dt><dd>{offer.freshness_days === 0 ? "Aujourd'hui" : `${offer.freshness_days} jours`}</dd></div>
          <div><dt>Version</dt><dd>{offer.score_version}</dd></div>
        </dl>
      </div>

      <div className="detail-tags">
        <span><MapPin aria-hidden="true" size={14} />{offer.location}</span>
        <span>{humanize[offer.contract] ?? offer.contract}</span>
        <span>{humanize[offer.remote] ?? offer.remote}</span>
      </div>

      <div className="detail-source-action">
        <a href={offer.url} target="_blank" rel="noreferrer">
          Voir l'annonce source <ExternalLink aria-hidden="true" size={15} />
        </a>
      </div>

      {offer.blocker && (
        <div className="blocker"><CircleAlert aria-hidden="true" size={17} /><span>Point bloquant: {offer.blocker.replaceAll("_", " ")}</span></div>
      )}

      <section className="detail-section" aria-labelledby="axes-title">
        <div className="section-title"><h3 id="axes-title">Axes de score</h3><span>{offer.axes.length}</span></div>
        <div className="axis-list">
          {offer.axes.map((axis) => (
            <article key={axis.name}>
              <div><strong>{humanize[axis.name] ?? axis.name}</strong><b>+{axis.points}</b></div>
              <p>{axis.explanation}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="detail-section" aria-labelledby="facts-title">
        <div className="section-title"><h3 id="facts-title">Faits vérifiables</h3><span>{offer.facts.length}</span></div>
        <div className="fact-list">
          {offer.facts.map((fact, index) => (
            <blockquote key={`${fact.name}-${fact.value}-${index}`}>
              <p>{fact.citation}</p>
              <footer><Check aria-hidden="true" size={14} />{fact.value} · confiance {fact.confidence}%</footer>
            </blockquote>
          ))}
        </div>
      </section>

      <section className="provenance" aria-labelledby="provenance-title">
        <h3 id="provenance-title"><Database aria-hidden="true" size={16} />Provenance</h3>
        <ul>
          {offer.provenance.map((item) => (
            <li key={`${item.source}-${item.external_id}`}>
              <a href={item.url} target="_blank" rel="noreferrer">
                {item.source.replaceAll("_", " ")} · {item.external_id}
                <ExternalLink aria-hidden="true" size={12} />
              </a>
            </li>
          ))}
        </ul>
      </section>

      <section className="feedback" aria-labelledby="feedback-title">
        <h3 id="feedback-title"><MessageSquare aria-hidden="true" size={16} />Donner un avis</h3>
        <p className="feedback-note">Cet avis n'influence pas encore le score. Il reste stocké localement pour une analyse future.</p>
        {session.isPending ? (
          <p className="feedback-unavailable">Initialisation de la session locale…</p>
        ) : !session.isAvailable ? (
          <>
            <p className="feedback-unavailable">Feedback indisponible sans session locale.</p>
            <div className="feedback-actions">
              <button type="button" disabled>Pertinente</button>
              <button type="button" disabled>À revoir</button>
              <button type="button" disabled>Non pertinente</button>
            </div>
          </>
        ) : feedback.isSuccess ? (
          <p className="feedback-success" role="status"><Check aria-hidden="true" size={16} />Avis enregistré localement</p>
        ) : (
          <>
            <div className="feedback-actions">
              <button type="button" onClick={() => feedback.mutate("relevant")} disabled={feedback.isPending}>Pertinente</button>
              <button type="button" onClick={() => feedback.mutate("review")} disabled={feedback.isPending}>À revoir</button>
              <button type="button" onClick={() => feedback.mutate("not_relevant")} disabled={feedback.isPending}>Non pertinente</button>
            </div>
            {feedback.isError && <p className="feedback-error" role="alert">Le retour n'a pas pu être enregistré.</p>}
          </>
        )}
      </section>
    </section>
  );
}
