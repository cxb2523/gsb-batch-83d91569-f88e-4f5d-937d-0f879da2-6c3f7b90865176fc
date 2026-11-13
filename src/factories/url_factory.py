"""
Factory para crear generadores de URL según la consola/plataforma.
"""

import json
from typing import Dict
from urllib.parse import quote

from ..core.interfaces import URLGenerator

_source_override_cache: Dict[str, dict] = {}


def _load_source_override(path: str) -> dict:
    """Carga (y cachea en memoria) un Data/<consola>_source_override.json
    generado por scripts/sync_source.py -- mapea rom_path -> nombre de archivo en
    la colección de reemplazo. Si no existe todavía, devuelve {} (la
    consola sigue usando su BASE_URL de siempre, sin romper nada)."""
    if path not in _source_override_cache:
        try:
            with open(path, encoding="utf-8") as f:
                _source_override_cache[path] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _source_override_cache[path] = {}
    return _source_override_cache[path]


def _normalize_slashes(path: str) -> str:
    """Normaliza separadores a '/' y quita un '/' inicial si existe."""
    return path.replace("\\", "/").lstrip("/")


def _encode_rel_path(path: str) -> str:
    """Codifica el path relativo preservando '/'.

    - Espacios, paréntesis y otros caracteres especiales se codifican.
    - No codifica '/', '-', '_', '.' para URLs más limpias.
    """
    return quote(path, safe="/-_.")


def _strip_first_segment_if_matches(path: str, segment: str) -> str:
    """Si el path comienza con 'segment/', elimina ese primer segmento.

    Útil para evitar duplicar carpetas de consola cuando la BASE_URL ya
    incluye dicha carpeta (ej. 'PlayStation 2/').
    """
    norm = _normalize_slashes(path)
    seg_lower = segment.lower()
    if norm.lower().startswith(seg_lower + "/"):
        # Quitar exactamente el primer segmento (hasta el primer '/')
        return norm.split("/", 1)[1]
    return norm


class SNESURLGenerator(URLGenerator):
    """Generador de URLs para SNES/Super Famicom.

    La colección vieja de archive.org (BASE_URL) murió. Hay una de
    reemplazo, pero con nombres/estructura distintos -- scripts/sync_source.py
    genera Data/snes_source_override.json (rom_path -> nombre de archivo
    en la colección nueva) matcheando por hash real, no por nombre. Lo que
    todavía no tiene match sigue cayendo en el BASE_URL viejo (roto, pero
    es justo lo que queda listado en Data/snes_missing_sources.txt)."""

    BASE_URL = "https://archive.org/download/retroachievements_collection_SNES-Super_Famicom/"
    BASE_URL_REPLACEMENT = "https://archive.org/download/retroachievementscompatibleromsSNES/"
    OVERRIDE_FILE = "Data/snes_source_override.json"

    def generate_url(self, rom_path: str) -> str:
        rel = _normalize_slashes(rom_path)
        override = _load_source_override(self.OVERRIDE_FILE)
        filename = override.get(rel)
        if filename:
            return self.BASE_URL_REPLACEMENT + _encode_rel_path(filename)
        return self.BASE_URL + _encode_rel_path(rel)

    def can_handle(self, rom_path: str) -> bool:
        return "SNES-Super Famicom" in rom_path


class NESURLGenerator(URLGenerator):
    """Generador de URLs para NES/Famicom."""

    BASE_URL = "https://archive.org/download/retroachievements_collection_NES-Famicom/"

    def generate_url(self, rom_path: str) -> str:
        rel = _normalize_slashes(rom_path)
        return self.BASE_URL + _encode_rel_path(rel)

    def can_handle(self, rom_path: str) -> bool:
        return "NES-Famicom" in rom_path


