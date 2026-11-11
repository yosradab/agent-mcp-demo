"""API metier locale : gestion de tickets support (simulation d'un vrai backend).

C'est LA couche qui contient la donnee metier reelle : tickets, clients, etc.
L'agent IA ne doit jamais acceder directement a cette base : il passe par le
serveur MCP, qui fait le lien.
"""

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).parent
DATA_FILE = Path(os.getenv("TICKETS_FILE", BASE_DIR / "data" / "tickets.json"))
STATIC_DIR = BASE_DIR / "static"
# RLock : une transaction (lecture -> modification -> ecriture) garde le verrou
# de bout en bout, sinon deux creations simultanees pourraient obtenir le meme id.
LOCK = threading.RLock()
UNASSIGNED = "non-assigne"

SEED_TICKETS = [
    {
        "id": 1,
        "title": "NVR ne repond plus apres coupure de courant",
        "description": "Le NVR Hikvision ne demarre plus, voyant alimentation clignote.",
        "status": "open",
        "priority": "high",
        "assignee": "technicien-1",
        "created_at": "2026-09-01T09:00:00Z",
    },
    {
        "id": 2,
        "title": "Implementer un agent IA avec MCP",
        "description": "Automatiser la creation et le tri des tickets par un agent IA.",
        "status": "in_progress",
        "priority": "medium",
        "assignee": "dev-ai",
        "created_at": "2026-09-05T14:30:00Z",
    },
    {
        "id": 3,
        "title": "Relance paiement facture 1042",
        "description": "Client en retard de paiement depuis 30 jours.",
        "status": "open",
        "priority": "low",
        "assignee": "comptabilite",
        "created_at": "2026-09-10T08:15:00Z",
    },
]


def _load_tickets() -> list[dict]:
    with LOCK:
        if not DATA_FILE.exists():
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            _save_tickets(SEED_TICKETS)
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _save_tickets(tickets: list[dict]) -> None:
    """Ecriture atomique : fichier temporaire puis remplacement (pas de JSON corrompu)."""
    with LOCK:
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(tickets, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(DATA_FILE)


@contextmanager
def _transaction():
    """Charge les tickets, laisse l'appelant les modifier, puis sauvegarde sous verrou."""
    with LOCK:
        tickets = _load_tickets()
        yield tickets
        _save_tickets(tickets)


class TicketCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(default="", max_length=2000)
    priority: str = Field(default="medium", pattern="^(low|medium|high)$")
    assignee: str | None = Field(default=None, max_length=100)


class TicketUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern="^(open|in_progress|closed)$")
    priority: str | None = Field(default=None, pattern="^(low|medium|high)$")
    assignee: str | None = Field(default=None, max_length=100)


