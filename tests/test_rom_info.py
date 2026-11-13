"""
Tests sobre src/core/rom_info.py, compartido entre la app de consola y
api/index.py -- incluye los alias de consola vistos en datos reales
(megadriv, npg, nes, sg1000, sms, arcade en minúscula).
"""

import pytest

from src.core.rom_info import analyze_rom_info, extract_game_name, get_console_from_rom_path


@pytest.mark.parametrize(
    "rom_path, expected_console",
    [
        ("SNES-Super Famicom/Game (U).sfc", "SNES"),
        ("PlayStation 2/A-M/Foo (U).iso", "PS2"),
        ("arcade/!_flycast/foo.zip", "ARCADE"),
        ("megadriv/Sonic (U).bin", "Genesis/Mega Drive"),
        ("npg/Some Game (J).ngp", "Neo Geo Pocket"),
        ("ngp/rockmanb.zip", "Neo Geo Pocket"),
        ("nes/finalfaniii.zip", "NES"),
        ("sg1000/moyuchua.zip", "SG-1000"),
        ("sms/asterix1.zip", "Master System"),
        ("GameCube/Game (U).rvz", "GameCube"),
        ("WiiWare/Game (USA) (WiiWare).wad", "WiiWare"),
        ("Wii/Game (USA).rvz", "Wii"),
    ],
)
def test_get_console_from_rom_path(rom_path, expected_console):
    assert get_console_from_rom_path(rom_path) == expected_console


def test_get_console_from_rom_path_unknown_falls_back_to_pretty_root():
    assert get_console_from_rom_path("Some Weird Console/Game.zip") == "Some Weird Console"


@pytest.mark.parametrize(
    "rom_path, expected_name",
    [
        # Sin subcarpeta por juego: cae al nombre de archivo limpio.
        ("SNES-Super Famicom/Super Mario World (U).sfc", "Super Mario World (U)"),
        # Con subcarpeta por juego (el caso común en Data/): usa esa carpeta.
        ("SNES-Super Famicom/Super Mario World/Super Mario World (U) [!] [T+Spa_Wave].zip", "Super Mario World"),
        ("arcade/!_flycast/sfiii3_usa.zip", "sfiii3 usa"),
        ("arcade/arcade/pacman.zip", "pacman"),
    ],
)
def test_extract_game_name(rom_path, expected_name):
    assert extract_game_name(rom_path) == expected_name


def test_analyze_rom_info_hack():
    info = analyze_rom_info("PlayStation/Foo [Hack].bin")
    assert info["is_hack"] is True
    assert info["priority"] == 3


def test_analyze_rom_info_original_usa():
    info = analyze_rom_info("NES-Famicom/Foo (U) [!].zip")
    assert info["region"] == "USA"
    assert info["is_original"] is True
    assert info["priority"] == 1


@pytest.mark.parametrize(
    "rom_path, expected_region",
    [
        ("NES-Famicom/Foo (E).zip", "Europe"),
        ("NES-Famicom/Foo (J).zip", "Japan"),
        ("NES-Famicom/Foo (UE).zip", "USA/Europe"),
        ("NES-Famicom/Foo.zip", "Unknown"),
    ],
)
def test_analyze_rom_info_region(rom_path, expected_region):
    assert analyze_rom_info(rom_path)["region"] == expected_region


def test_analyze_rom_info_official_translation_is_priority_2():
    # Caso real del dataset: original + traducción oficial.
    info = analyze_rom_info("SNES-Super Famicom/Super Mario World/Super Mario World (U) [!] [T+Spa_Wave].zip")
    assert info["is_original"] is True
    assert info["is_translation"] is True
    assert info["priority"] == 2


def test_analyze_rom_info_plain_rom_is_priority_4():
    info = analyze_rom_info("NES-Famicom/Foo (U).zip")
    assert info["is_hack"] is False
    assert info["is_original"] is False
    assert info["priority"] == 4


def test_extract_game_name_empty_path():
    assert extract_game_name("") == ""
