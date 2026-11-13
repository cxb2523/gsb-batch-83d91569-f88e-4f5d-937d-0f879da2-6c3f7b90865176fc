"""
Tests sobre los atajos 'cambiar'/'salir' de UIHelper (src/utils/helpers.py):
letras en get_hash_input (texto libre), números en select_from_list (listas).
"""

from unittest.mock import patch

from src.utils.helpers import UIHelper


def _ask(value):
    return patch("src.utils.helpers.Prompt.ask", return_value=value)


def test_get_hash_input_m_switches_mode():
    with _ask("M"):
        assert UIHelper().get_hash_input() == "cambiar"


def test_get_hash_input_s_exits():
    with _ask("s"):
        assert UIHelper().get_hash_input() == "salir"


def test_get_hash_input_returns_raw_value_otherwise():
    with _ask("AABBCCDD11223344"):
        assert UIHelper().get_hash_input() == "AABBCCDD11223344"


def test_select_from_list_empty_items_returns_none():
    assert UIHelper().select_from_list([], "titulo") is None


def test_select_from_list_picks_item_by_number():
    with _ask("2"):
        assert UIHelper().select_from_list(["Uno", "Dos"], "titulo") == "Dos"


def test_select_from_list_last_two_numbers_are_cambiar_and_salir():
    items = ["Uno", "Dos"]  # 1, 2 = items; 3 = cambiar; 4 = salir

    with _ask("3"):
        assert UIHelper().select_from_list(items, "titulo") == "cambiar"

    with _ask("4"):
        assert UIHelper().select_from_list(items, "titulo") == "salir"


def test_select_from_list_allow_all_shifts_the_shortcut_numbers():
    items = ["Uno"]  # con allow_all: 1 = Uno, 2 = Todos, 3 = cambiar, 4 = salir

    with _ask("2"):
        assert UIHelper().select_from_list(items, "titulo", allow_all=True) == "todos"

    with _ask("4"):
        assert UIHelper().select_from_list(items, "titulo", allow_all=True) == "salir"


def test_select_from_list_invalid_number_falls_back_to_first_item():
    with _ask("99"):
        assert UIHelper().select_from_list(["Uno", "Dos"], "titulo") == "Uno"


def test_select_from_list_non_numeric_falls_back_to_first_item():
    with _ask("no-es-un-numero"):
        assert UIHelper().select_from_list(["Uno", "Dos"], "titulo") == "Uno"