app = FastAPI(title="Tickets API", version="1.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "tickets-api"}


@app.get("/", include_in_schema=False)
def homepage() -> FileResponse:
    """Frontend web : interface de gestion des tickets.
    L'agent IA, lui, n'utilise jamais ce frontend : il passe par le serveur MCP.
    """
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/api/tickets")
def list_tickets(
    status: str | None = Query(default=None, pattern="^(open|in_progress|closed)$"),
    priority: str | None = Query(default=None, pattern="^(low|medium|high)$"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    tickets = _load_tickets()
    if status:
        tickets = [t for t in tickets if t["status"] == status]
    if priority:
        tickets = [t for t in tickets if t["priority"] == priority]
    return tickets[:limit]


@app.get("/api/tickets/{ticket_id}")
def get_ticket(ticket_id: int) -> dict:
    for t in _load_tickets():
        if t["id"] == ticket_id:
            return t
    raise HTTPException(status_code=404, detail="Ticket introuvable")


@app.post("/api/tickets", status_code=201)
def create_ticket(payload: TicketCreate) -> dict:
    with _transaction() as tickets:
        new_id = max((t["id"] for t in tickets), default=0) + 1
        ticket = {
            "id": new_id,
            "title": payload.title.strip(),
            "description": payload.description.strip(),
            "status": "open",
            "priority": payload.priority,
            "assignee": (payload.assignee or "").strip() or UNASSIGNED,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        tickets.append(ticket)
    return ticket


@app.patch("/api/tickets/{ticket_id}")
def update_ticket(ticket_id: int, payload: TicketUpdate) -> dict:
    """Met a jour le titre / la description / le statut / la priorite / l'assignee d'un ticket."""
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if "assignee" in changes:
        changes["assignee"] = changes["assignee"].strip() or UNASSIGNED
    with _transaction() as tickets:
        for ticket in tickets:
            if ticket["id"] == ticket_id:
                ticket.update(changes)
                ticket["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                return ticket
    raise HTTPException(status_code=404, detail="Ticket introuvable")


@app.delete("/api/tickets/{ticket_id}")
def delete_ticket(ticket_id: int) -> dict:
    with _transaction() as tickets:
        for i, ticket in enumerate(tickets):
            if ticket["id"] == ticket_id:
                tickets.pop(i)
                return {"deleted": ticket_id}
    raise HTTPException(status_code=404, detail="Ticket introuvable")


@app.get("/api/tickets/stats/summary")
def ticket_stats() -> dict:
    tickets = _load_tickets()
    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for t in tickets:
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        by_priority[t["priority"]] = by_priority.get(t["priority"], 0) + 1
    return {"total": len(tickets), "by_status": by_status, "by_priority": by_priority}


# ---------------------------------------------------------------------------
# Agent IA en ligne : POST /api/agent
#
# Securite des cles :
# - les cles LLM ne vivent que dans les variables d'environnement du serveur
#   (jamais dans le code, jamais envoyees au navigateur) ;
# - le sous-processus MCP est lance sans elles (voir agent.mcp_server_env) ;
# - l'endpoint est limite (par IP + plafond journalier) pour qu'un visiteur ne
#   puisse pas vider le credit API.
# ---------------------------------------------------------------------------
import asyncio  # noqa: E402
import time  # noqa: E402
from collections import deque  # noqa: E402

from fastapi import Request  # noqa: E402

AGENT_MAX_QUERY = int(os.getenv("AGENT_MAX_QUERY", "500"))
AGENT_TIMEOUT = float(os.getenv("AGENT_TIMEOUT", "60"))
AGENT_RATE_PER_IP = int(os.getenv("AGENT_RATE_PER_IP", "5"))          # requetes par fenetre et par IP
AGENT_RATE_WINDOW = int(os.getenv("AGENT_RATE_WINDOW", "600"))        # fenetre en secondes (10 min)
AGENT_DAILY_CAP = int(os.getenv("AGENT_DAILY_CAP", "100"))            # requetes par jour, tous visiteurs
AGENT_CONCURRENCY = asyncio.Semaphore(int(os.getenv("AGENT_CONCURRENCY", "2")))

_RATE: dict[str, deque] = {}
_DAILY = {"day": "", "count": 0}
_RATE_LOCK = threading.Lock()


def _agent_provider() -> str | None:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return None


def _client_ip(request: Request) -> str:
    # Derriere le proxy de l'hebergeur, on prend la DERNIERE IP de X-Forwarded-For :
    # c'est celle ajoutee par le proxy. La premiere peut etre inventee par le visiteur
    # pour contourner la limite. (Le plafond journalier reste le garde-fou final.)
    fwd = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    return fwd[-1] if fwd else (request.client.host if request.client else "unknown")


def _check_quota(ip: str) -> None:
    now = time.time()
    today = datetime.now(timezone.utc).date().isoformat()
    with _RATE_LOCK:
        if _DAILY["day"] != today:
            _DAILY.update(day=today, count=0)
        if _DAILY["count"] >= AGENT_DAILY_CAP:
            raise HTTPException(status_code=429, detail="Quota journalier de la demo atteint. Revenez demain !")
        hits = _RATE.setdefault(ip, deque())
        while hits and now - hits[0] > AGENT_RATE_WINDOW:
            hits.popleft()
        if len(hits) >= AGENT_RATE_PER_IP:
            wait = int(AGENT_RATE_WINDOW - (now - hits[0])) + 1
            raise HTTPException(status_code=429, detail=f"Trop de demandes. Reessayez dans {wait} s.")
        hits.append(now)
        _DAILY["count"] += 1


class AgentQuery(BaseModel):
    query: str = Field(..., min_length=3, max_length=AGENT_MAX_QUERY)


@app.get("/api/agent/status")
def agent_status() -> dict:
    provider = _agent_provider()
    return {"enabled": provider is not None, "provider": provider, "max_query": AGENT_MAX_QUERY}


@app.post("/api/agent")
async def ask_agent(payload: AgentQuery, request: Request) -> dict:
    if _agent_provider() is None:
        raise HTTPException(status_code=503, detail="Agent IA desactive : aucune cle LLM configuree sur le serveur.")
    _check_quota(_client_ip(request))

    import agent  # import tardif : l'API reste utilisable sans les SDK LLM

    trace: list[str] = []
    try:
        async with AGENT_CONCURRENCY:
            answer = await asyncio.wait_for(agent.run_agent(payload.query.strip(), log=trace.append), AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="L'agent a mis trop de temps a repondre.")
    except Exception as exc:  # jamais de details internes (ni de cle) vers le navigateur
        print(f"[agent] erreur : {type(exc).__name__}", flush=True)
        raise HTTPException(status_code=502, detail="L'agent a rencontre une erreur. Reessayez plus tard.")
    return {"answer": answer, "trace": [t.strip() for t in trace][:40]}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT") or os.getenv("API_PORT", "8000"))
    # Le serveur MCP (sous-processus de l'agent) rappelle cette meme API en local.
    os.environ.setdefault("API_BASE", f"http://127.0.0.1:{port}")
    host = os.getenv("API_HOST", "0.0.0.0" if os.getenv("PORT") else "127.0.0.1")
    uvicorn.run(app, host=host, port=port)