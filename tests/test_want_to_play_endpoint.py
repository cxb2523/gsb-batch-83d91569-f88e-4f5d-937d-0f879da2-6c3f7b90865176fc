"""
Tests sobre /api/ra/connect, /api/ra/disconnect, /api/ra/status y
/api/want_to_play (api/index.py) -- cruzan la lista "Want to Play" de
RetroAchievements del usuario contra el catálogo local por ID de juego,
guardando la API Key en una sesión de servidor (cookie firmada + HttpOnly)
en vez de devolverla o pedirla en cada request. Mockean
RetroAchievementsClient.get_want_to_play_list para no pegarle a la API real
de RA.
"""

from unittest.mock import patch

import api.index as api_module

_FAKE_CATALOG = [
    {
        "id": "1",
        "name": "Sonic the Hedgehog",
        "consoles": ["Genesis/Mega Drive"],
        "versions": 2,
        "sample_rom_path": "Genesis/Mega Drive/Sonic the Hedgehog.zip",
        "image_icon": None,
        "achievements": 35,
    },
    {
        "id": "2",
        "name": "Other Game",
        "consoles": ["NES"],
        "versions": 1,
        "sample_rom_path": "NES-Famicom/Other Game.zip",
        "image_icon": None,
        "achievements": None,
    },
]


def _client():
    # Un test_client por test mantiene su propia cookie jar -- simula un
    # browser real a lo largo de varias requests (connect -> want_to_play).
    return api_module.app.test_client()


def _connect(client, api_key="x", username="y", wtp_games=None):
    with patch.object(api_module.RetroAchievementsClient, "get_want_to_play_list", return_value=wtp_games or []):
        return client.post("/api/ra/connect", data={"api_key": api_key, "username": username})


# --- /api/ra/connect --------------------------------------------------------


def test_connect_missing_params_returns_400():
    resp = _client().post("/api/ra/connect", data={})
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_connect_ra_api_error_returns_502_without_leaking_detail():
    with patch.object(
        api_module.RetroAchievementsClient,
        "get_want_to_play_list",
        side_effect=api_module.RetroAchievementsAPIError("detalle interno sensible"),
    ):
        resp = _client().post("/api/ra/connect", data={"api_key": "x", "username": "y"})

    assert resp.status_code == 502
    data = resp.get_json()
    assert data["success"] is False
    assert data["message"]
    assert "detalle interno sensible" not in data["message"]


def test_connect_success_never_returns_credentials():
    """No devuelve ni la api_key ni el username que el cliente acaba de
    mandar -- lo segundo porque reflejar de vuelta un valor que llega en el
    mismo request es exactamente el patrón que CodeQL marca como XSS
    reflejado, y el cliente ya lo tiene en su propio form de todos modos.
    Tampoco devuelve conteos: el frontend los trae por separado de
    /api/want_to_play apenas ve la cuenta conectada."""
    fake_wtp = [{"ID": 1, "Title": "Sonic the Hedgehog"}]
    with patch.object(api_module.RetroAchievementsClient, "get_want_to_play_list", return_value=fake_wtp):
        resp = _connect(_client(), api_key="super-secret-key", username="pipetboy", wtp_games=fake_wtp)

    assert resp.status_code == 200
    assert resp.get_json() == {"success": True}
    assert "super-secret-key" not in resp.get_data(as_text=True)
    assert "pipetboy" not in resp.get_data(as_text=True)


# --- /api/want_to_play (requiere sesión) ------------------------------------


def test_want_to_play_without_session_returns_401():
    resp = _client().get("/api/want_to_play")
    assert resp.status_code == 401
    assert resp.get_json()["success"] is False


def test_want_to_play_uses_session_after_connect():
    """La misma sesión (test_client mantiene cookies) conecta una vez y
    después pide la lista sin volver a mandar la API Key."""
    client = _client()
    fake_wtp = [{"ID": 1, "Title": "Sonic the Hedgehog"}]
    with patch.object(api_module, "build_games_index", return_value=_FAKE_CATALOG):
        connect_resp = _connect(client, wtp_games=fake_wtp)
        assert connect_resp.status_code == 200

        with patch.object(api_module.RetroAchievementsClient, "get_want_to_play_list", return_value=fake_wtp):
            resp = client.get("/api/want_to_play")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["items"] == [_FAKE_CATALOG[0]]


