"""Pruebas del endpoint POST /api/mods/collect con cliente HTTP sustituible."""

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.core.security import create_session_token, SESSION_COOKIE_NAME
from app.core.activity_manager import activity_manager
from app.routers import mods as mods_router


def _auth_client() -> TestClient:
    client = TestClient(app)
    token = create_session_token(settings.admin_user)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return client


def _sample_payload(mod_id, title=None, creator="TestAuthor", file_size=2 * 1024 * 1024, time_updated=1700000000):
    """Respuesta local construida con el formato de la API de Steam Workshop."""
    return {
        "response": {
            "publishedfiledetails": [
                {
                    "publishedfileid": str(mod_id),
                    "title": title or f"Mod {mod_id}",
                    "creator": creator,
                    "file_size": file_size,
                    "time_updated": time_updated,
                }
            ]
        }
    }


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeClient:
    """Cliente HTTP falso: behavior(mod_id) devuelve FakeResponse o una excepción."""

    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = []
        self.closed = False

    async def post(self, url, data=None):
        mod_id = data.get("publishedfileids[0]")
        self.calls.append(mod_id)
        result = self.behavior(mod_id)
        if isinstance(result, Exception):
            raise result
        return result

    async def aclose(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _clear_workshop_cache():
    mods_router._WORKSHOP_CACHE.clear()
    yield
    mods_router._WORKSHOP_CACHE.clear()


@pytest.fixture
def install_fake_client(monkeypatch):
    """Sustituye la fábrica de clientes HTTP del router por el cliente falso dado."""

    def _install(client: FakeClient) -> FakeClient:
        monkeypatch.setattr(mods_router, "_create_collect_client", lambda: client)
        return client

    return _install


def test_collect_requires_auth():
    client = TestClient(app)
    res = client.post("/api/mods/collect", json={"mod_ids": ["111"]})
    assert res.status_code == 401


def test_collect_success_parsing(install_fake_client):
    fake = install_fake_client(FakeClient(lambda mid: FakeResponse(200, _sample_payload(mid))))
    client = _auth_client()

    res = client.post("/api/mods/collect", json={"mod_ids": ["111", "222"]})
    assert res.status_code == 200
    body = res.json()

    assert body["total"] == 2
    assert body["success_count"] == 2
    assert body["failed_count"] == 0
    assert fake.calls == ["111", "222"]

    first, second = body["results"]
    assert first["id"] == "111"
    assert first["status"] == "success"
    assert first["title"] == "Mod 111"
    assert first["author"] == "TestAuthor"
    assert first["file_size_mb"] == 2.0
    assert first["time_updated"] == 1700000000
    assert first["remote_updated_str"]
    assert second["id"] == "222"
    assert second["status"] == "success"


def test_collect_cache_hit_skips_request(install_fake_client):
    cached_info = {
        "id": "111",
        "title": "Cached Mod",
        "creator": "CachedAuthor",
        "file_size_mb": 1.5,
        "time_updated": 1600000000,
        "remote_updated_str": "13/09/2020 12:26",
    }
    mods_router._WORKSHOP_CACHE["111"] = (cached_info, time.time())

    def _boom(mid):
        raise AssertionError("No debería haberse emitido ninguna solicitud HTTP")

    install_fake_client(FakeClient(_boom))
    client = _auth_client()

    res = client.post("/api/mods/collect", json={"mod_ids": ["111"]})
    assert res.status_code == 200
    entry = res.json()["results"][0]
    assert entry["status"] == "success"
    assert entry["cached"] is True
    assert entry["title"] == "Cached Mod"
    assert entry["author"] == "CachedAuthor"


def test_collect_force_refresh_ignores_cache(install_fake_client):
    mods_router._WORKSHOP_CACHE["111"] = (
        {"id": "111", "title": "Viejo", "creator": "X", "file_size_mb": 0.0,
         "time_updated": 1, "remote_updated_str": None},
        time.time(),
    )
    fake = install_fake_client(FakeClient(lambda mid: FakeResponse(200, _sample_payload(mid, title="Nuevo"))))
    client = _auth_client()

    res = client.post("/api/mods/collect", json={"mod_ids": ["111"], "force_refresh": True})
    assert res.status_code == 200
    entry = res.json()["results"][0]
    assert fake.calls == ["111"]
    assert entry["status"] == "success"
    assert entry["title"] == "Nuevo"


def test_collect_duplicates_fetch_once(install_fake_client):
    fake = install_fake_client(FakeClient(lambda mid: FakeResponse(200, _sample_payload(mid))))
    client = _auth_client()

    res = client.post("/api/mods/collect", json={"mod_ids": ["111", "111", "222", "111"]})
    assert res.status_code == 200
    body = res.json()

    # Cada ID único se solicita una sola vez
    assert fake.calls == ["111", "222"]
    assert body["success_count"] == 2
    assert body["duplicate_count"] == 2

    results = body["results"]
    assert results[0]["status"] == "success"
    assert results[1]["status"] == "duplicate"
    assert results[1]["duplicate_of"] == "111"
    assert results[1]["first_index"] == 0
    assert results[2]["status"] == "success"
    assert results[3]["status"] == "duplicate"
    assert results[3]["duplicate_of"] == "111"


def test_collect_invalid_ids_never_requested(install_fake_client):
    fake = install_fake_client(FakeClient(lambda mid: FakeResponse(200, _sample_payload(mid))))
    client = _auth_client()

    invalid_ids = ["", "   ", "abc", "12x3", "1" * 21, "-5"]
    res = client.post("/api/mods/collect", json={"mod_ids": invalid_ids})
    assert res.status_code == 200
    body = res.json()

    assert fake.calls == []  # Ningún ID inválido genera solicitud
    assert body["success_count"] == 0
    assert body["failed_count"] == len(invalid_ids)
    for original, entry in zip(invalid_ids, body["results"]):
        assert entry["id"] == original
        assert entry["status"] == "invalid"


def test_collect_single_timeout_does_not_break_batch(install_fake_client):
    def behavior(mid):
        if mid == "111":
            return httpx.TimeoutException("timeout simulado")
        return FakeResponse(200, _sample_payload(mid))

    fake = install_fake_client(FakeClient(behavior))
    client = _auth_client()

    res = client.post("/api/mods/collect", json={"mod_ids": ["111", "222", "333"]})
    assert res.status_code == 200
    body = res.json()

    assert body["success_count"] == 2
    assert body["failed_count"] == 1
    statuses = {e["id"]: e["status"] for e in body["results"]}
    assert statuses == {"111": "timeout", "222": "success", "333": "success"}

    # El lote registró los contadores en el log de actividad
    logs = activity_manager.get_recent()
    assert any(
        log["category"] == "Mods" and "2 exitosos" in log["message"] and "1 fallidos" in log["message"]
        for log in logs
    )


def test_collect_http_error_marks_failed(install_fake_client):
    install_fake_client(FakeClient(lambda mid: FakeResponse(500, {})))
    client = _auth_client()

    res = client.post("/api/mods/collect", json={"mod_ids": ["111"]})
    assert res.status_code == 200
    entry = res.json()["results"][0]
    assert entry["status"] == "failed"
    assert res.json()["failed_count"] == 1


@pytest.mark.asyncio
async def test_collect_batch_timeout_marks_remaining_entries():
    """Con el límite de lote agotado, las entradas pendientes quedan como timeout (sin 500)."""
    fake = FakeClient(lambda mid: FakeResponse(200, _sample_payload(mid)))
    result = await mods_router.collect_workshop_metadata(["111", "222"], client=fake, batch_timeout=0.0)

    assert result["success_count"] == 0
    assert result["failed_count"] == 2
    assert all(e["status"] == "timeout" for e in result["results"])
    assert fake.calls == []  # Nunca se llegó a solicitar nada
