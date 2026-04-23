# 🕵️‍♂️ Poireaut — Outil OSINT

> Investigation open-source par pivots successifs.
> Mr. Poireaut enquête, vous validez, la toile se tisse.

---

## Stack

| Couche            | Techno                                      |
| ----------------- | ------------------------------------------- |
| **Backend API**   | FastAPI (Python 3.11) + Pydantic v2         |
| **Worker**        | Celery + Redis                              |
| **Database**      | PostgreSQL 16 + SQLAlchemy 2.0 async        |
| **Migrations**    | Alembic (async)                             |
| **Auth**          | JWT (HS256) + bcrypt                        |
| **Cache / Queue** | Redis 7                                     |
| **Frontend**      | React 18 + Vite + TypeScript                |
| **Graphe**        | React Flow (ajouté à l'étape 4)             |
| **Déploiement**   | Railway (services séparés, Dockerfile each) |

## Structure du monorepo

```
poireaut/
├── apps/
│   ├── api/        FastAPI
│   │   ├── src/
│   │   │   ├── db/          engine, Base, enums partagés
│   │   │   ├── models/      SQLAlchemy (User, Investigation, Entity, DataPoint, Connector, ConnectorRun)
│   │   │   ├── schemas/     Pydantic I/O
│   │   │   ├── services/    logique métier (auth, …)
│   │   │   ├── routes/      FastAPI routers
│   │   │   ├── deps.py      get_db, get_current_user
│   │   │   ├── config.py
│   │   │   └── main.py
│   │   ├── migrations/      Alembic
│   │   ├── tests/
│   │   ├── alembic.ini
│   │   ├── entrypoint.sh    applique les migrations puis lance uvicorn
│   │   └── Dockerfile
│   ├── worker/     Celery
│   └── web/        React
├── docs/ARCHITECTURE.md
├── docker-compose.yml
├── .env.example
└── README.md
```

## Démarrer en local

```bash
cp .env.example .env
docker compose up --build
```

Les migrations Alembic sont appliquées **automatiquement** au démarrage de
`api` (via `entrypoint.sh` → `alembic upgrade head`). Tu n'as rien à lancer
à la main.

Accès :
- Frontend : http://localhost:5173
- API docs : http://localhost:8000/docs
- Health   : http://localhost:8000/health

## API — endpoints disponibles (étape 2)

Toutes les routes `/investigations`, `/entities`, `/datapoints` exigent un
header `Authorization: Bearer <token>`.

### Auth
| Méthode | Route            | Description                       |
| ------- | ---------------- | --------------------------------- |
| POST    | `/auth/register` | Créer un compte (désactivable via `ALLOW_REGISTRATION=false`) |
| POST    | `/auth/login`    | `application/x-www-form-urlencoded` → token JWT |
| GET     | `/auth/me`       | Profil courant                    |

### Enquêtes
| Méthode | Route                                  |
| ------- | -------------------------------------- |
| GET     | `/investigations`                      |
| POST    | `/investigations`                      |
| GET     | `/investigations/{id}`                 |
| PATCH   | `/investigations/{id}`                 |
| DELETE  | `/investigations/{id}`                 |
| GET     | `/investigations/{id}/entities`        |
| POST    | `/investigations/{id}/entities`        |
| GET     | `/investigations/{id}/graph`           |

### Entités & datapoints
| Méthode | Route                                |
| ------- | ------------------------------------ |
| GET     | `/entities/{id}`                     |
| PATCH   | `/entities/{id}`                     |
| DELETE  | `/entities/{id}`                     |
| GET     | `/entities/{id}/datapoints`          |
| POST    | `/entities/{id}/datapoints`          |
| GET     | `/datapoints/{id}`                   |
| PATCH   | `/datapoints/{id}`  ← validation     |
| DELETE  | `/datapoints/{id}`                   |

## Créer une nouvelle migration

À faire quand tu modifies un modèle :

```bash
# autogénère une révision depuis la diff modèles ↔ DB
docker compose exec api alembic revision --autogenerate -m "add foo column"

# applique
docker compose exec api alembic upgrade head

# revenir une révision en arrière
docker compose exec api alembic downgrade -1
```

## Lancer les tests

```bash
docker compose exec api pytest -q
```

## Déploiement Railway

| Service Railway   | Root directory   | Type           |
| ----------------- | ---------------- | -------------- |
| `poireaut-api`    | `apps/api`       | Dockerfile     |
| `poireaut-worker` | `apps/worker`    | Dockerfile     |
| `poireaut-web`    | `apps/web`       | Dockerfile     |
| `poireaut-db`     | —                | Postgres addon |
| `poireaut-redis`  | —                | Redis addon    |

Variables à fournir au service `poireaut-api` sur Railway :
- `DATABASE_URL` (auto-injecté si tu relies l'addon Postgres)
- `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` (auto-injectés si tu relies Redis)
- `JWT_SECRET` (**obligatoire** — `python -c "import secrets; print(secrets.token_urlsafe(64))"`)
- `ALLOW_REGISTRATION=false` (sauf en dev)
- `API_CORS_ORIGINS=https://poireaut-web.up.railway.app` (l'URL publique du front)

Au premier déploiement : crée un admin via l'API avec `ALLOW_REGISTRATION=true`,
puis passe-le à `false`.

## Avancement

- [x] **Étape 1** — Scaffold du monorepo + infra locale + hello-world déployable
- [x] **Étape 2** — Modèles (User, Investigation, Entity, DataPoint, Connector, ConnectorRun)
      + Alembic + auth JWT + CRUD enquêtes/entités/datapoints + endpoint graphe
- [ ] Étape 3 — Interface `Connector` + premier connecteur (Holehe) + worker Celery
- [ ] Étape 4 — Design system Poireaut + composant toile d'araignée
- [ ] Étape 5 — Flux d'enquête end-to-end

## Légal

Poireaut est un outil d'investigation en sources ouvertes. L'usage doit respecter
le RGPD et les législations applicables. Toute enquête sur un tiers sans base
légale légitime (consentement, intérêt légitime documenté, mission journalistique,
recherche de sécurité autorisée…) est interdite.