def test_want_to_play_against_real_catalog_smoke():
    """Smoke test sin mockear build_games_index(): prueba contra el dataset
    real que el game_id "1" de Data/TamperMonkeyRetroachievements.json es
    efectivamente el juego #1 de RA (Sonic the Hedgehog) -- la asunción
    central de la que depende todo el endpoint."""
    client = _client()
    fake_wtp = [{"ID": 1, "Title": "Sonic the Hedgehog"}]
    _connect(client, wtp_games=fake_wtp)

    with patch.object(api_module.RetroAchievementsClient, "get_want_to_play_list", return_value=fake_wtp):
        resp = client.get("/api/want_to_play")

    data = resp.get_json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "1"
    assert data["items"][0]["name"] == "Sonic the Hedgehog"


def test_want_to_play_empty_list_returns_empty_items():
    client = _client()
    _connect(client, wtp_games=[])

    with patch.object(api_module.RetroAchievementsClient, "get_want_to_play_list", return_value=[]):
        resp = client.get("/api/want_to_play")

    assert resp.get_json() == {"success": True, "items": [], "total": 0, "requested": 0}


# --- /api/ra/status y /api/ra/disconnect ------------------------------------


def test_status_reflects_connection_state():
    client = _client()
    assert client.get("/api/ra/status").get_json() == {"connected": False, "username": None}

    _connect(client, username="pipetboy")
    assert client.get("/api/ra/status").get_json() == {"connected": True, "username": "pipetboy"}


def test_disconnect_clears_session():
    client = _client()
    _connect(client, username="pipetboy")
    assert client.get("/api/ra/status").get_json()["connected"] is True

    disconnect_resp = client.post("/api/ra/disconnect")
    assert disconnect_resp.get_json() == {"success": True}

    assert client.get("/api/ra/status").get_json() == {"connected": False, "username": None}
    assert client.get("/api/want_to_play").status_code == 401


# --- /api/ra/profile ---------------------------------------------------------

_FAKE_PROFILE = {
    "User": "pipetboy",
    "UserPic": "/UserPic/pipetboy.png",
    "TotalPoints": 12345,
    "TotalTruePoints": 45678,
    "MemberSince": "2020-01-02 00:00:00",
    "Motto": "Jugando RA",
}


def test_profile_without_session_returns_401():
    resp = _client().get("/api/ra/profile")
    assert resp.status_code == 401
    assert resp.get_json()["success"] is False


def test_profile_uses_session_and_builds_full_avatar_url():
    client = _client()
    _connect(client)

    with patch.object(api_module.RetroAchievementsClient, "get_user_profile", return_value=_FAKE_PROFILE):
        resp = client.get("/api/ra/profile")

    assert resp.status_code == 200
    assert resp.get_json() == {
        "success": True,
        "avatar_url": "https://media.retroachievements.org/UserPic/pipetboy.png",
        "total_points": 12345,
        "total_true_points": 45678,
        "motto": "Jugando RA",
    }


def test_profile_without_avatar_returns_null_url():
    client = _client()
    _connect(client)
    profile_without_pic = {**_FAKE_PROFILE, "UserPic": ""}

    with patch.object(api_module.RetroAchievementsClient, "get_user_profile", return_value=profile_without_pic):
        resp = client.get("/api/ra/profile")

    assert resp.get_json()["avatar_url"] is None


def test_profile_ra_api_error_returns_502():
    client = _client()
    _connect(client)

    with patch.object(
        api_module.RetroAchievementsClient,
        "get_user_profile",
        side_effect=api_module.RetroAchievementsAPIError("boom"),
    ):
        resp = client.get("/api/ra/profile")

    assert resp.status_code == 502
    assert "boom" not in resp.get_data(as_text=True)
