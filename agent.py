"""Agent IA : connecte un modele (Claude / GPT / ...) a un serveur MCP via stdio.

Flux :
1. L'agent demarre le serveur MCP (mcp_server.py) en sous-processus.
2. Il negocie les capacites (initialize) et recupere la liste des tools.
3. L'utilisateur pose une question en langage naturel.
4. L'agent demande au LLM de choisir l'outil a appeler (tool calling).
5. L'agent execute l'appel via MCP, renvoie le resultat au LLM, et repete
   jusqu'a obtenir une reponse finale.

Sans cle API : le mode interactif permet de piloter les outils manuellement.
"""

import asyncio
import json
import os
import sys
from datetime import date
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_STEPS = 8


def format_tool_result(result: Any) -> str:
    """Convertit le resultat MCP (structuredContent ou text) en chaine lisible."""
    if getattr(result, "structuredContent", None):
        return json.dumps(result.structuredContent, ensure_ascii=False, indent=2)
    parts = [getattr(block, "text", str(block)) for block in (result.content or [])]
    return "\n".join(parts) if parts else "(vide)"


async def run_with_anthropic(session, tools, query: str) -> str:
    import anthropic

    client = anthropic.Anthropic()

    system_prompt = (
        "Tu es un assistant metier specialise dans la gestion de tickets.\n"
        "Tu as acces a des outils MCP qui parlent a l'API tickets.\n"
        "Reponds en francais, de facon concise, et base-toi uniquement sur "
        "les resultats des outils.\n"
        f"Date du jour : {date.today().isoformat()}."
    )
    messages: list[dict] = [{"role": "user", "content": query}]
    tool_schemas = [
        {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
        for t in tools
    ]

    for _ in range(MAX_STEPS):
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=system_prompt,
            tools=tool_schemas,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            return "".join(getattr(b, "text", "") for b in resp.content)

        tool_results = []
        for block in tool_uses:
            print(f"  [agent -> tool] {block.name}({block.input})")
            result = await session.call_tool(block.name, block.input or {})
            rendered = format_tool_result(result)
            print(f"  [tool -> agent] {rendered[:300]}")
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": rendered[:2000],
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return "Nombre maximal d'etapes atteint sans reponse finale."


async def run_with_openai(session, tools, query: str) -> str:
    from openai import OpenAI

    client = OpenAI()

    system_prompt = (
        "Tu es un assistant metier specialise dans la gestion de tickets.\n"
        "Tu as acces a des outils MCP qui parlent a l'API tickets.\n"
        "Reponds en francais, de facon concise, et base-toi uniquement sur "
        "les resultats des outils.\n"
        f"Date du jour : {date.today().isoformat()}."
    )
    messages: list[dict] = [{"role": "system", "content": system_prompt}, {"role": "user", "content": query}]
    tool_schemas = [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.inputSchema,
            },
        }
        for t in tools
    ]

    for _ in range(MAX_STEPS):
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=tool_schemas,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": msg.tool_calls})
        if not msg.tool_calls:
            return msg.content or "(absence de reponse)"

        for call in msg.tool_calls:
            print(f"  [agent -> tool] {call.function.name}({call.function.arguments})")
            args = json.loads(call.function.arguments or "{}")
            result = await session.call_tool(call.function.name, args)
            rendered = format_tool_result(result)
            print(f"  [tool -> agent] {rendered[:300]}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": rendered[:2000],
                }
            )

    return "Nombre maximal d'etapes atteint sans reponse finale."


async def interactive_loop(session, tools) -> None:
    print("\nMode interactif (aucune cle API detectee). Outils disponibles :")
    for i, t in enumerate(tools, start=1):
        print(f"  {i}. {t.name} - {t.description}")
    print("  q. Quitter\n")

    while True:
        try:
            choice = input("Choisissez un outil (numero, 'q' pour quitter) : ").strip()
        except EOFError:
            print("(fin de saisie)")
            break
        if choice.lower() == "q":
            break
        if not choice.isdigit():
            continue
        idx = int(choice) - 1
        if not (0 <= idx < len(tools)):
            continue

        tool = tools[idx]
        print(f"Entrez l'argument JSON ({tool.name}) ou Entree pour aucun :")
        try:
            raw = input("> ").strip()
        except EOFError:
            print("(fin de saisie)")
            break
        args = json.loads(raw) if raw else {}
        result = await session.call_tool(tool.name, args or None)
        print("\nResultat :")
        print(format_tool_result(result)[:1000])
        print()


async def main() -> None:
    query = ""
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    elif not ANTHROPIC_KEY and not OPENAI_KEY:
        query = None
    else:
        query = input("Votre demande pour l'agent : ").strip()

    server = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tools = tools_result.tools
            print(f"Connecte au serveur MCP - {len(tools)} outils disponibles.")
            for t in tools:
                print(f"  - {t.name}: {t.description}")

            if query is None:
                await interactive_loop(session, tools)
            elif ANTHROPIC_KEY:
                answer = await run_with_anthropic(session, tools, query)
                print("\n=== REPONSE DE L'AGENT ===\n" + answer)
            elif OPENAI_KEY:
                answer = await run_with_openai(session, tools, query)
                print("\n=== REPONSE DE L'AGENT ===\n" + answer)
            else:
                print(
                    "\nPas de cle API (ANTHROPIC_API_KEY / OPENAI_API_KEY) detectee : "
                    "la demande en langage naturel est desactivee.\n"
                    "Mode interactif -> vous pilotez les outils manuellement.\n"
                )
                await interactive_loop(session, tools)


if __name__ == "__main__":
    asyncio.run(main())