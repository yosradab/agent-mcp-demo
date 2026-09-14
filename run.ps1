# Lance la demo complete sous Windows : API -> MCP -> Agent
# Usage:
#   .\run.ps1                          (mode interactif, sans cle API)
#   .\run.ps1 "Liste les tickets high"
#  Mettre ANTHROPIC_API_KEY (ou OPENAI_API_KEY) dans l'environnement pour un vrai agent LLM.

$ErrorActionPreference = "Stop"

if (Test-Path ".\.venv\Scripts\python.exe") { $Python = ".\.venv\Scripts\python.exe" } else { $Python = "python" }

Write-Host "[1/3] Demarrage de l'API metier (FastAPI sur http://127.0.0.1:8000) ..."
$api = Start-Process -FilePath $Python -ArgumentList "api_server.py" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 5
    Write-Host "[1/3] OK -> $($health.service) status=$($health.status)"

    Write-Host "[2/3] Lancement du serveur MCP + agent ..."
    Write-Host ""
    if ($args.Count -gt 0) {
        & $Python agent.py $args
    } else {
        & $Python agent.py
    }
} finally {
    Write-Host ""
    Write-Host "[3/3] Arret de l'API ..."
    Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
}