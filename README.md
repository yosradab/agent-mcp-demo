# agent-mcp-demo

Démo complète et minimale d'un **agent IA qui pilote une API métier via le Model Context Protocol (MCP)**.

Un backend de tickets de support (FastAPI) est exposé à un agent LLM (Claude ou GPT) sous forme d'**outils MCP**. L'agent ne voit jamais l'API HTTP : il connaît seulement le nom des outils, leur description et leur schéma JSON, et choisit lui-même quels outils appeler pour répondre à une demande en langage naturel.

```
 "Ferme tous les tickets haute priorité assignés à technicien-1"
                        │
                        ▼
┌──────────────┐  stdio / MCP   ┌──────────────┐   HTTP/JSON   ┌──────────────┐
│   agent.py   │ ─────────────▶ │ mcp_server.py│ ────────────▶ │ api_server.py│ ──▶ data/tickets.json
│ LLM tool-use │ ◀───────────── │  outils MCP  │ ◀──────────── │   FastAPI    │
└──────────────┘                └──────────────┘               └──────┬───────┘
                                                                      │
                                                        static/ interface web (humains)
```

| Couche | Fichier | Rôle |
|---|---|---|
| API métier | `api_server.py` | CRUD FastAPI + statistiques sur les tickets, stockage JSON, validation, interface web sur `/` |
| Serveur MCP | `mcp_server.py` | Expose l'API sous forme de 5 outils MCP et transforme les erreurs HTTP en erreurs d'outil lisibles |
| Agent | `agent.py` | Lance le serveur MCP en stdio et exécute une boucle d'appels d'outils avec le LLM (Anthropic ou OpenAI) |
| Interface web | `static/` | Tableau de bord « Support Desk » pour les humains : stats, filtres, recherche, création, édition, suppression |

## Outils MCP

| Outil | Rôle |
|---|---|
| `list_tickets(status?, priority?, limit=20)` | Liste les tickets, avec filtres optionnels |
| `get_ticket(ticket_id)` | Détail complet d'un ticket |
| `create_ticket(title, description?, priority?, assignee?)` | Crée un ticket (statut `open`) |
| `update_ticket(ticket_id, status?, priority?, assignee?)` | Ferme, réassigne ou change la priorité d'un ticket |
| `ticket_stats()` | Totaux par statut et par priorité |

`status` ∈ `open | in_progress | closed` et `priority` ∈ `low | medium | high` sont déclarés comme enums dans les schémas des outils : le LLM voit les valeurs autorisées.

La suppression n'est volontairement **pas** exposée à l'agent : les actions destructives restent réservées aux humains, via l'interface web.

## Démarrage rapide

Prérequis : **Python 3.10+**.

```bash
git clone https://github.com/yosradab/agent-mcp-demo.git
cd agent-mcp-demo
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

### 1. Avec un agent LLM

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # ou OPENAI_API_KEY=sk-... (pip install openai)
./run.sh "Quels tickets haute priorité sont encore ouverts ?"
```

Windows (PowerShell) :

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
.\run.ps1 "Crée un ticket : caméra HS au 2e étage, priorité haute"
```

Le script démarre l'API, attend `/health`, puis lance l'agent (qui démarre lui-même le serveur MCP). Chaque appel d'outil est affiché, ce qui permet de suivre le raisonnement de l'agent :

```
Connecte au serveur MCP - 5 outils disponibles.
  [agent -> tool] list_tickets({'status': 'open', 'priority': 'high'})
  [tool -> agent] {"id": 1, "title": "NVR ne repond plus apres coupure de courant", ...}

