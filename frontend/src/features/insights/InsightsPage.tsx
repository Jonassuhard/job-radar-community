import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BarChart3, DatabaseZap, Inbox, TrendingUp } from "lucide-react";

import { fetchMarketInsights } from "../../lib/api";

const decisionLabels: Record<string, string> = {
  prioritize: "À prioriser",
  review: "À examiner",
  monitor: "À surveiller",
  reject: "Écartées",
};

function PageHeading() {
  return (
    <header className="secondary-heading">
      <div>
        <p className="eyebrow"><BarChart3 aria-hidden="true" size={14} /> Observatoire</p>
        <h1>Marché local</h1>
        <p>Lecture factuelle du corpus stocké sur cette machine.</p>
      </div>
    </header>
  );
}

export function InsightsPage() {
  const query = useQuery({
    queryKey: ["market-insights"],
    queryFn: fetchMarketInsights,
  });

  if (query.isPending) {
    return (
      <section className="secondary-page">
        <PageHeading />
        <div className="secondary-state secondary-loading" role="status" aria-label="Chargement des indicateurs">
          <span aria-hidden="true" />
          <p>Calcul des indicateurs locaux…</p>
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
          <h2>Impossible de charger les indicateurs</h2>
          <p>Le service local n’a pas répondu.</p>
          <button type="button" onClick={() => void query.refetch()}>Réessayer</button>
        </div>
      </section>
    );
  }

  const insights = query.data;
  if (insights.total_offers === 0) {
    return (
      <section className="secondary-page">
        <PageHeading />
        <div className="secondary-state" role="status" aria-label="Aucune donnée de marché">
          <Inbox aria-hidden="true" size={25} />
          <h2>Aucune donnée de marché</h2>
          <p>Alimentez le corpus local pour faire apparaître les indicateurs.</p>
        </div>
      </section>
    );
  }

  const leadingSkills = insights.skills.slice(0, 12);
  const maxSkillCount = Math.max(...leadingSkills.map((skill) => skill.count), 1);

  return (
    <section className="secondary-page insights-page">
      <PageHeading />

      <div className="metric-strip" aria-label="Résumé du marché">
        <article className="metric-primary">
          <span>Corpus actif</span>
          <strong>{insights.total_offers}</strong>
          <small>offres locales</small>
        </article>
        {Object.entries(insights.decisions).map(([decision, count]) => (
          <article key={decision} data-decision={decision}>
            <span>{decisionLabels[decision] ?? decision}</span>
            <strong>{count}</strong>
            <small>{Math.round((count / insights.total_offers) * 100)} % du corpus</small>
          </article>
        ))}
      </div>

      <div className="insights-grid">
        <section className="data-section skills-section" aria-labelledby="skills-title">
          <div className="section-heading">
            <div>
              <p className="section-kicker">Demande observée</p>
              <h2 id="skills-title">Compétences les plus citées</h2>
            </div>
            <DatabaseZap aria-hidden="true" size={20} />
          </div>
          {leadingSkills.length ? (
            <ol className="skill-ranking">
              {leadingSkills.map((skill, index) => (
                <li key={skill.name}>
                  <span className="skill-rank">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <span>{skill.name}</span>
                    <i aria-hidden="true" style={{ width: `${(skill.count / maxSkillCount) * 100}%` }} />
                  </div>
                  <strong>{skill.count}</strong>
                </li>
              ))}
            </ol>
          ) : (
            <p className="inline-empty">Aucune compétence structurée dans le corpus actuel.</p>
          )}
        </section>

        <aside className="trend-panel" aria-labelledby="trend-title">
          <TrendingUp aria-hidden="true" size={21} />
          <p className="section-kicker">Évolution</p>
          <h2 id="trend-title">Tendance indisponible</h2>
          <p><strong>Historique insuffisant.</strong> Plusieurs relevés datés sont nécessaires pour comparer le marché dans le temps.</p>
          <dl>
            <div><dt>Source</dt><dd>Base locale</dd></div>
            <div><dt>Période</dt><dd>Instantané actuel</dd></div>
          </dl>
        </aside>
      </div>
    </section>
  );
}
