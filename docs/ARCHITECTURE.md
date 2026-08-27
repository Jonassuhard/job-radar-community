# Architecture

```text
APIs et ATS autorises        Imports manuels
          |                      |
          +----------+-----------+
                     v
       normalisation et provenance
                     v
       canonicalisation et doublons
                     v
           extraction de faits
                     v
 profile.yml + search.yml + scoring.yml
                     |
                     v
 score explicable + confiance + fraicheur
                     v
          SQLite local + FastAPI locale
                     v
       Interface React: Radar, Insights, Sources, Reglages
```

## Frontieres

Le noyau Python ne depend ni de React, ni d'un LLM, ni d'un service cloud. Les
connecteurs emettent des `RawOffer`; le pipeline produit des `ScoredOffer`.
L'API lit SQLite et l'interface affiche la reponse: elle ne recalcule pas les
scores.

Le serveur refuse une ecoute hors loopback. Les ecritures de feedback, vues et
configuration exigent un jeton de session local, emis au demarrage et jamais
affiche par la CLI.

## Donnees locales

SQLite contient uniquement des offres, leur provenance, leurs faits, leurs
scores, l'etat des refresh, la sante des sources, les vues sauvegardees et le
feedback local. Une installation neuve fonctionne avec la demo synthetique.
Les choix de collecte sont documentes dans [la politique des sources](SOURCES_POLICY.md)
et les limites de conservation dans [la confidentialite](PRIVACY.md).

## Contrats publics

- `job-radar init`, `demo`, `refresh`, `rescore`, `doctor`, `serve` et
  `config validate` constituent la surface CLI.
- `/health` et `/api/*` constituent la surface FastAPI locale.
- `scripts/export_openapi.py` produit le document OpenAPI stable sur la sortie
  standard sans toucher a la configuration utilisateur.
- `scripts/public_audit.py` verifie la liste blanche du depot public.
