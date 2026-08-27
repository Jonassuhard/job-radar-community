import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, X } from "lucide-react";

import { compareOffers } from "../../lib/api";

type CompareDialogProps = {
  ids: number[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function CompareDialog({ ids, open, onOpenChange }: CompareDialogProps) {
  const comparison = useQuery({
    queryKey: ["offers", "compare", ids],
    queryFn: () => compareOffers(ids),
    enabled: open && ids.length > 0,
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="compare-dialog" aria-describedby="compare-description">
          <header>
            <div>
              <p className="eyebrow"><ArrowLeftRight aria-hidden="true" size={15} />Lecture transversale</p>
              <Dialog.Title>Comparaison</Dialog.Title>
              <Dialog.Description id="compare-description">Les scores restent séparés de la confiance et de la fraîcheur.</Dialog.Description>
            </div>
            <Dialog.Close className="icon-button" aria-label="Fermer la comparaison" title="Fermer">
              <X aria-hidden="true" size={20} />
            </Dialog.Close>
          </header>

          {comparison.isPending && <div className="compare-loading" role="status">Préparation de la comparaison…</div>}
          {comparison.isError && <p className="inline-error" role="alert">La comparaison est indisponible.</p>}
          {comparison.data && (
            <div
              className="compare-grid"
              tabIndex={0}
              aria-label="Offres comparées, défilement horizontal"
            >
              {comparison.data.offers.map((offer) => (
                <article key={offer.id}>
                  <div className="compare-score"><strong>{offer.relevance}</strong><span>/100</span></div>
                  <h3>{offer.title}</h3>
                  <p className="compare-company">{offer.company}</p>
                  <dl>
                    <div><dt>Confiance</dt><dd>{offer.confidence}%</dd></div>
                    <div><dt>Fraîcheur</dt><dd>{offer.freshness_days} j</dd></div>
                    <div><dt>Lieu</dt><dd>{offer.location}</dd></div>
                    <div><dt>Contrat</dt><dd>{offer.contract}</dd></div>
                  </dl>
                  <ul>
                    {offer.axes.map((axis) => <li key={axis.name}><span>{axis.name}</span><b>+{axis.points}</b></li>)}
                  </ul>
                </article>
              ))}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
