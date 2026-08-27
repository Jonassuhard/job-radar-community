# Configuration

## Emplacements locaux

Sans option, Job Radar lit ses fichiers YAML dans `~/.config/job-radar/` et sa
base SQLite dans `~/.local/share/job-radar/job-radar.db`. Pour isoler un essai:

```sh
job-radar init --data-dir "$PWD/.job-radar"
job-radar demo --data-dir "$PWD/.job-radar"
```

`JOB_RADAR_CONFIG_DIR` change uniquement le repertoire des YAML. L'option
`--config-dir` est utile pour valider ou reutiliser un repertoire explicite.

```sh
job-radar config validate --config-dir "$PWD/.job-radar/config"
job-radar doctor --data-dir "$PWD/.job-radar"
```

Job Radar cree ses repertoires locaux avec les permissions `0700` et ses
fichiers avec les permissions `0600`. Un repertoire, un fichier ou un lien
symbolique existant qui ne respecte pas ce contrat est refuse sans etre modifie
automatiquement. Corrige alors uniquement le chemin que tu as choisi, par
exemple avec `chmod 700 <repertoire>` ou `chmod 600 <fichier>`, puis relance la
commande. Ce controle protege notamment le profil, la configuration et la base
SQLite contre une lecture par un autre compte local.

## Les cinq fichiers

- `profile.yml`: roles, competences, preuves, langues et seniorite.
- `search.yml`: lieux, contrats, teletravail, salaire et termes.
- `scoring.yml`: axes, poids, seuils, bonus, malus et blocages.
- `sources.yml`: modes des sources, quotas et noms de variables d'environnement.
- `taxonomy.yml`: alias et termes requis, preferes ou mentionnes.

Les exemples versionnes sont dans [config](../config/). `job-radar init` ne
remplace jamais un fichier deja present. `job-radar config validate` ne modifie
jamais les fichiers et affiche les chemins YAML en erreur.

### Generations actives

Au premier demarrage, les cinq YAML racine du repertoire de configuration sont
les fichiers actifs. Un enregistrement depuis l'interface cree ensuite une
generation complete et immuable dans le repertoire `.generations`, sous
`<identifiant>/`, puis ecrit son identifiant dans `.current`. Des que `.current`
existe, Job Radar lit cette
generation active: les YAML racine restent des copies d'amorcage et ne pilotent
plus l'application. Pour modifier la configuration, utilise l'interface ou une
nouvelle generation complete; n'edite pas les anciennes generations.

L'interface valide les cinq documents, active la nouvelle generation d'un seul
bloc, puis relance le calcul des offres deja enregistrees. Si ce recalcul echoue,
la configuration reste enregistree et l'interface propose de relancer uniquement
le recalcul, sans reecrire les YAML.

## Reglages de score effectivement supportes

Le vocabulaire de decision est ferme: `reject`, `monitor`, `review`, puis
`prioritize`, avec des seuils strictement croissants. Les seuls axes acceptes
sont `role_fit`, `skills`, `location`, `contract`, `work_mode`, `language`,
`seniority`, `required_terms`, `include_terms` et `salary`.

Les seuils disponibles sont `minimum_confidence` et
`deduplication_similarity`. Les plafonds disponibles sont `bonus` et
`penalty`. Les regles implementees sont volontairement limitees:

- bonus: `salary_transparency`;
- malus: `missing_salary`, `missing_role_detail`;
- conditions bloquantes: `excluded_term`, `required_term_missing`.

Tout autre nom est refuse par `job-radar config validate`. Un salaire connu
inferieur a `salary_minimum` et une confiance inferieure a
`minimum_confidence` forcent la decision `reject` avec une raison bloquante.

## Secrets et sources

Une cle est referencee par son nom de variable, par exemple `ADZUNA_APP_KEY`;
sa valeur ne doit pas apparaitre dans un YAML ni dans un ticket. Utilise un
fichier `.env` local ignore par Git ou les variables de ton environnement. Le
fichier `.env` n'est pas charge automatiquement. Exporte-le explicitement dans
le shell qui lance Job Radar:

```sh
set -a; source .env; set +a
job-radar serve --data-dir "$PWD/.job-radar"
```

Les sources `manual_only` ne peuvent pas declarer de cle. LinkedIn, Indeed et
Welcome to the Jungle restent dans ce mode. Consulte [la politique des sources](SOURCES_POLICY.md)
avant d'activer ou d'ajouter une source.

## Recalcul et diagnostic

```sh
job-radar refresh --data-dir "$PWD/.job-radar"
job-radar rescore --data-dir "$PWD/.job-radar"
job-radar doctor --data-dir "$PWD/.job-radar"
```

`refresh` ignore les connecteurs indisponibles et refuse une source
`manual_only`. `rescore` ne contacte aucun service: il recalcule les scores de
la base locale.
