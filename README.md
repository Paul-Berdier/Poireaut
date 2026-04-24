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
| **Frontend**      | React 18 + Vite + TypeScript + React Flow   |
| **Déploiement**   | Railway — 3 services (api, worker, web)     |

## Démarrer en local

```bash
cp .env.example .env
docker compose up --build
```

Front : http://localhost:5173 — API : http://localhost:8000/docs

## L'app, en 30 secondes

1. **Landing** → "Ouvrir une enquête"
2. **Auth** — onglet Connexion / Nouveau compte
3. **Dashboard** — liste de tes enquêtes, ou création
4. **Canvas** — la toile d'araignée de ton enquête
   - Barre du haut : ajouter un indice (email, pseudo, domaine, …)
   - Clic sur un nœud : panneau latéral avec valider / rejeter / **pivoter**
   - Le bouton Pivoter lance tous les connecteurs compatibles en parallèle
   - Les nouveaux nœuds apparaissent **en live** (WebSocket)
   - Drag & drop libre des nœuds, minimap, zoom, pan

## Connecteurs OSINT disponibles

| Nom      | Entrée    | Sortie      | Statut |
| -------- | --------- | ----------- | ------ |
| `holehe` | `email`   | `account` × | ✅      |

Ajouter un connecteur : créer `apps/worker/src/connectors/mon_outil.py`,
hériter de `BaseConnector`, décorer avec `@register`.

## Avancement

- [x] **Étape 1** — Scaffold + Docker + Railway
- [x] **Étape 2** — Modèles, migrations, auth JWT, CRUD, graph endpoint
- [x] **Étape 3** — Interface Connector, Holehe, orchestrateur Celery, WS stream
- [x] **Étape 4** — Toile d'araignée interactive (React Flow), page par enquête,
      validation en un clic, updates live via WebSocket
- [ ] Étape 5 — Connecteurs supplémentaires (Maigret, HIBP, Sherlock, …),
      healthchecks planifiés, page admin

## Légal

Usage strictement soumis au RGPD et aux législations applicables.
