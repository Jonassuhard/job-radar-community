# Contribuer

## Avant de coder

Lis [la politique des sources](docs/SOURCES_POLICY.md), [la confidentialite](docs/PRIVACY.md)
et la [securite](SECURITY.md). Les contributions restent dans le perimetre local,
explicable et sans auto-candidature.

N'ajoute jamais de CV, cookies, jetons, mots de passe, fichiers `.env`, bases
SQLite ou donnees de candidature dans une Issue, une Pull Request ou un commit.
Un secret expose doit etre revoque avant tout signalement prive.

## Cycle de travail

1. Ouvre une Issue pour un changement substantiel; decris le probleme et son
   impact sans donnees personnelles.
2. Cree une branche ciblee et ajoute ou adapte les tests avant l'implementation.
3. Garde les identites, URLs et donnees de test fictives (`.example`).
4. Mets a jour les documents touches et la liste blanche publique si une racine
   versionnee est ajoutee.
5. Execute les controles locaux ci-dessous avant la Pull Request.

```sh
uv sync --locked --group dev
uv run --locked --group dev pytest -q
uv run --locked --group dev ruff check .
npm --prefix frontend ci
npm --prefix frontend test -- --run
npm --prefix frontend run build
uv run --locked --group dev python scripts/public_audit.py .
gitleaks detect --source . --redact
```

Une Pull Request doit expliquer le comportement verifie, les limites de source
et tout changement de configuration. Les mainteneurs peuvent demander une
preuve d'autorisation avant toute integration de connecteur.