=== REPONSE DE L'AGENT ===
1 ticket haute priorité est ouvert : #1 « NVR ne répond plus après coupure de courant » (technicien-1).
```

### 2. Sans clé API

Sans clé, `./run.sh` ouvre un **mode interactif** : on choisit un outil par son numéro et on passe soi-même les arguments JSON. Pratique pour tester la couche MCP.

```
Choisissez un outil (numero, 'q' pour quitter) : 4
Entrez l'argument JSON (update_ticket) ou Entree pour aucun :
> {"ticket_id": 1, "status": "closed"}
```

### 3. Interface web

```bash
python api_server.py
```

- Tableau de bord : http://127.0.0.1:8000
- Documentation OpenAPI : http://127.0.0.1:8000/docs

Les modifications faites par l'agent apparaissent dans l'interface après **Actualiser** : les deux passent par la même API.

### 4. Depuis Claude Desktop (ou tout client MCP)

Démarrer l'API (`python api_server.py`), puis ajouter dans la configuration MCP du client :

```json
{
  "mcpServers": {
    "tickets": {
      "command": "/chemin/absolu/vers/.venv/bin/python",
      "args": ["/chemin/absolu/vers/agent-mcp-demo/mcp_server.py"],
      "env": { "API_BASE": "http://127.0.0.1:8000" }
    }
  }
}
```

Pour vérifier le lien MCP → API sans agent : `python mcp_server.py --selftest`.

## Configuration

Tout est optionnel, voir `.env.example`.

| Variable | Défaut | Utilisée par |
|---|---|---|
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | – | agent (Anthropic est prioritaire) |
| `ANTHROPIC_MODEL` / `OPENAI_MODEL` | `claude-sonnet-4-5` / `gpt-4o-mini` | agent |
| `AGENT_MAX_STEPS` | `8` | agent : nombre max d'itérations d'appels d'outils |
| `API_BASE` | `http://127.0.0.1:8000` | serveur MCP |
| `API_TIMEOUT` | `10` | serveur MCP (secondes) |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | API (`PORT` de l'hébergeur prioritaire, écoute alors sur `0.0.0.0`) |
| `AGENT_RATE_PER_IP` / `AGENT_RATE_WINDOW` | `5` / `600` | web : requêtes agent par IP et par fenêtre (secondes) |
| `AGENT_DAILY_CAP` | `100` | web : plafond de requêtes agent par jour, tous visiteurs |
| `AGENT_MAX_QUERY` / `AGENT_TIMEOUT` | `500` / `60` | web : longueur max d'une demande, délai max (secondes) |
| `TICKETS_FILE` | `data/tickets.json` | API : créé automatiquement avec 3 tickets d'exemple |

## API REST

| Méthode | Route | Corps |
|---|---|---|
| `GET` | `/health` | – |
| `GET` | `/api/tickets?status=&priority=&limit=` | – |
| `GET` | `/api/tickets/{id}` | – |
| `POST` | `/api/tickets` → `201` | `{title, description?, priority?, assignee?}` |
| `PATCH` | `/api/tickets/{id}` | n'importe quel champ parmi `{title, description, status, priority, assignee}` |
| `DELETE` | `/api/tickets/{id}` | – |
| `GET` | `/api/tickets/stats/summary` | – |
| `GET` | `/api/agent/status` | – (l'agent est-il activé ?) |
| `POST` | `/api/agent` | `{query}` → `{answer, trace}` (limité, voir Déploiement) |

## Déploiement (Render)

Le repo contient un `Dockerfile` et un blueprint `render.yaml` : l'API, le frontend et l'agent tournent dans un seul service.

1. Sur [render.com](https://render.com) : **New → Blueprint**, choisissez ce repo.
2. Render demande `ANTHROPIC_API_KEY` : collez votre clé **dans Render uniquement**. Pour utiliser GPT à la place, ajoutez `OPENAI_API_KEY` dans *Environment* et décommentez `openai` dans `requirements.txt`.
3. Déployez. L'URL publique affiche le Support Desk avec le panneau « Demandez à l'agent IA ».

Sans clé, le site fonctionne quand même : seul le panneau agent est désactivé.

### Sécurité des clés

- Les clés ne sont jamais dans le code ni dans l'historique Git : `.env` est ignoré par Git **et** par Docker (`.dockerignore`).
- Elles restent côté serveur : le navigateur n'en voit aucune, et les erreurs renvoyées au client ne contiennent aucun détail interne.
- Le sous-processus MCP est lancé **sans** les clés LLM (environnement minimal) : seul l'agent parle au modèle.
- `/api/agent` est limité (par IP, plafond journalier, longueur des demandes, délai, 2 requêtes simultanées max) pour qu'un visiteur ne puisse pas vider votre crédit.
- Recommandé : fixez aussi une **limite de dépense mensuelle** dans la console Anthropic (ou OpenAI). C'est le garde-fou ultime.

> Sur l'offre gratuite de Render, le service s'endort après 15 min d'inactivité (premier chargement ~1 min) et `data/tickets.json` repart des 3 tickets d'exemple à chaque redémarrage. C'est voulu pour une démo.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

Couvre le CRUD, la validation, les filtres, les statistiques et la création concurrente (identifiants uniques sous requêtes parallèles).

## Choix de conception

- **Séparation des responsabilités** : l'agent ne parle que MCP, le serveur MCP ne parle que HTTP, et seule l'API touche aux données. Remplacer le fichier JSON par une vraie base de données ne change rien au-dessus de l'API.
- **Des erreurs exploitables par le LLM** : les erreurs de l'API sont relancées en `ToolError` MCP (`HTTP 404 : Ticket introuvable`) et signalées `is_error` au modèle, qui peut se corriger au lieu d'échouer à l'aveugle.
- **Persistance sûre** : écritures atomiques (fichier temporaire + renommage) et chaque lecture-modification-écriture s'exécute sous un verrou unique.
- **Agent indépendant du fournisseur** : la même liste d'outils MCP est convertie en `tools` Anthropic ou en `functions` OpenAI.

## Stack

Python · [MCP Python SDK v2](https://github.com/modelcontextprotocol/python-sdk) · FastAPI · httpx · Pydantic · SDK Anthropic / OpenAI · JavaScript vanilla

## Auteur

**Yosra Dab** — Ingénieure logiciel Full Stack · [Portfolio](https://yosradab.vercel.app) · [GitHub](https://github.com/yosradab) · [LinkedIn](https://linkedin.com/in/yosradab)
