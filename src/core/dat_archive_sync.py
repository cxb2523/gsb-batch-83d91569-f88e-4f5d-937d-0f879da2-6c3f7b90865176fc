"""
Da de alta hashes de RetroAchievements en
Data/TamperMonkeyRetroachievements.json cruzando un .dat de UGA_RA_DATs
(https://github.com/UltraGodAzgorath/UGA_RA_DATs) contra el listado de
archivos de un item de archive.org, para consolas donde verificar hasheando
(como hace SourceResync) implicaria descargar varios GB por candidato.

No hace falta bajar ningun juego: el .dat trae el MD5 del archivo junto al
<ra_hash>, y archive.org expone el MD5 de cada archivo en su propia
metadata. Cruzando por MD5 (no por nombre, que puede diferir entre el dat
y el archivo real -- confirmado con GameCube: ~20% de los matches reales
tenian nombre distinto) se obtiene el hash de RA con la misma certeza que
si lo hubieramos hasheado nosotros.
"""

import json
import os
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Tuple

import requests

import config

REQUEST_TIMEOUT = 30


def _parse_dat(xml_bytes: bytes, extensions: Iterable[str]) -> Dict[str, Tuple[str, str, str]]:
    """{md5_rom_lower: (ra_hash_upper, rom_filename, game_name)}.

    Dentro de un <game> cada <rom> con extension valida seguido
    inmediatamente de un <ra_hash> (multi-disco: cada disco tiene su
    propio hash) se toma; el resto (ej. .m3u) se ignora."""
    exts = tuple(e.lower() for e in extensions)
    root = ET.fromstring(xml_bytes)
    roms: Dict[str, Tuple[str, str, str]] = {}
    for game in root.findall("game"):
        children = list(game)
        for i, el in enumerate(children):
            if el.tag != "rom" or not el.get("name", "").lower().endswith(exts):
                continue
            if i + 1 >= len(children) or children[i + 1].tag != "ra_hash":
                continue
            md5 = el.get("md5", "").lower()
            roms[md5] = (children[i + 1].text.strip().upper(), el.get("name", ""), game.get("name", ""))
    return roms


def _match(
    dat_roms: Dict[str, Tuple[str, str, str]],
    archive_files: List[Tuple[str, str]],
    existing_hashes: set,
    console_folder: str,
) -> Tuple[Dict[str, Dict[str, str]], set]:
    """-> ({game_name: {ra_hash: rom_path}}, {md5 matcheados contra el dat})."""
    matched_by_game: Dict[str, Dict[str, str]] = {}
    matched_md5s = set()
    for filename, md5 in archive_files:
        dat_entry = dat_roms.get(md5)
        if not dat_entry:
            continue
        ra_hash, _dat_filename, game_name = dat_entry
        matched_md5s.add(md5)
        if ra_hash in existing_hashes:
            continue  # ya cargado -- re-run idempotente
        matched_by_game.setdefault(game_name, {})[ra_hash] = f"{console_folder}/{filename}"
    return matched_by_game, matched_md5s


class DatArchiveSync:
    """Orquesta el alta de una consola en Data/TamperMonkeyRetroachievements.json
    a partir de un .dat de UGA_RA_DATs y un item de archive.org."""

    def __init__(
        self, dat_url: str, archive_item: str, console_folder: str, extensions: Iterable[str], missing_file: str
    ):
        self.dat_url = dat_url
        self.archive_item = archive_item
        self.console_folder = console_folder
        self.extensions = tuple(e.lower() for e in extensions)
        self.missing_file = missing_file

    def _fetch_dat_roms(self) -> Dict[str, Tuple[str, str, str]]:
        resp = requests.get(self.dat_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return _parse_dat(resp.content, self.extensions)

    def _fetch_archive_files(self) -> List[Tuple[str, str]]:
        resp = requests.get(f"https://archive.org/metadata/{self.archive_item}", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        files = resp.json().get("files", [])
        return [
            (f["name"], (f.get("md5") or "").lower())
            for f in files
            if f.get("name", "").lower().endswith(self.extensions)
        ]

    def run(self):
        dat_roms = self._fetch_dat_roms()
        archive_files = self._fetch_archive_files()

        with open(config.JSON_FILE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        existing_hashes = {h for entries in data.values() for item in entries for h in item}
        next_id = max((int(k) for k in data.keys()), default=0)

        matched_by_game, matched_md5s = _match(dat_roms, archive_files, existing_hashes, self.console_folder)

        added_hashes = 0
        for game_name, hash_map in matched_by_game.items():
            next_id += 1
            data[str(next_id)] = [hash_map]
            added_hashes += len(hash_map)

        with open(config.JSON_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

        missing = sorted(
            {
                (game_name, filename, ra_hash)
                for md5, (ra_hash, filename, game_name) in dat_roms.items()
                if md5 not in matched_md5s
            },
            key=lambda x: x[0].lower(),
        )
        os.makedirs("Data", exist_ok=True)
        with open(self.missing_file, "w", encoding="utf-8") as f:
            for game_name, filename, ra_hash in missing:
                f.write(f"{game_name}\t{filename}\t{ra_hash}\n")

        unmatched_archive = len(archive_files) - len(matched_md5s)
        print(f"Agregados: {len(matched_by_game)} juegos, {added_hashes} hashes nuevos.")
        print(
            f"No encontrados en {self.archive_item} (RA los reconoce, falta el archivo): "
            f"{len(missing)} -> {self.missing_file}"
        )
        print(
            "Archivos del item sin match en el .dat (hacks/subsets no reconocidos por RA, se ignoran): "
            f"{unmatched_archive}"
        )


if __name__ == "__main__":
    sample_dat = _parse_dat(
        b'<datafile><game name="X"><rom name="X.rvz" md5="AA"/><ra_hash>bb</ra_hash></game>'
        b'<game name="Y"><rom name="Y.m3u" md5="cc"/><rom name="Y.rvz" md5="dd"/><ra_hash>ee</ra_hash></game>'
        b'<game name="Z"><rom name="Z.wad" md5="ff"/><ra_hash>11</ra_hash></game></datafile>',
        extensions=(".rvz", ".wad"),
    )
    assert sample_dat == {"aa": ("BB", "X.rvz", "X"), "dd": ("EE", "Y.rvz", "Y"), "ff": ("11", "Z.wad", "Z")}

    matched, matched_md5s = _match(
        sample_dat,
        archive_files=[("X.rvz", "aa"), ("Y.rvz", "dd"), ("W.rvz", "ff2")],
        existing_hashes=set(),
        console_folder="Test",
    )
    assert matched == {"X": {"BB": "Test/X.rvz"}, "Y": {"EE": "Test/Y.rvz"}}
    assert matched_md5s == {"aa", "dd"}

    matched_again, _ = _match(sample_dat, [("X.rvz", "aa")], existing_hashes={"BB"}, console_folder="Test")
    assert matched_again == {}

    print("dat_archive_sync smoke check: OK")