class PSPURLGenerator(URLGenerator):
    """Generador de URLs para PlayStation Portable."""

    BASE_URL = "https://dn720005.ca.archive.org/0/items/retroachievements_collection_PlayStation_Portable/PlayStation%20Portable/"

    def generate_url(self, rom_path: str) -> str:
        # La BASE_URL ya incluye 'PlayStation%20Portable/'
        rel = _strip_first_segment_if_matches(rom_path, "PlayStation Portable")
        return self.BASE_URL + _encode_rel_path(rel)

    def can_handle(self, rom_path: str) -> bool:
        return "PlayStation Portable" in rom_path


class PS1URLGenerator(URLGenerator):
    """Generador de URLs para PlayStation 1."""

    BASE_URL = "https://archive.org/download/retroachievements_collection_PlayStation/PlayStation/"

    def generate_url(self, rom_path: str) -> str:
        # La BASE_URL ya incluye 'PlayStation/'
        rel = _strip_first_segment_if_matches(rom_path, "PlayStation")
        return self.BASE_URL + _encode_rel_path(rel)

    def can_handle(self, rom_path: str) -> bool:
        return "PlayStation" in rom_path and "PlayStation 2" not in rom_path and "PlayStation Portable" not in rom_path


class PS2URLGenerator(URLGenerator):
    """Generador de URLs para PlayStation 2."""

    BASE_URL_A_M = "https://archive.org/download/retroachievements_collection_PlayStation_2_A-M/PlayStation%202/"
    BASE_URL_N_Z = "https://archive.org/download/retroachievements_collection_PlayStation_2_N-Z/PlayStation%202/"

    def generate_url(self, rom_path: str) -> str:
        # Quitar prefijo 'PlayStation 2/' si está presente para evitar duplicados
        rel = _strip_first_segment_if_matches(rom_path, "PlayStation 2")
        # Decidir entre A-M o N-Z basado en el nombre del archivo (primer caracter)
        game_name = rel.split("/")[-1] if "/" in rel else rel
        base = self.BASE_URL_A_M if (game_name and game_name[0].upper() < "N") else self.BASE_URL_N_Z
        return base + _encode_rel_path(rel)

    def can_handle(self, rom_path: str) -> bool:
        return "PlayStation 2" in rom_path


class SegaURLGenerator(URLGenerator):
    """Generador de URLs para consolas Sega (Genesis, Mega Drive, Sega CD)."""

    BASE_URL = "https://archive.org/download/retroachievements_collection_v5/"

    def generate_url(self, rom_path: str) -> str:
        rel = _normalize_slashes(rom_path)
        return self.BASE_URL + _encode_rel_path(rel)

    def can_handle(self, rom_path: str) -> bool:
        return any(console in rom_path for console in ["Genesis-Mega Drive", "Sega CD"])


class ArcadeURLGenerator(URLGenerator):
    """Generador de URLs para Arcade.

    Bug encontrado (no es un problema de fuente muerta, como SNES): los
    rom_path reales usan "arcade\\" en minúscula (ej. "arcade\\sailormn.zip"),
    pero can_handle() comparaba contra "Arcade" con mayúscula -- ningún
    juego de Arcade pasaba nunca por este generador, caían todos en el
    DefaultURLGenerator (BASE_URL de v5, rotos). Y aunque entraran, BASE_URL
    ya termina en ".../arcade/" y el rom_path también empieza con
    "arcade/", así que sin strip quedaba duplicado
    (".../arcade/arcade/...", también roto). Confirmado con la colección
    real: https://archive.org/download/fbnarcade-fullnonmerged/arcade/<archivo>
    sí funciona."""

    BASE_URL = "https://archive.org/download/fbnarcade-fullnonmerged/arcade/"

    def generate_url(self, rom_path: str) -> str:
        rel = _strip_first_segment_if_matches(rom_path, "arcade")
        return self.BASE_URL + _encode_rel_path(rel)

    def can_handle(self, rom_path: str) -> bool:
        first_segment = _normalize_slashes(rom_path).split("/", 1)[0]
        return first_segment.lower() == "arcade"


