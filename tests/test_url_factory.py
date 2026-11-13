"""
Tests sobre src/factories/url_factory.py usando rom_path reales de
Data/TamperMonkeyRetroachievements.json (uno por consola relevante), para
anclar el comportamiento documentado (strip de segmento, split A-M/N-Z de
PS2, case-insensitivity de Arcade, fallback a DefaultURLGenerator) y
detectar deriva con api/index.py.
"""

import json
from urllib.parse import quote

import pytest

from src.factories.url_factory import (
    ArcadeURLGenerator,
    DefaultURLGenerator,
    DSiOctober2025URLGenerator,
    GameCubeURLGenerator,
    NESURLGenerator,
    PS1URLGenerator,
    PS2URLGenerator,
    PSPURLGenerator,
    SegaURLGenerator,
    SNESURLGenerator,
    URLGeneratorFactory,
    WiiDiscURLGenerator,
    WiiURLGenerator,
)


def test_snes_without_override_falls_back_to_dead_source():
    rom_path = "SNES-Super Famicom/Nonexistent Test Game/Nonexistent Test Game (U).sfc"
    url = SNESURLGenerator().generate_url(rom_path)
    assert url == SNESURLGenerator.BASE_URL + quote(rom_path, safe="/-_.")


def test_snes_with_override_uses_replacement_source():
    with open(SNESURLGenerator.OVERRIDE_FILE, encoding="utf-8") as f:
        override = json.load(f)
    rom_path, filename = next(iter(override.items()))

    url = URLGeneratorFactory.generate_url(rom_path)

    assert url == SNESURLGenerator.BASE_URL_REPLACEMENT + quote(filename, safe="/-_.")


def test_nes():
    rom_path = "NES-Famicom/Super Mario Bros/Super Mario Bros. - 25th Anniversary (J-VC).zip"
    assert NESURLGenerator().can_handle(rom_path)
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url == NESURLGenerator.BASE_URL + quote(rom_path, safe="/-_.")


def test_psp_strips_first_segment():
    rel = "Gottlieb Pinball Classics/Gottlieb Pinball Classics (Europe) (En,Fr,De,Es,It) (v1.03).zip"
    rom_path = f"PlayStation Portable/{rel}"
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url == PSPURLGenerator.BASE_URL + quote(rel, safe="/-_.")


def test_ps1_strips_first_segment():
    rom_path = "PlayStation/Incredible Crisis/Incredible Crisis (USA).zip"
    rel = "Incredible Crisis/Incredible Crisis (USA).zip"
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url == PS1URLGenerator.BASE_URL + quote(rel, safe="/-_.")


def test_ps1_does_not_claim_ps2_or_psp_paths():
    gen = PS1URLGenerator()
    assert not gen.can_handle("PlayStation 2/Fatal Frame/Fatal Frame (USA).zip")
    assert not gen.can_handle("PlayStation Portable/Foo/Foo.zip")


@pytest.mark.parametrize(
    "rom_path, expected_base",
    [
        ("PlayStation 2/Fatal Frame ! Project Zero/Fatal Frame (USA).zip", PS2URLGenerator.BASE_URL_A_M),
        (
            "PlayStation 2/Fatal Frame ! Project Zero/Project Zero (E)(Undub)(Fixes)[Widescreen].zip",
            PS2URLGenerator.BASE_URL_N_Z,
        ),
    ],
)
def test_ps2_splits_a_m_vs_n_z_by_filename(rom_path, expected_base):
    rel = rom_path.split("/", 1)[1]
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url == expected_base + quote(rel, safe="/-_.")


def test_sega_genesis_mega_drive():
    rom_path = "Genesis-Mega Drive/Sonic the Hedgehog/Sonic The Hedgehog (W) (REV00) [T+Rus_NewGame].zip"
    assert SegaURLGenerator().can_handle(rom_path)
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url == SegaURLGenerator.BASE_URL + quote(rom_path, safe="/-_.")


def test_sega_cd():
    rom_path = "Sega CD/~Homebrew~ Mighty Mighty Missile!/Mighty Mighty Missile (USA) (Unl).zip"
    assert SegaURLGenerator().can_handle(rom_path)


def test_arcade_is_case_insensitive_and_strips_folder():
    rom_path = "arcade\\sailormn.zip"
    assert ArcadeURLGenerator().can_handle(rom_path)
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url == ArcadeURLGenerator.BASE_URL + "sailormn.zip"


