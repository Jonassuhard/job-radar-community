# Politique des sources

## Principe

Job Radar collecte uniquement ce qui est autorise par la source, sa licence et
ses conditions applicables. Chaque offre conserve sa provenance, son URL et sa
date. Le produit n'essaie pas de contourner des controles d'acces.

## Modes

| Mode | Usage | Refresh automatique |
| --- | --- | --- |
| `api` | API documentee et cle eventuelle en variable d'environnement | Oui, si le connecteur est implemente et active |
| `ats` | Flux ou ATS public explicitement autorise | Oui, si le connecteur est implemente et active |
| `manual_only` | Import local normalise par la personne utilisatrice | Non |

LinkedIn, Indeed et Welcome to the Jungle sont `manual_only`. Leur selection
dans `job-radar refresh --source ...` est refusee: aucune requete automatique,
aucun navigateur authentifie et aucun crawler ne sont fournis pour ces services.

## Import manuel local

Le fichier est un tableau JSON strict d'objets offre. Chaque objet declare
`external_id`, `source`, `url`, `title`, `company`, `location`, `contract`,
`remote`, `description` et un `published_at` avec fuseau horaire. Les champs
inconnus, les cles dupliquees et les dates sans fuseau sont refuses avant toute
ecriture.

Un import accepte au maximum 500 offres et 2 MiB. La preview traverse
normalisation, deduplication et scoring sans modifier SQLite:

```sh
job-radar import offres.json --preview --data-dir "$PWD/.job-radar"
job-radar import offres.json --data-dir "$PWD/.job-radar"
```

La vue Sources fournit les memes actions. L'API locale expose `POST /api/import`
et `POST /api/import?preview=true`; ces deux mutations exigent le jeton de
session ephemere emis par l'instance locale. Le fichier est lu dans le navigateur
et n'est pas stocke hors de la base locale.

## Etat de la V0.1

La configuration exemple fournit `local_demo`, pour une installation sans
reseau. Les familles France Travail, Adzuna, Jooble, Remotive et ATS publics
peuvent etre evaluees pour des connecteurs futurs seulement lorsque leurs
conditions, leur API et leurs limites de debit le permettent. Ce document ne
constitue pas une autorisation de collecter une source.

## Ajout d'une source

Une contribution de connecteur doit:

1. Identifier une API ou un flux public autorise et sa documentation.
2. Declarer le mode, le quota et le nom de variable de secret, sans valeur de secret.
3. Preserver URL, identifiant externe, date et texte source necessaires a
   l'explication.
4. Ajouter des tests montrant le respect des quotas, les erreurs et le refus
   `manual_only`.
5. Ne jamais ajouter de fonction de candidature, de remplissage de formulaire,
   de session authentifiee ou de contournement de CAPTCHA.

Les donnees importees manuellement relevent de la responsabilite de la personne
qui les fournit. Voir aussi [la confidentialite](PRIVACY.md) et [la contribution](../CONTRIBUTING.md).
