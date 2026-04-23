# 🕵️‍♂️ Poireaut — Outil OSINT

> Investigation open-source par pivots successifs.
> Mr. Poireaut enquête, vous validez, la toile se tisse.

---

## Stack

| Couche            | Techno                                      |
| ----------------- | ------------------------------------------- |
| **Backend API**   | FastAPI (Python 3.11) + Pydantic v2         |
| **Worker**        | Celery + Redis                              |
| **Database**      | PostgreSQL 16                               |
| **Cache / Queue** | Redis 7                                     |
| **Frontend**      | React 18 + Vite + TypeScript                |
| **Graphe**        | React Flow (ajouté à l'étape 4)             |
| **Déploiement**   | Railway (services séparés, Dockerfile each) |

## Structure du monorepo

```
poireaut/
├── apps/
│   ├── api/        FastAPI — expose REST + WebSocket
│   ├── worker/     Celery — exécute les connecteurs OSINT
│   └── web/        React — UI investigateur + toile d'araignée
├── docs/
│   └── ARCHITECTURE.md
├── docker-compose.yml
├── .env.example
└── README.md
```

Chaque app est **indépendante** : son propre `Dockerfile`, ses propres deps, son propre service Railway.

## Démarrer en local

Prérequis : Docker + Docker Compose.

```bash
# 1. Cloner et copier les variables d'env
cp .env.example .env

# 2. Lancer toute la stack (postgres + redis + api + worker + web)
docker compose up --build

# 3. Ouvrir
#   Frontend : http://localhost:5173
#   API docs : http://localhost:8000/docs
#   Health   : http://localhost:8000/health
```

Pour arrêter : `docker compose down`. Pour repartir de zéro (efface la DB) : `docker compose down -v`.

## Déploiement Railway

Sur Railway, créer **un service par app** en pointant chacun vers son dossier :

| Service Railway   | Root directory   | Type           |
| ----------------- | ---------------- | -------------- |
| `poireaut-api`    | `apps/api`       | Dockerfile     |
| `poireaut-worker` | `apps/worker`    | Dockerfile     |
| `poireaut-web`    | `apps/web`       | Dockerfile     |
| `poireaut-db`     | —                | Postgres addon |
| `poireaut-redis`  | —                | Redis addon    |

Railway injectera automatiquement `DATABASE_URL` et `REDIS_URL` si vous "reliez" les addons aux services applicatifs.

## Avancement

- [x] **Étape 1** — Scaffold du monorepo + infra locale + hello-world déployable
- [ ] Étape 2 — Modèles de données + migrations Alembic + auth
- [ ] Étape 3 — Interface `Connector` + premier connecteur (Holehe) + worker Celery
- [ ] Étape 4 — Design system Poireaut + composant toile d'araignée
- [ ] Étape 5 — Flux d'enquête end-to-end

## Légal

Poireaut est un outil d'investigation en sources ouvertes. L'usage doit respecter
le RGPD et les législations applicables. Toute enquête sur un tiers sans base
légale légitime (consentement, intérêt légitime documenté, mission journalistique,
recherche de sécurité autorisée…) est interdite.
