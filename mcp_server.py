"""Serveur MCP : expose les tickets de l'API metier comme des OUTILS utilisables par un agent IA.

Role dans l'architecture :
- Un agent (Claude, GPT, ...) se connecte a ce serveur via le protocole MCP.
- Le serveur declare des "tools" (list_tickets, get_ticket, create_ticket, ticket_stats).
- L'agent peut appeler ces tools comme des fonctions : le serveur se charge de
  talker a l'API metier (FastAPI) en HTTP et de renvoyer le resultat au format JSON.

L'agent n'a aucune idee de la forme de l'API : il ne connait que des outils MCP
dothes d'une description et d'un schema JSON.
"""

import os

import httpx
from mcp.server.mcpserver import MCPServer

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
TIMEOUT = float(os.getenv("API_TIMEOUT", "10"))

mcp = MCPServer(
    "tickets",
    instructions=(
        "Tu es un assistant de gestion de tickets. Utilise les outils fournis "
        "pour lister, lire, creer des tickets ou obtenir des statistiques."
    ),
)


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=API_BASE, timeout=TIMEOUT)


@mcp.tool()
async def list_tickets(
    status: str | None = None,
    priority: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Liste les tickets (optionnellement filtres par statut ou priorite).

    Args:
        status: "open", "in_progress" ou "closed".
        priority: "low", "medium" ou "high".
        limit: nombre maximum de tickets (1-100).
    """
    async with _http() as client:
        params = {"limit": limit}
        if status:
            params["status"] = status
        if priority:
            params["priority"] = priority
        resp = await client.get("/api/tickets", params=params)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def get_ticket(ticket_id: int) -> dict:
    """Recupere le detail complet d'un ticket par son identifiant."""
    async with _http() as client:
        resp = await client.get(f"/api/tickets/{ticket_id}")
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def create_ticket(
    title: str,
    description: str = "",
    priority: str = "medium",
    assignee: str | None = None,
) -> dict:
    """Cree un nouveau ticket support.

    Args:
        title: titre court du ticket.
        description: details du probleme.
        priority: "low", "medium" ou "high".
        assignee: personne chargee du traitement (optionnel).
    """
    async with _http() as client:
        resp = await client.post(
            "/api/tickets",
            json={
                "title": title,
                "description": description,
                "priority": priority,
                "assignee": assignee,
            },
        )
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def ticket_stats() -> dict:
    """Retourne des statistiques sur les tickets (total, repartition par statut et priorite)."""
    async with _http() as client:
        resp = await client.get("/api/tickets/stats/summary")
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:  # verifie le lien MCP -> API sans agent
        import asyncio

        async def _selftest() -> None:
            print("--- API stats ---")
            print(await ticket_stats())
            print("--- list tickets ---")
            print(await list_tickets(limit=5))
            print("--- create ticket ---")
            print(await create_ticket("Ticket de test selftest", "Lance par --selftest", "low", "bot"))

        asyncio.run(_selftest())
    else:
        mcp.run()