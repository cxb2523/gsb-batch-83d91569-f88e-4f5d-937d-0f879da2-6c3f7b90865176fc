"""
Tests sobre el cambio de modo y los atajos ('salir'/'cambiar') en src/app.py.

Agregados junto con la mejora estética del CLI -- antes de esto la app de
consola no tenía ningún test (ver pytest.ini). Usan dobles simples en vez de
instanciar las estrategias/comandos reales para no pegarle a archive.org ni
a la API de RetroAchievements, y no tocan la UI real (UIHelper se stubea).
"""

import pytest

from src.app import AppMode, RetroAchievementsDownloader
from src.core.interfaces import GameInfo


class _FakeDirectHashStrategy:
    def __init__(self, result=None):
        self.result = result
        self.queries = []

    def search(self, hash_value):
        self.queries.append(hash_value)
        return self.result


class _FakeWantToPlayStrategy:
    def __init__(self, consoles=None, games=None):
        self.consoles = consoles if consoles is not None else ["NES"]
        self.games = games if games is not None else ["Game A"]

    def get_available_consoles(self):
        return self.consoles

    def get_games_for_console(self, console):
        return self.games

    def search(self, game_name):
        return None  # fuerza el camino "no encontrado", sin red


def _app(mode, strategy):
    app = RetroAchievementsDownloader(mode)
    app.search_strategy = strategy
    return app


# --- Modo hash directo ---------------------------------------------------


def test_direct_hash_mode_returns_cambiar_on_shortcut(monkeypatch):
    app = _app(AppMode.DIRECT_HASH, _FakeDirectHashStrategy())
    monkeypatch.setattr(app.ui_helper, "get_hash_input", lambda: "cambiar")

    assert app._run_direct_hash_mode() == "cambiar"


def test_direct_hash_mode_returns_salir_on_shortcut(monkeypatch):
    app = _app(AppMode.DIRECT_HASH, _FakeDirectHashStrategy())
    monkeypatch.setattr(app.ui_helper, "get_hash_input", lambda: "salir")

    assert app._run_direct_hash_mode() == "salir"


def test_direct_hash_mode_rejects_invalid_hash_and_keeps_looping(monkeypatch):
    strategy = _FakeDirectHashStrategy()
    app = _app(AppMode.DIRECT_HASH, strategy)
    inputs = iter(["no-es-un-hash", "salir"])
    monkeypatch.setattr(app.ui_helper, "get_hash_input", lambda: next(inputs))

    assert app._run_direct_hash_mode() == "salir"
    assert strategy.queries == []  # un hash inválido nunca llega a buscarse


def test_direct_hash_mode_opens_browser_for_a_valid_hash(monkeypatch):
    game_info = GameInfo(name="Foo", console="NES", hash_value="AABBCCDD11223344", rom_path="NES-Famicom/Foo.zip")
    strategy = _FakeDirectHashStrategy(result=game_info)
    app = _app(AppMode.DIRECT_HASH, strategy)

    inputs = iter(["AABBCCDD11223344", "salir"])
    monkeypatch.setattr(app.ui_helper, "get_hash_input", lambda: next(inputs))

    opened = []

    class _FakeCommand:
        def __init__(self, info):
            opened.append(info)

        def execute(self):
            return True

    monkeypatch.setattr("src.app.OpenInBrowserCommand", _FakeCommand)

    assert app._run_direct_hash_mode() == "salir"
    assert opened == [game_info]
    assert strategy.queries == ["AABBCCDD11223344"]


# --- Modo lista de deseos --------------------------------------------------


def test_want_to_play_mode_exits_when_no_consoles():
    app = _app(AppMode.WANT_TO_PLAY, _FakeWantToPlayStrategy(consoles=[]))

    assert app._run_want_to_play_mode() == "salir"


def test_want_to_play_mode_switches_from_console_menu(monkeypatch):
    app = _app(AppMode.WANT_TO_PLAY, _FakeWantToPlayStrategy())
    monkeypatch.setattr(app.ui_helper, "select_from_list", lambda items, title, allow_all=False: "cambiar")

    assert app._run_want_to_play_mode() == "cambiar"


def test_want_to_play_mode_does_not_exit_after_downloading_a_game(monkeypatch):
    """Caso pedido explícitamente: tras descargar un juego, vuelve a pedir
    consola en vez de terminar la app. Si el modo no hiciera loop, la
    tercera respuesta ('salir') nunca se consumiría."""
    app = _app(AppMode.WANT_TO_PLAY, _FakeWantToPlayStrategy())

    responses = iter(["NES", "Game A", "salir"])
    monkeypatch.setattr(app.ui_helper, "select_from_list", lambda items, title, allow_all=False: next(responses))

    assert app._run_want_to_play_mode() == "salir"
    with pytest.raises(StopIteration):
        next(responses)


# --- Loop de cambio de modo en run() ---------------------------------------


def test_run_switches_mode_and_then_exits(monkeypatch):
    app = _app(AppMode.DIRECT_HASH, _FakeDirectHashStrategy())
    monkeypatch.setattr(app.ui_helper, "display_welcome_message", lambda *a, **k: None)

    calls = []

    def fake_direct():
        calls.append(("direct", app.mode))
        return "cambiar"

    def fake_want():
        calls.append(("want", app.mode))
        return "salir"

    monkeypatch.setattr(app, "_run_direct_hash_mode", fake_direct)
    monkeypatch.setattr(app, "_run_want_to_play_mode", fake_want)

    app.run()

    assert calls == [("direct", AppMode.DIRECT_HASH), ("want", AppMode.WANT_TO_PLAY)]
    assert app.mode == AppMode.WANT_TO_PLAY
