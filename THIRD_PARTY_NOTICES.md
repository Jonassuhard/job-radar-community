# Notices tierces

Cette liste couvre les dependances runtime directes resolues pour
`0.1.0-beta.1`. Les dependances transitives sont fournies sous leurs propres
notices et licences dans les distributions installees. `uv.lock` et
`frontend/package-lock.json` verrouillent les versions de l'environnement de
release.

## Runtime Python

| Composant | Version resolue | Licence |
| --- | ---: | --- |
| [FastAPI](https://github.com/fastapi/fastapi) | 0.141.1 | MIT |
| [httpx](https://github.com/encode/httpx) | 0.28.1 | BSD-3-Clause |
| [Pydantic](https://github.com/pydantic/pydantic) | 2.13.4 | MIT |
| [PyYAML](https://github.com/yaml/pyyaml) | 6.0.3 | MIT |
| [Typer](https://github.com/fastapi/typer) | 0.27.1 | MIT |
| [Uvicorn](https://github.com/Kludex/uvicorn) | 0.52.4 | BSD-3-Clause |

## Runtime frontend

| Composant | Version resolue | Licence |
| --- | ---: | --- |
| [Radix Dialog](https://www.radix-ui.com/primitives) | 1.1.23 | MIT |
| [Radix Tooltip](https://www.radix-ui.com/primitives) | 1.2.16 | MIT |
| [TanStack Query](https://github.com/TanStack/query) | 5.102.5 | MIT |
| [Lucide React](https://github.com/lucide-icons/lucide) | 0.541.0 | ISC |
| [Motion](https://github.com/motiondivision/motion) | 12.43.0 | MIT |
| [React](https://github.com/facebook/react) | 19.2.8 | MIT |
| [React DOM](https://github.com/facebook/react) | 19.2.8 | MIT |
| [React Router DOM](https://github.com/remix-run/react-router) | 7.18.2 | MIT |
| [YAML](https://github.com/eemeli/yaml) | 2.9.0 | ISC |

## Outil de build frontend

| Composant | Version resolue | Licence |
| --- | ---: | --- |
| [Vite](https://github.com/vitejs/vite) | 7.3.6 | MIT |

La licence du projet est disponible dans [LICENSE](LICENSE). Les audits de
dependances sont executes en CI; voir [CONTRIBUTING.md](CONTRIBUTING.md).
