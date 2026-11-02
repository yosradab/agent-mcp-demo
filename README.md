# agent-mcp-demo

A minimal, end-to-end demo of an **AI agent that operates a business API through the Model Context Protocol (MCP)**.

A support-ticket backend (FastAPI) is exposed to an LLM agent (Claude or GPT) as MCP **tools**. The agent never sees the HTTP API: it only knows tool names, descriptions and JSON schemas, and decides on its own which tools to call to answer a natural-language request.

```
 "Close every high-priority ticket assigned to technicien-1"
                        │
                        ▼
┌──────────────┐  stdio / MCP   ┌──────────────┐   HTTP/JSON   ┌──────────────┐
│   agent.py   │ ─────────────▶ │ mcp_server.py│ ────────────▶ │ api_server.py│ ──▶ data/tickets.json
│ LLM tool-use │ ◀───────────── │  MCP tools   │ ◀──────────── │   FastAPI    │
└──────────────┘                └──────────────┘               └──────┬───────┘
                                                                      │
                                                         static/ web UI (humans)
```

| Layer | File | Role |
|---|---|---|
| Business API | `api_server.py` | FastAPI CRUD + stats on tickets, JSON file storage, validation, web UI at `/` |
| MCP server | `mcp_server.py` | Wraps the API as 5 MCP tools, turns HTTP errors into readable tool errors |
| Agent | `agent.py` | Spawns the MCP server over stdio, runs an LLM tool-calling loop (Anthropic or OpenAI) |
| Web UI | `static/` | "Support Desk" dashboard for humans: stats, filters, search, create/edit/delete |

## MCP tools

| Tool | What it does |
|---|---|
| `list_tickets(status?, priority?, limit=20)` | List tickets, optionally filtered |
| `get_ticket(ticket_id)` | Full detail of one ticket |
| `create_ticket(title, description?, priority?, assignee?)` | Create a ticket (status `open`) |
| `update_ticket(ticket_id, status?, priority?, assignee?)` | Close, reassign or re-prioritise a ticket |
| `ticket_stats()` | Totals by status and priority |

`status` ∈ `open | in_progress | closed`, `priority` ∈ `low | medium | high` — enforced as enums in the tool schemas, so the LLM sees the allowed values.

Deletion is intentionally **not** exposed to the agent: destructive actions stay human-only, via the web UI.

## Quick start

Requires **Python 3.10+**.

```bash
git clone https://github.com/yosradab/agent-mcp-demo.git
cd agent-mcp-demo
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 1. Run with an LLM agent

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY=sk-... (pip install openai)
./run.sh "Quels tickets haute priorité sont encore ouverts ?"
```

Windows (PowerShell):

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
.\run.ps1 "Crée un ticket : caméra HS au 2e étage, priorité haute"
```

The script starts the API, waits for `/health`, then launches the agent (which itself starts the MCP server). Each tool call is printed, so you can watch the agent reason:

```
Connecte au serveur MCP - 5 outils disponibles.
  [agent -> tool] list_tickets({'status': 'open', 'priority': 'high'})
  [tool -> agent] {"id": 1, "title": "NVR ne repond plus apres coupure de courant", ...}

=== REPONSE DE L'AGENT ===
1 ticket haute priorité est ouvert : #1 « NVR ne répond plus après coupure de courant » (technicien-1).
```

### 2. Run without an API key

`./run.sh` with no key opens an **interactive mode**: pick a tool by number and pass JSON arguments yourself — handy for testing the MCP layer.

```
Choisissez un outil (numero, 'q' pour quitter) : 4
Entrez l'argument JSON (update_ticket) ou Entree pour aucun :
> {"ticket_id": 1, "status": "closed"}
```

### 3. Web UI

```bash
python api_server.py
```

- Dashboard: http://127.0.0.1:8000
- OpenAPI docs: http://127.0.0.1:8000/docs

Changes made by the agent show up in the UI after **Actualiser** — both sides share the same API.

### 4. Use the MCP server from Claude Desktop (or any MCP client)

Start the API (`python api_server.py`), then add to your client's MCP config:

```json
{
  "mcpServers": {
    "tickets": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/agent-mcp-demo/mcp_server.py"],
      "env": { "API_BASE": "http://127.0.0.1:8000" }
    }
  }
}
```

Self-check of the MCP → API link without any agent: `python mcp_server.py --selftest`.

## Configuration

All optional — see `.env.example`.

| Variable | Default | Used by |
|---|---|---|
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | – | agent (Anthropic takes precedence) |
| `ANTHROPIC_MODEL` / `OPENAI_MODEL` | `claude-sonnet-4-5` / `gpt-4o-mini` | agent |
| `AGENT_MAX_STEPS` | `8` | agent — max tool-calling iterations |
| `API_BASE` | `http://127.0.0.1:8000` | MCP server |
| `API_TIMEOUT` | `10` | MCP server (seconds) |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | API |
| `TICKETS_FILE` | `data/tickets.json` | API — auto-created with 3 seed tickets |

## REST API

| Method | Route | Body |
|---|---|---|
| `GET` | `/health` | – |
| `GET` | `/api/tickets?status=&priority=&limit=` | – |
| `GET` | `/api/tickets/{id}` | – |
| `POST` | `/api/tickets` → `201` | `{title, description?, priority?, assignee?}` |
| `PATCH` | `/api/tickets/{id}` | any of `{title, description, status, priority, assignee}` |
| `DELETE` | `/api/tickets/{id}` | – |
| `GET` | `/api/tickets/stats/summary` | – |

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

Covers CRUD, validation, filters, stats and concurrent creation (unique IDs under parallel requests).

## Design notes

- **Separation of concerns** — the agent only talks MCP; the MCP server only talks HTTP; only the API touches data. Swapping the JSON file for a real database changes nothing above the API.
- **Errors the LLM can act on** — API errors are re-raised as MCP `ToolError` (`HTTP 404 : Ticket introuvable`) and flagged `is_error` to the model, so it can correct itself instead of failing blindly.
- **Safe persistence** — writes are atomic (temp file + rename) and each read-modify-write runs under a single lock.
- **Provider-agnostic agent** — the same MCP tool list is mapped to Anthropic `tools` or OpenAI `functions`.

## Stack

Python · [MCP Python SDK v2](https://github.com/modelcontextprotocol/python-sdk) · FastAPI · httpx · Pydantic · Anthropic / OpenAI SDKs · vanilla JS

## Author

**Yosra Dab** — Full Stack Software Engineer · [Portfolio](https://yosradab.vercel.app) · [GitHub](https://github.com/yosradab) · [LinkedIn](https://linkedin.com/in/yosradab)
