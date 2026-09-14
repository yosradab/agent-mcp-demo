"""API metier locale : gestion de tickets support (simulation d'un vrai backend).

C'est LA couche qui contient la donnee metier reelle : tickets, clients, etc.
L'agent IA ne doit jamais acceder directement a cette base : il passe par le
serveur MCP, qui fait le lien.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DATA_DIR = Path(__file__).parent / "data"
DATA_FILE = DATA_DIR / "tickets.json"
STATIC_DIR = Path(__file__).parent / "static"
LOCK = threading.Lock()

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
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            DATA_FILE.write_text(json.dumps(SEED_TICKETS, indent=2), encoding="utf-8")
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _save_tickets(tickets: list[dict]) -> None:
    with LOCK:
        DATA_FILE.write_text(json.dumps(tickets, indent=2, ensure_ascii=False), encoding="utf-8")


class TicketCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(default="", max_length=2000)
    priority: str = Field(default="medium", pattern="^(low|medium|high)$")
    assignee: str | None = Field(default=None, max_length=100)


class TicketUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|in_progress|closed)$")
    priority: str | None = Field(default=None, pattern="^(low|medium|high)$")
    assignee: str | None = Field(default=None, max_length=100)


app = FastAPI(title="Tickets API", version="1.0.0")


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


@app.post("/api/tickets")
def create_ticket(payload: TicketCreate) -> dict:
    tickets = _load_tickets()
    new_id = max((t["id"] for t in tickets), default=0) + 1
    ticket = {
        "id": new_id,
        "title": payload.title,
        "description": payload.description,
        "status": "open",
        "priority": payload.priority,
        "assignee": payload.assignee or "non-assigne",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    tickets.append(ticket)
    _save_tickets(tickets)
    return ticket


@app.patch("/api/tickets/{ticket_id}")
def update_ticket(ticket_id: int, payload: TicketUpdate) -> dict:
    """Met a jour le statut / la priorite / l'assignee d'un ticket."""
    tickets = _load_tickets()
    for ticket in tickets:
        if ticket["id"] == ticket_id:
            changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
            ticket.update(changes)
            _save_tickets(tickets)
            return ticket
    raise HTTPException(status_code=404, detail="Ticket introuvable")


@app.delete("/api/tickets/{ticket_id}")
def delete_ticket(ticket_id: int) -> dict:
    tickets = _load_tickets()
    for i, ticket in enumerate(tickets):
        if ticket["id"] == ticket_id:
            removed = tickets.pop(i)
            _save_tickets(tickets)
            return {"deleted": removed["id"]}
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)