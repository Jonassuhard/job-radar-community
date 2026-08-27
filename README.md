# Job Radar Community

Radar local et explicable pour explorer des offres d'emploi. Il normalise les
offres, les deduplique et explique separement la pertinence, la confiance et la
fraicheur. Les donnees restent locales par defaut.

## Limites de l'edition publique

- Pas de CV, candidature, email de candidature, auto-candidature ou generation
  de documents de candidature.
- Pas de navigateur authentifie, CAPTCHA ni contournement de conditions d'usage.
- LinkedIn, Indeed et Welcome to the Jungle sont `manual_only`: aucun refresh
  automatique ne peut les appeler.
- Le mode demo contient 42 offres et identites fictives; il fonctionne hors ligne.

## Demarrage en cinq minutes

Prerequis: Python 3.12 et Node 22 pour l'interface. Le service API reste lie a
la machine locale (`127.0.0.1`).

```sh
# Depuis le dossier contenant l'archive extraite:
RELEASE=v0.1.0-beta.1
cd job-radar-community-$RELEASE
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
job-radar demo --data-dir "$PWD/.job-radar"
job-radar config validate --config-dir "$PWD/.job-radar/config"
job-radar doctor --data-dir "$PWD/.job-radar"
job-radar serve --data-dir "$PWD/.job-radar"
```

Dans un second terminal, lance l'interface qui transmet les requetes API vers
le service local:

```sh
# Depuis le meme dossier contenant l'archive extraite:
RELEASE=v0.1.0-beta.1
cd job-radar-community-$RELEASE
npm --prefix frontend ci
npm --prefix frontend run dev
```

Ouvre l'URL affichee par Vite, habituellement `http://127.0.0.1:5173`.

## Configuration et donnees

Par defaut, la CLI utilise `~/.config/job-radar/` pour les fichiers YAML et
`~/.local/share/job-radar/` pour SQLite. `--data-dir` regroupe les deux pour un
essai isole; `JOB_RADAR_CONFIG_DIR` remplace uniquement le repertoire YAML.
Les cles eventuelles restent dans les variables d'environnement, jamais dans
les fichiers YAML. Voir [la configuration](docs/CONFIGURATION.md).

La demo est le moyen recommande de verifier l'installation avant toute source
externe. La politique est detaillee dans [la politique des sources](docs/SOURCES_POLICY.md).

Un fichier JSON local peut etre valide sans ecriture, puis importe:

```sh
job-radar import offres.json --preview --data-dir "$PWD/.job-radar"
job-radar import offres.json --data-dir "$PWD/.job-radar"
```

La vue Sources expose le meme parcours avec un selecteur de fichier local.

## Architecture

Le noyau Python traite les offres et ecrit SQLite localement. FastAPI expose
les vues materialisees; React les affiche sans recalculer le score. Aucun LLM
ni service cloud n'est requis. Les details sont dans [l'architecture](docs/ARCHITECTURE.md).

## Developpement et verifications

```sh
uv sync --locked --group dev
uv run --locked --group dev pytest -q
uv run --locked --group dev ruff check .
npm --prefix frontend ci
npm --prefix frontend test -- --run
npm --prefix frontend run build
npm --prefix frontend exec playwright install chromium
npm --prefix frontend run test:e2e
uv run --locked --group dev python scripts/export_openapi.py > /tmp/job-radar-openapi.json
uv run --locked --group dev python scripts/public_audit.py .
gitleaks detect --source . --redact
npm --prefix frontend audit --omit=dev --audit-level=high
uv run --locked --group dev pip-audit
```

## Documentation et communaute

- [Configuration](docs/CONFIGURATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Politique des sources](docs/SOURCES_POLICY.md)
- [Confidentialite](docs/PRIVACY.md)
- [Contribuer](CONTRIBUTING.md)
- [Securite](SECURITY.md)
- [Support](SUPPORT.md)
- [Changelog](CHANGELOG.md)
- [Notices tierces](THIRD_PARTY_NOTICES.md)

Le projet est distribue sous [licence MIT](LICENSE).
