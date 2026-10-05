#!/usr/bin/env bash
# Serve the dashboard publicly through Tailscale Funnel (no open firewall port).
#
# Reflex runs as a production build in single-port mode: the static frontend
# and the websocket backend share PORT on localhost, and Funnel proxies the
# node's https://<machine>.<tailnet>.ts.net:PUBLIC_PORT URL to it.
# PUBLIC_PORT is fixed at 8443, leaving 443 and 10000 free for other apps.
#
# One-time setup (needs sudo):
#   sudo tailscale set --operator=$USER    # let this user manage serve/funnel
#   Funnel + HTTPS must be enabled for the tailnet; the first `tailscale funnel`
#   prints an admin-console link if they are not.
#
# Usage:  ./serve_public.sh          start (foreground; Ctrl-C stops the app)
#         ./serve_public.sh local    same single-port build, no funnel: open
#                                    http://localhost:$PORT (one port to forward
#                                    when developing on a remote machine)
#         ./serve_public.sh off      remove this app's funnel (PUBLIC_PORT only)
#
# Env:    PORT=3057 (local app port)
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-3057}"
PUBLIC_PORT=8443  # Funnel allows only 443, 8443 or 10000

if [[ "${1:-}" == "off" ]]; then
    tailscale funnel --https="$PUBLIC_PORT" off
    exit 0
fi

if [[ "${1:-}" == "local" ]]; then
    export REFLEX_API_URL="http://localhost:${PORT}"
    exec ../.venv/bin/reflex run --env prod --single-port --backend-host 127.0.0.1 --backend-port "$PORT"
fi

# Public URL of this node, e.g. https://myhost.tail1234.ts.net
DNS_NAME="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
PUBLIC_URL="https://${DNS_NAME}:${PUBLIC_PORT}"

# The browser opens its websocket to api_url, so it must be the public URL.
export REFLEX_API_URL="$PUBLIC_URL"
export REFLEX_DEPLOY_URL="$PUBLIC_URL"

tailscale funnel --bg --https="$PUBLIC_PORT" "$PORT"
echo "Public URL: $PUBLIC_URL"

exec ../.venv/bin/reflex run --env prod --single-port --backend-host 127.0.0.1 --backend-port "$PORT"
