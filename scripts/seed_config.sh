#!/usr/bin/env bash
# Environment-specific settings from .env into Postgres (kept out of workflow exports):
#   TG_CHAT_ID -> settings.alert_chat_id (alerts), TG_REVIEW_CHAT_ID -> settings.review_chat_id (cards, stage 7)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${TG_CHAT_ID:?TG_CHAT_ID is not set in .env}"
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v chat="$TG_CHAT_ID" -v review="${TG_REVIEW_CHAT_ID:-$TG_CHAT_ID}" <<'SQL'
INSERT INTO settings (key, value) VALUES ('alert_chat_id', :'chat'), ('review_chat_id', :'review')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
SQL
echo "config seeded"
