#!/usr/bin/env bash
# Idem que run.ps1 mais pour Linux/macOS.

set -euo pipefail

if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="python"; fi

echo "[1/3] Demarrage de l'API metier ..."
"$PY" api_server.py &
API_PID=$!
trap 'echo "[3/3] Arret de l API"; kill $API_PID 2>/dev/null || true' EXIT

sleep 2

echo "[2/3] Lancement du serveur MCP + agent ..."
echo ""
if [ "$#" -gt 0 ]; then
  "$PY" agent.py "$@"
else
  "$PY" agent.py
fi