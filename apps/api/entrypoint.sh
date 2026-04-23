#!/bin/sh
# Poireaut API entrypoint
# ------------------------------------------------------------------
# 1. Wait until the database accepts connections
# 2. Apply Alembic migrations
# 3. Exec the requested command (uvicorn, celery, a shell, …)
#
# Note: `alembic upgrade head` is idempotent. In production with a
# single API replica this is fine. If you scale out, move migrations
# into a separate release job to avoid concurrent upgrades.

set -e

echo "⟡ Poireaut API starting…"

# Substitute $PORT if Railway provided one (it overrides the CMD's --port).
if [ -n "$PORT" ]; then
    echo "⟡ Binding to PORT=$PORT"
fi

echo "⟡ Running database migrations"
alembic upgrade head
echo "⟡ Migrations OK"

echo "⟡ Handing off to: $*"
exec "$@"
