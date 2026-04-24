# 🕵️‍♂️ Poireaut — Outil OSINT

> Investigation open-source par pivots successifs.
> Mr. Poireaut enquête, vous validez, la toile se tisse.

---

## Stack

| Couche            | Techno                                      |
| ----------------- | ------------------------------------------- |
| **Backend API**   | FastAPI + Pydantic v2 + SQLAlchemy 2 async  |
| **Worker**        | Celery + Redis, connecteurs OSINT async     |
| **Scheduler**     | Celery Beat (healthchecks quotidiens)       |
| **DB**            | PostgreSQL 16 + Alembic                     |
| **Auth**          | JWT HS256 + bcrypt                          |
| **Temps réel**    | Redis pub/sub → WebSocket                   |
| **Frontend**      | React 18 + Vite + TypeScript + React Flow   |
| **Déploiement**   | Railway — 3 services (api, worker, web)     |

## Démarrer en local

```bash
cp .env.example .env
docker compose up --build
```

Front : http://localhost:5173 — API : http://localhost:8000/docs

## Connecteurs OSINT disponibles

| Nom        | Entrée     | Sortie          | Coût          |
| ---------- | ---------- | --------------- | ------------- |
| `holehe`   | `email`    | `account`       | Gratuit       |
| `maigret`  | `username` | `account`, `url` | Gratuit       |
| `hibp`     | `email`    | `other` (breach) | Clé API gratuite |
| `crtsh`    | `domain`   | `domain` (sous-)| Gratuit       |
| `wayback`  | `url`      | `url` (snapshots) | Gratuit    |

Ajouter un connecteur : créer `apps/worker/src/connectors/mon_outil.py`,
hériter de `BaseConnector`, décorer avec `@register`, importer dans
`connectors/__init__.py`. Terminé.

## Fonctionnalités

- ✅ Auth JWT (register / login, désactivable en prod)
- ✅ Enquêtes multiples par utilisateur, scopées au propriétaire
- ✅ Datapoints typés (email, pseudo, téléphone, domaine, URL, photo, …)
- ✅ Pivot sur 1 clic — tous les connecteurs compatibles lancés en parallèle
- ✅ Graphe interactif (React Flow) mis à jour en live via WebSocket
- ✅ Validation / rejet / suppression par datapoint avec audit
- ✅ Page admin : état de santé des connecteurs, historique des runs
- ✅ Healthcheck quotidien automatique (Celery Beat, 04:17 UTC)

## Variables d'environnement (production)

Sur `poireaut-api` :

| Variable                          | Obligatoire | Notes                                  |
| --------------------------------- | ----------- | -------------------------------------- |
| `DATABASE_URL`                    | ✅          | `${{Postgres.DATABASE_URL}}` suffit    |
| `REDIS_URL`                       | ✅          | `${{Redis.REDIS_URL}}`                 |
| `CELERY_BROKER_URL`               | ✅          | même Redis, path `/1`                  |
| `CELERY_RESULT_BACKEND`           | ✅          | même Redis, path `/2`                  |
| `JWT_SECRET`                      | ✅          | `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `API_CORS_ORIGINS`                | ✅          | URL du front, sans slash final          |
| `ALLOW_REGISTRATION`              |            | `false` une fois le 1ᵉʳ compte créé     |
| `HIBP_API_KEY`                    |            | Active le connecteur HIBP               |
| `SHODAN_API_KEY`                  |            | Prévu pour de futurs connecteurs        |

## Avancement

- [x] **Étape 1** — Scaffold + Docker + Railway
- [x] **Étape 2** — Modèles, migrations, auth JWT, CRUD, graph endpoint
- [x] **Étape 3** — Interface Connector, Holehe, orchestrateur Celery, WS stream
- [x] **Étape 4** — Toile d'araignée interactive (React Flow), page par enquête
- [x] **Étape 5** — +4 connecteurs (Maigret, HIBP, crt.sh, Wayback),
      healthchecks planifiés, page admin, polish

## Légal

Usage strictement soumis au RGPD et aux législations applicables. Toute
enquête sur un tiers sans base légale légitime (journalisme, sécurité
autorisée, recherche documentée…) est interdite.
