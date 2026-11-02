#!/usr/bin/env bash
# Lance la demo complete sous Linux/macOS : API -> MCP -> Agent
# Usage:
#   ./run.sh                          (mode interactif, sans cle API)
#   ./run.sh "Liste les tickets high"

set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="python3"; fi
API_URL="${API_BASE:-http://127.0.0.1:8000}"

echo "[1/3] Demarrage de l'API metier ($API_URL) ..."
"$PY" api_server.py > api.log 2>&1 &
API_PID=$!
trap 'echo ""; echo "[3/3] Arret de l API"; kill $API_PID 2>/dev/null || true' EXIT

# Attend que l'API reponde (max ~10s) au lieu d'un sleep fixe
for _ in $(seq 1 20); do
  if "$PY" -c "import urllib.request,sys; urllib.request.urlopen('$API_URL/health', timeout=1)" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then echo "L'API n'a pas demarre, voir api.log"; exit 1; fi
  sleep 0.5
done
echo "[1/3] OK"

echo "[2/3] Lancement du serveur MCP + agent ..."
echo ""
"$PY" agent.py "$@"