class WiiURLGenerator(URLGenerator):
    """Generador de URLs para WiiWare. Fuente: item de archive.org
    'RetroAchievementsWii' (archivos sueltos en la raiz del item, sin
    subcarpetas). Root propio ("WiiWare", no "Wii") para diferenciarlo de
    los juegos de disco (.rvz/.iso), que ahora cubre WiiDiscURLGenerator
    (mismo item, root "Wii") -- scripts/sync_wii.py matchea ambos por MD5 contra
    el .dat de RetroAchievements (UGA_RA_DATs), sin descargar ningun
    juego (mismo mecanismo que GameCube, ver dat_archive_sync.py)."""

    BASE_URL = "https://archive.org/download/RetroAchievementsWii/"

    def generate_url(self, rom_path: str) -> str:
        filename = _normalize_slashes(rom_path).split("/")[-1]
        return self.BASE_URL + _encode_rel_path(filename)

    def can_handle(self, rom_path: str) -> bool:
        return _normalize_slashes(rom_path).split("/", 1)[0] == "WiiWare"


class WiiDiscURLGenerator(URLGenerator):
    """Generador de URLs para discos de Wii (.rvz/.iso). Mismo item de
    archive.org que WiiURLGenerator (WiiWare), pero con su propio root
    ("Wii") para que la taxonomia local los liste como consolas
    separadas."""

    BASE_URL = "https://archive.org/download/RetroAchievementsWii/"

    def generate_url(self, rom_path: str) -> str:
        filename = _normalize_slashes(rom_path).split("/")[-1]
        return self.BASE_URL + _encode_rel_path(filename)

    def can_handle(self, rom_path: str) -> bool:
        return _normalize_slashes(rom_path).split("/", 1)[0] == "Wii"


class GameCubeURLGenerator(URLGenerator):
    """Generador de URLs para GameCube. Fuente: item de archive.org
    'RetroAchievementsGameCube' (archivos .rvz sueltos en la raiz del
    item, sin subcarpetas). A diferencia de Wii, estos SI estan
    verificados sin descargar: scripts/sync_gamecube.py matchea por MD5 del .rvz
    contra el .dat de RetroAchievements (UGA_RA_DATs), que trae md5 y
    ra_hash juntos por archivo."""

    BASE_URL = "https://archive.org/download/RetroAchievementsGameCube/"

    def generate_url(self, rom_path: str) -> str:
        filename = _normalize_slashes(rom_path).split("/")[-1]
        return self.BASE_URL + _encode_rel_path(filename)

    def can_handle(self, rom_path: str) -> bool:
        return _normalize_slashes(rom_path).split("/", 1)[0] == "GameCube"


class DSiOctober2025URLGenerator(URLGenerator):
    """5 juegos de Nintendo DSi que la coleccion v5 no tiene (RA no los
    reconocia todavia cuando se armo v5). Fuente: item de archive.org
    'retro-achievements-nintendo-dsi-october-25-2025', un unico .zip con un
    .zip por juego adentro. Hashes verificados con RAHasher contra
    GetGameList(78) antes de agregarlos -- el resto de Nintendo DSi sigue
    cayendo en DefaultURLGenerator, sin tocar.

    archive.org expone cada archivo interno via /download/<item>/<outer>.zip/
    <outer sin extension>%2F<interno>.zip (confirmado: responde 302 al
    contenido real del zip interno, no al listado HTML)."""

    ITEM = "retro-achievements-nintendo-dsi-october-25-2025"
    OUTER_ZIP = "RetroAchievements Nintendo dsi (October 25 2025).zip"
    BASE_URL = f"https://archive.org/download/{ITEM}/{quote(OUTER_ZIP, safe='')}/"

    INNER_FILES = {
        "Nintendo DSi/99 Moves/99 Moves (Europe) (En,Fr,De,Es,It).zip": "99 Moves (Europe) (En,Fr,De,Es,It).zip",
        "Nintendo DSi/1001 Blockbusters/1001 Blockbusters (Europe).zip": "1001 Blockbusters (Europe).zip",
        (
            "Nintendo DSi/Airport Mania - First Flight/"
            "Airport Mania - First Flight (Europe, Australia) (En,Fr,De,Es,It,Nl).zip"
        ): "Airport Mania - First Flight (Europe, Australia) (En,Fr,De,Es,It,Nl).zip",
        "Nintendo DSi/Kappa's Trail, A/Kappa's Trail, A (USA).zip": "Kappa's Trail, A (USA).zip",
        "Nintendo DSi/Mario Calculator/Mario Calculator (USA) (En,Fr,Es).zip": "Mario Calculator (USA) (En,Fr,Es).zip",
    }

    def generate_url(self, rom_path: str) -> str:
        rel = _normalize_slashes(rom_path)
        inner = self.INNER_FILES[rel]
        outer_folder = self.OUTER_ZIP.rsplit(".zip", 1)[0]
        return self.BASE_URL + quote(f"{outer_folder}/{inner}", safe="")

    def can_handle(self, rom_path: str) -> bool:
        return _normalize_slashes(rom_path) in self.INNER_FILES


