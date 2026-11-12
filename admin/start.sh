#!/bin/sh
set -eu
export SUPABASE_URL="${SUPABASE_URL:-}"
export SUPABASE_PUBLISHABLE_KEY="${SUPABASE_PUBLISHABLE_KEY:-}"
export API_BASE_URL="${API_BASE_URL:-}"
envsubst '${SUPABASE_URL} ${SUPABASE_PUBLISHABLE_KEY} ${API_BASE_URL}' < /opt/runtime-config.template > /tmp/config.js
exec nginx -g 'daemon off;'
