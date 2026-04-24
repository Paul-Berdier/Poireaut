# 🕵️‍♂️ Poireaut — Outil OSINT

> Investigation open-source par pivots successifs.
> Mr. Poireaut enquête, vous validez, la toile se tisse.

---

## Stack

| Couche            | Techno                                      |
| ----------------- | ------------------------------------------- |
| **Backend API**   | FastAPI + Pydantic v2 + SQLAlchemy 2 async  |
| **Worker**        | Celery + Redis, connecteurs OSINT async     |
| **DB**            | PostgreSQL 16 + Alembic                     |
| **Auth**          | JWT HS256 + bcrypt                          |
| **Temps réel**    | Redis pub/sub → WebSocket                   |
| **Frontend**      | React 18 + Vite + TypeScript                |
| **Déploiement**   | Railway — 3 services (api, worker, web)     |

## Démarrer en local

```bash
cp .env.example .env
docker compose up --build
```

- Frontend : http://localhost:5173
- API docs : http://localhost:8000/docs

## Connecteurs OSINT disponibles

| Nom      | Entrée    | Sortie      | Statut |
| -------- | --------- | ----------- | ------ |
| `holehe` | `email`   | `account` × | ✅      |

Ajouter un connecteur : créer `apps/worker/src/connectors/mon_outil.py`,
hériter de `BaseConnector`, décorer avec `@register`, importer depuis
`connectors/__init__.py`. Terminé.

## Flux d'une enquête

1. `POST /auth/register` ou `/login` → token JWT
2. `POST /investigations` → créer un dossier
3. `POST /investigations/{id}/entities` → ajouter la cible
4. `POST /entities/{id}/datapoints` → insérer la 1re miette (un email par ex.)
5. `POST /datapoints/{id}/pivot` → **le worker lance tous les connecteurs
   compatibles en parallèle**
6. Abonne-toi à `WS /ws/investigations/{id}?token=…` pour voir les résultats
   arriver en live via Redis pub/sub
7. `PATCH /datapoints/{newId}` pour valider ou rejeter chaque finding
8. Re-pivoter depuis un datapoint validé pour étendre la toile

## Avancement

- [x] **Étape 1** — Scaffold + Docker + Railway
- [x] **Étape 2** — Modèles, migrations, auth JWT, CRUD, graph endpoint
- [x] **Étape 3** — Interface Connector, Holehe, orchestrateur Celery,
      pub/sub Redis → WebSocket, UI login + dashboard
- [ ] Étape 4 — Toile d'araignée interactive (React Flow) + UI par enquête
- [ ] Étape 5 — Connecteurs supplémentaires (Maigret, HIBP, Sherlock, …)
      + healthchecks planifiés + admin

## Légal

Usage strictement soumis au RGPD et aux législations applicables. Aucune
enquête sur un tiers sans base légale légitime.
