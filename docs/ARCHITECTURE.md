# Architecture Poireaut

## Vue d'ensemble

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│              │       │              │       │              │
│   Browser    │──────▶│  poireaut-   │──────▶│  PostgreSQL  │
│   (React)    │  HTTP │     api      │       │              │
│              │  WS   │  (FastAPI)   │       └──────────────┘
└──────────────┘       │              │
                       │              │       ┌──────────────┐
                       │              │──────▶│              │
                       └──────────────┘ queue │    Redis     │
                                              │   (broker)   │
                       ┌──────────────┐       │              │
                       │              │◀──────│              │
                       │  poireaut-   │       └──────────────┘
                       │   worker     │
                       │   (Celery)   │──────▶ OSINT tools
                       │              │        (Holehe, Maigret, …)
                       └──────────────┘
```

## Services

### `poireaut-api` — FastAPI
Expose l'API REST + WebSocket.
Ne fait **aucun** appel OSINT long : tout est délégué au worker via une queue Redis.
Healthcheck : `GET /health`.

### `poireaut-worker` — Celery
Consomme les tâches produites par l'API. Chaque tâche exécute un ou plusieurs connecteurs OSINT, écrit le résultat en DB, puis notifie l'API via Redis pubsub qui relaie au frontend par WebSocket.

### `poireaut-web` — React + Vite
SPA servie statiquement en production (Nginx). Parle à l'API en HTTP et s'abonne au WS pour les updates live de la toile d'araignée.

### Postgres / Redis
Addons Railway. En local, conteneurs docker-compose.

## Choix techniques — justifications

**Pourquoi séparer API et Worker ?**
Les requêtes OSINT peuvent durer 30s à plusieurs minutes (Maigret scanne 2500 sites). Si on les faisait dans le handler HTTP, on saturerait les workers Uvicorn et les timeouts HTTP casseraient les enquêtes. Avec Celery, l'API répond en quelques ms ("tâche lancée, id = X"), et le frontend suit la progression en live.

**Pourquoi Redis et pas RabbitMQ ?**
Redis est déjà là pour le cache. Un broker en moins. Pour la charge prévue (quelques utilisateurs, quelques centaines de tâches/jour max) c'est largement suffisant.

**Pourquoi Postgres et pas SQLite ?**
Railway gère Postgres comme addon. Pas besoin de volume persistant à monter. Et on aura besoin de JSONB pour stocker les résultats bruts des connecteurs de façon flexible.

**Pourquoi React Flow (étape 4) et pas D3 ?**
React Flow a une API déclarative React-first, gère le drag/zoom/panning gratuitement, et permet des nœuds custom en JSX. D3 est plus puissant mais 10× plus de code pour le même résultat.

## Flux d'une requête "je veux enquêter sur cet email"

1. **Frontend** → `POST /investigations/{id}/datapoints` avec `{ type: "email", value: "alice@…" }`
2. **API** valide, insère en DB, enqueue `run_connectors_for_datapoint(datapoint_id)`
3. **API** répond `202 Accepted` au front
4. **Worker** récupère la tâche, demande au registre les connecteurs qui acceptent `email`, les lance en parallèle (asyncio.gather dans la tâche Celery)
5. Chaque connecteur retourne un `ConnectorResult` (liste de nouveaux datapoints trouvés, source, date, confiance)
6. **Worker** insère les nouveaux datapoints avec `status=UNVERIFIED`
7. **Worker** publie sur un channel Redis `investigation:{id}` les nouvelles arêtes du graphe
8. **API** (abonné au channel) pousse l'update sur le WebSocket ouvert avec le front
9. **Frontend** ajoute les nouveaux nœuds sur la toile en live

## Où vont les choses

- Logique métier (validation, orchestration) → `api/src/services/`
- Connecteurs OSINT (un fichier par outil) → `worker/src/connectors/`
- Modèles DB (SQLAlchemy) → `api/src/models/`
- Schemas API (Pydantic I/O) → `api/src/schemas/`
- Composants UI → `web/src/components/`
- Features métier (investigation, graph) → `web/src/features/`
