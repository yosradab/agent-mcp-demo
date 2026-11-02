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
