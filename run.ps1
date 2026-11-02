# Lance la demo complete sous Windows : API -> MCP -> Agent
# Usage:
#   .\run.ps1                          (mode interactif, sans cle API)
#   .\run.ps1 "Liste les tickets high"
#  Mettre ANTHROPIC_API_KEY (ou OPENAI_API_KEY) dans l'environnement pour un vrai agent LLM.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path ".\.venv\Scripts\python.exe") {
    $Python = (Resolve-Path ".\.venv\Scripts\python.exe").Path
} else {
    $Python = "python"
    Write-Host "Attention : pas de .venv trouve, utilisation du python systeme." -ForegroundColor Yellow
}

# Verifie les dependances avant de lancer quoi que ce soit
& $Python -c "import fastapi, uvicorn, mcp, httpx" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Dependances manquantes. Lancez :" -ForegroundColor Red
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\Activate.ps1"
    Write-Host "  pip install -r requirements.txt"
    exit 1
}

Write-Host "[1/3] Demarrage de l'API metier (FastAPI sur http://127.0.0.1:8000) ..."
$api = Start-Process -FilePath $Python -ArgumentList "api_server.py" -PassThru -NoNewWindow `
    -RedirectStandardOutput "api.log" -RedirectStandardError "api.err.log"

try {
    # Attend que l'API reponde (max ~20s)
    $health = $null
    for ($i = 0; $i -lt 40 -and -not $health; $i++) {
        if ($api.HasExited) { break }
        try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 1 } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $health) {
        Write-Host "L'API n'a pas demarre. Erreur :" -ForegroundColor Red
        if (Test-Path "api.err.log") { Get-Content "api.err.log" -Tail 20 }
        Write-Host "(Port 8000 deja pris ? -> netstat -ano | findstr :8000)"
        exit 1
    }
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