def test_wii_disc_uses_filename_only():
    rom_path = "Wii/Animal Crossing - City Folk (USA) (En,Fr,Es).rvz"
    assert WiiDiscURLGenerator().can_handle(rom_path)
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url == WiiDiscURLGenerator.BASE_URL + quote("Animal Crossing - City Folk (USA) (En,Fr,Es).rvz", safe="/-_.")


def test_wiiware_uses_filename_only():
    rom_path = "WiiWare/Adventure Island - The Beginning/Adventure Island - The Beginning (USA) (WiiWare).wad"
    assert WiiURLGenerator().can_handle(rom_path)
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url == WiiURLGenerator.BASE_URL + quote("Adventure Island - The Beginning (USA) (WiiWare).wad", safe="/-_.")


def test_gamecube_uses_filename_only():
    rom_path = "GameCube/1080 Avalanche (USA).rvz"
    assert GameCubeURLGenerator().can_handle(rom_path)
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url == GameCubeURLGenerator.BASE_URL + quote("1080 Avalanche (USA).rvz", safe="/-_.")


def test_dsi_october_2025_known_inner_file():
    rom_path = "Nintendo DSi/Mario Calculator/Mario Calculator (USA) (En,Fr,Es).zip"
    assert DSiOctober2025URLGenerator().can_handle(rom_path)
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url == (
        "https://archive.org/download/retro-achievements-nintendo-dsi-october-25-2025/"
        "RetroAchievements%20Nintendo%20dsi%20%28October%2025%202025%29.zip/"
        "RetroAchievements%20Nintendo%20dsi%20%28October%2025%202025%29%2F"
        "Mario%20Calculator%20%28USA%29%20%28En%2CFr%2CEs%29.zip"
    )


def test_unmatched_dsi_falls_back_to_default():
    rom_path = "Nintendo DSi/Shantae - Risky's Revenge/Shantae - Risky's Revenge (USA).zip"
    assert not DSiOctober2025URLGenerator().can_handle(rom_path)
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url.startswith(DefaultURLGenerator.BASE_URL)


def test_unknown_console_falls_back_to_default():
    rom_path = "Dreamcast/Tech Romancer/Tech Romancer (USA).zip"
    url = URLGeneratorFactory.generate_url(rom_path)
    assert url == DefaultURLGenerator.BASE_URL + quote(rom_path, safe="/-_.")


ROM_PATHS_FOR_PARITY_CHECK = [
    "SNES-Super Famicom/Super Mario World/Super Mario World (U) [!] [T+Spa_Wave].zip",
    "NES-Famicom/Super Mario Bros/Super Mario Bros. - 25th Anniversary (J-VC).zip",
    "PlayStation Portable/Gottlieb Pinball Classics/Gottlieb Pinball Classics (Europe) (En,Fr,De,Es,It) (v1.03).zip",
    "PlayStation/Incredible Crisis/Incredible Crisis (USA).zip",
    "PlayStation 2/Fatal Frame ! Project Zero/Fatal Frame (USA).zip",
    "PlayStation 2/Fatal Frame ! Project Zero/Project Zero (E)(Undub)(Fixes)[Widescreen].zip",
    "Genesis-Mega Drive/Sonic the Hedgehog/Sonic The Hedgehog (W) (REV00) [T+Rus_NewGame].zip",
    "arcade\\sailormn.zip",
    "Wii/Animal Crossing - City Folk (USA) (En,Fr,Es).rvz",
    "WiiWare/Adventure Island - The Beginning/Adventure Island - The Beginning (USA) (WiiWare).wad",
    "GameCube/1080 Avalanche (USA).rvz",
    "Nintendo DSi/Mario Calculator/Mario Calculator (USA) (En,Fr,Es).zip",
    "Dreamcast/Tech Romancer/Tech Romancer (USA).zip",
]


@pytest.mark.parametrize("rom_path", ROM_PATHS_FOR_PARITY_CHECK)
def test_api_get_download_url_matches_url_factory(rom_path):
    """Convierte el 'consistency hazard' documentado en CLAUDE.md (api/index.py
    podría dejar de delegar en URLGeneratorFactory y volver a duplicar la
    lógica) en un test que falla si alguien edita solo un lado."""
    import api.index as api_index

    assert api_index.get_download_url(rom_path) == URLGeneratorFactory.generate_url(rom_path)
