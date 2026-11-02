"""Serveur MCP : expose les tickets de l'API metier comme des OUTILS utilisables par un agent IA.

Role dans l'architecture :
- Un agent (Claude, GPT, ...) se connecte a ce serveur via le protocole MCP.
- Le serveur declare des "tools" (list_tickets, get_ticket, create_ticket,
  update_ticket, ticket_stats).
- L'agent peut appeler ces tools comme des fonctions : le serveur se charge de
  parler a l'API metier (FastAPI) en HTTP et de renvoyer le resultat au format JSON.

L'agent n'a aucune idee de la forme de l'API : il ne connait que des outils MCP
dotes d'une description et d'un schema JSON.
"""

import os
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
TIMEOUT = float(os.getenv("API_TIMEOUT", "10"))

Status = Literal["open", "in_progress", "closed"]
Priority = Literal["low", "medium", "high"]

mcp = MCPServer(
    "tickets",
    instructions=(
        "Tu es un assistant de gestion de tickets. Utilise les outils fournis "
        "pour lister, lire, creer, mettre a jour des tickets ou obtenir des statistiques."
    ),
)


async def _request(method: str, path: str, **kwargs: Any) -> Any:
    """Appelle l'API metier et convertit les erreurs HTTP en ToolError lisible.

    Un ToolError est renvoye a l'agent avec son message (ex. "Ticket introuvable"),
    ce qui lui permet de corriger son appel au lieu de recevoir une erreur opaque.
    """
    try:
        async with httpx.AsyncClient(base_url=API_BASE, timeout=TIMEOUT) as client:
            resp = await client.request(method, path, **kwargs)
    except httpx.RequestError as exc:
        raise ToolError(f"API tickets injoignable ({API_BASE}) : {exc}") from exc

    if resp.is_error:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        raise ToolError(f"HTTP {resp.status_code} : {detail}")
    return resp.json()


@mcp.tool()
async def list_tickets(
    status: Status | None = None,
    priority: Priority | None = None,
    limit: int = 20,
) -> list[dict]:
    """Liste les tickets (optionnellement filtres par statut ou priorite).

    Args:
        status: "open", "in_progress" ou "closed".
        priority: "low", "medium" ou "high".
        limit: nombre maximum de tickets (1-100).
    """
    params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
    if status:
        params["status"] = status
    if priority:
        params["priority"] = priority
    return await _request("GET", "/api/tickets", params=params)


@mcp.tool()
async def get_ticket(ticket_id: int) -> dict:
    """Recupere le detail complet d'un ticket par son identifiant."""
    return await _request("GET", f"/api/tickets/{ticket_id}")


@mcp.tool()
async def create_ticket(
    title: str,
    description: str = "",
    priority: Priority = "medium",
    assignee: str | None = None,
) -> dict:
    """Cree un nouveau ticket support (statut initial : open).

    Args:
        title: titre court du ticket (3 a 200 caracteres).
        description: details du probleme.
        priority: "low", "medium" ou "high".
        assignee: personne chargee du traitement (optionnel).
    """
    return await _request(
        "POST",
        "/api/tickets",
        json={"title": title, "description": description, "priority": priority, "assignee": assignee},
    )


@mcp.tool()
async def update_ticket(
    ticket_id: int,
    status: Status | None = None,
    priority: Priority | None = None,
    assignee: str | None = None,
) -> dict:
    """Met a jour un ticket existant : changer son statut (ex. le fermer), sa priorite ou son assignee.

    Args:
        ticket_id: identifiant du ticket.
        status: nouveau statut "open", "in_progress" ou "closed".
        priority: nouvelle priorite "low", "medium" ou "high".
        assignee: nouvelle personne assignee.
    """
    changes = {k: v for k, v in {"status": status, "priority": priority, "assignee": assignee}.items() if v is not None}
    if not changes:
        raise ToolError("Aucun champ a mettre a jour (status, priority ou assignee).")
    return await _request("PATCH", f"/api/tickets/{ticket_id}", json=changes)


@mcp.tool()
async def ticket_stats() -> dict:
    """Retourne des statistiques sur les tickets (total, repartition par statut et priorite)."""
    return await _request("GET", "/api/tickets/stats/summary")


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:  # verifie le lien MCP -> API sans agent
        import asyncio

        async def _selftest() -> None:
            print("--- API stats ---")
            print(await ticket_stats())
            print("--- list tickets ---")
            print(await list_tickets(limit=5))
            print("--- create + update ticket ---")
            created = await create_ticket("Ticket de test selftest", "Lance par --selftest", "low", "bot")
            print(created)
            print(await update_ticket(created["id"], status="closed"))

        asyncio.run(_selftest())
    else:
        mcp.run()