class DefaultURLGenerator(URLGenerator):
    """Generador de URLs por defecto."""

    BASE_URL = "https://archive.org/download/retroachievements_collection_v5/"

    def generate_url(self, rom_path: str) -> str:
        rel = _normalize_slashes(rom_path)
        return self.BASE_URL + _encode_rel_path(rel)

    def can_handle(self, rom_path: str) -> bool:
        return True  # Siempre puede manejar como fallback


class URLGeneratorFactory:
    """Factory para crear generadores de URL."""

    _generators = [
        SNESURLGenerator(),
        NESURLGenerator(),
        PSPURLGenerator(),
        PS1URLGenerator(),
        PS2URLGenerator(),
        SegaURLGenerator(),
        ArcadeURLGenerator(),
        WiiURLGenerator(),
        WiiDiscURLGenerator(),
        GameCubeURLGenerator(),
        DSiOctober2025URLGenerator(),
        DefaultURLGenerator(),  # Debe ir al final como fallback
    ]

    @classmethod
    def get_generator(cls, rom_path: str) -> URLGenerator:
        """Obtiene el generador apropiado para la ROM."""
        for generator in cls._generators:
            if generator.can_handle(rom_path):
                return generator
        return cls._generators[-1]  # Retorna el generador por defecto

    @classmethod
    def generate_url(cls, rom_path: str) -> str:
        """Genera la URL de descarga para una ROM."""
        generator = cls.get_generator(rom_path)
        return generator.generate_url(rom_path)


if __name__ == "__main__":  # pragma: no cover
    url = URLGeneratorFactory.generate_url("Nintendo DSi/Mario Calculator/Mario Calculator (USA) (En,Fr,Es).zip")
    assert url == (
        "https://archive.org/download/retro-achievements-nintendo-dsi-october-25-2025/"
        "RetroAchievements%20Nintendo%20dsi%20%28October%2025%202025%29.zip/"
        "RetroAchievements%20Nintendo%20dsi%20%28October%2025%202025%29%2F"
        "Mario%20Calculator%20%28USA%29%20%28En%2CFr%2CEs%29.zip"
    )
    # Otros rom_path de Nintendo DSi no matcheados siguen cayendo en el fallback de siempre.
    assert "retroachievements_collection_v5" in URLGeneratorFactory.generate_url(
        "Nintendo DSi/Shantae - Risky's Revenge/Shantae - Risky's Revenge (USA).zip"
    )

    assert (
        URLGeneratorFactory.generate_url("WiiWare/Cave Story/Cave Story (USA) (v258) (WiiWare).wad")
        == "https://archive.org/download/RetroAchievementsWii/Cave%20Story%20%28USA%29%20%28v258%29%20%28WiiWare%29.wad"
    )

    assert (
        URLGeneratorFactory.generate_url("Wii/Boom Blox (USA) (En,Fr,Es).rvz")
        == "https://archive.org/download/RetroAchievementsWii/Boom%20Blox%20%28USA%29%20%28En%2CFr%2CEs%29.rvz"
    )

    print("url_factory smoke check: OK")
