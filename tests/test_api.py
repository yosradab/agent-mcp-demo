"""Tests de l'API metier (FastAPI) sur un fichier de donnees temporaire."""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_server  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "DATA_FILE", tmp_path / "tickets.json")
    return TestClient(api_server.app)


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_seed_and_filters(client):
    assert len(client.get("/api/tickets").json()) == 3
    high = client.get("/api/tickets", params={"priority": "high"}).json()
    assert [t["id"] for t in high] == [1]
    assert client.get("/api/tickets", params={"status": "bogus"}).status_code == 422


def test_create_update_delete(client):
    resp = client.post("/api/tickets", json={"title": "Camera HS", "priority": "high", "assignee": "  "})
    assert resp.status_code == 201
    ticket = resp.json()
    assert ticket["status"] == "open"
    assert ticket["assignee"] == api_server.UNASSIGNED

    upd = client.patch(f"/api/tickets/{ticket['id']}", json={"title": "Camera HS etage 2", "status": "closed"}).json()
    assert upd["title"] == "Camera HS etage 2"
    assert upd["status"] == "closed"
    assert "updated_at" in upd

    assert client.delete(f"/api/tickets/{ticket['id']}").json() == {"deleted": ticket["id"]}
    assert client.get(f"/api/tickets/{ticket['id']}").status_code == 404


def test_validation(client):
    assert client.post("/api/tickets", json={"title": "ab"}).status_code == 422
    assert client.post("/api/tickets", json={"title": "abc", "priority": "urgent"}).status_code == 422
    assert client.patch("/api/tickets/999", json={"status": "closed"}).status_code == 404


def test_stats(client):
    stats = client.get("/api/tickets/stats/summary").json()
    assert stats["total"] == 3
    assert stats["by_status"] == {"open": 2, "in_progress": 1}


def test_concurrent_creates_get_unique_ids(client):
    def create(i):
        return client.post("/api/tickets", json={"title": f"Ticket concurrent {i}"}).json()["id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(create, range(20)))
    assert len(set(ids)) == 20
    assert client.get("/api/tickets/stats/summary").json()["total"] == 23


# ---------------------------------------------------------------------------
# Agent web : cle absente, validation, limites anti-abus
# ---------------------------------------------------------------------------
@pytest.fixture()
def agent_env(client, monkeypatch):
    """Simule une cle configuree et un agent qui repond sans appeler de LLM."""
    import agent

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(api_server, "_RATE", {})
    monkeypatch.setattr(api_server, "_DAILY", {"day": "", "count": 0})

    async def fake_run_agent(query, log=print):
        log("[agent -> tool] list_tickets({})")
        return f"ok: {query}"

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)
    return client


def test_agent_disabled_without_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert client.get("/api/agent/status").json()["enabled"] is False
    assert client.post("/api/agent", json={"query": "liste les tickets"}).status_code == 503


def test_agent_answers_and_never_leaks_key(agent_env):
    status = agent_env.get("/api/agent/status").json()
    assert status == {"enabled": True, "provider": "anthropic", "max_query": api_server.AGENT_MAX_QUERY}
    resp = agent_env.post("/api/agent", json={"query": "liste les tickets"})
    assert resp.status_code == 200
    assert resp.json()["answer"] == "ok: liste les tickets"
    assert "test-key-not-real" not in resp.text


def test_agent_rejects_long_query(agent_env):
    assert agent_env.post("/api/agent", json={"query": "x" * 501}).status_code == 422


def test_agent_rate_limit_per_ip(agent_env, monkeypatch):
    monkeypatch.setattr(api_server, "AGENT_RATE_PER_IP", 2)
    hdr = {"x-forwarded-for": "1.2.3.4"}
    assert agent_env.post("/api/agent", json={"query": "un"*2}, headers=hdr).status_code == 200
    assert agent_env.post("/api/agent", json={"query": "un"*2}, headers=hdr).status_code == 200
    assert agent_env.post("/api/agent", json={"query": "un"*2}, headers=hdr).status_code == 429
    # usurper la premiere IP de X-Forwarded-For ne contourne pas la limite
    spoof = {"x-forwarded-for": "9.9.9.9, 1.2.3.4"}
    assert agent_env.post("/api/agent", json={"query": "un"*2}, headers=spoof).status_code == 429


def test_agent_daily_cap(agent_env, monkeypatch):
    monkeypatch.setattr(api_server, "AGENT_DAILY_CAP", 1)
    assert agent_env.post("/api/agent", json={"query": "abc"}, headers={"x-forwarded-for": "5.5.5.5"}).status_code == 200
    assert agent_env.post("/api/agent", json={"query": "abc"}, headers={"x-forwarded-for": "6.6.6.6"}).status_code == 429


def test_agent_error_hides_details(agent_env, monkeypatch):
    import agent

    async def boom(query, log=print):
        raise RuntimeError("secret detail sk-ant-xxx")

    monkeypatch.setattr(agent, "run_agent", boom)
    resp = agent_env.post("/api/agent", json={"query": "abc"})
    assert resp.status_code == 502 and "sk-ant" not in resp.text


def test_agent_error_categories_never_leak_key(agent_env, monkeypatch):
    import agent

    class AuthenticationError(Exception):
        pass

    async def bad_key(query, log=print):
        raise ExceptionGroup("tg", [AuthenticationError("invalid x-api-key test-key-not-real")])

    monkeypatch.setattr(agent, "run_agent", bad_key)
    resp = agent_env.post("/api/agent", json={"query": "abc"})
    assert resp.status_code == 502
    assert "cle API" in resp.json()["detail"] and "test-key-not-real" not in resp.text
