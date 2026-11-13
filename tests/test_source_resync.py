"""
Tests de src/core/source_resync.py con un archive.org falso 100% local
(sin red): metadata y descargas se sirven desde dicts en memoria via
monkeypatch de `_get_with_retries`. Cubre la regla de header-stripping,
el cache en disco (reuso y reintento de fallos), el reporte por archivo
y el resumen de conteos.
"""

import hashlib
import io
import json
import zipfile

import requests

from src.core import source_resync
from src.core.source_resync import SourceResync, _ra_hash

ITEM = "fake-item-snes"

# ROM "A": 8192 bytes de cuerpo + 512 de header de copiadora -> el hash RA
# debe ser el MD5 del cuerpo sin header.
BODY_A = bytes(range(256)) * 32
HEADERED_A = b"H" * 512 + BODY_A
HASH_A = hashlib.md5(BODY_A).hexdigest()

# ROM "B": va dentro de un zip, junto a un archivo chico de relleno (se
# debe hashear el mas grande).
ROM_B = b"\xaa" * 4096
HASH_B = hashlib.md5(ROM_B).hexdigest()

# Hash nuestro que ningun archivo del item produce -> cae en faltantes.
HASH_UNMATCHED = "0" * 32

ROM_PATH_A = "SNES-Super Famicom/Game A (U).sfc"
ROM_PATH_B = "SNES-Super Famicom/Game B (U).sfc"
ROM_PATH_C = "SNES-Super Famicom/Game C (U).sfc"


def _make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, content: bytes = b"", json_data=None):
        self.content = content
        self._json_data = json_data

    def json(self):
        return self._json_data


class FakeArchiveOrg:
    """Reemplazo local de `_get_with_retries`: sirve la metadata del item y
    las descargas desde `files` (nombre -> bytes). Los nombres en
    `not_found` aparecen en la metadata pero fallan al descargar (404)."""

    def __init__(self, files: dict, not_found=()):
        self.files = files
        self.not_found = set(not_found)
        self.downloads = []  # nombres pedidos, para verificar cache/reintentos

    def __call__(self, url, **kwargs):
        if url == f"https://archive.org/metadata/{ITEM}":
            listing = [{"name": name, "size": str(len(content))} for name, content in self.files.items()]
            return _FakeResponse(json_data={"files": listing})
        prefix = f"https://archive.org/download/{ITEM}/"
        assert url.startswith(prefix), f"URL inesperada: {url}"
        name = requests.utils.unquote(url[len(prefix) :])
        self.downloads.append(name)
        if name in self.not_found:
            raise RuntimeError("status 404 (despues de 3 intentos)")
        return _FakeResponse(content=self.files[name])


def _our_hashes_file(tmp_path):
    path = tmp_path / "our_hashes.json"
    if not path.exists():  # un test puede pisarlo antes con hashes custom
        data = {"1": [{HASH_A: ROM_PATH_A, HASH_B: ROM_PATH_B, HASH_UNMATCHED: ROM_PATH_C}]}
        path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _item_files():
    return {
        "Game A (U).smc": HEADERED_A,
        "Game B (U).zip": _make_zip({"readme.txt": b"relleno", "Game B (U).sfc": ROM_B}),
        "broken.zip": b"esto no es un zip",
        "empty.zip": _make_zip({}),
        "gone.zip": b"contenido inalcanzable",
    }


def _make_resync(tmp_path, monkeypatch, files=None, not_found=("gone.zip",)):
    fake = FakeArchiveOrg(files if files is not None else _item_files(), not_found=not_found)
    monkeypatch.setattr(source_resync, "_get_with_retries", fake)
    resync = SourceResync(
        console="SNES",
        item=ITEM,
        data_dir=str(tmp_path / "Data"),
        json_file=_our_hashes_file(tmp_path),
    )
    return resync, fake


def _read_report(resync):
    with open(resync.report_file, encoding="utf-8") as f:
        return json.load(f)


# --- regla de hash ----------------------------------------------------------


def test_ra_hash_strips_512_byte_header():
    assert _ra_hash(HEADERED_A) == HASH_A
    assert _ra_hash(BODY_A) == HASH_A  # sin header: hash directo


def test_ra_hash_no_strip_when_size_not_512_over_multiple():
    data = b"x" * 8192
    assert _ra_hash(data) == hashlib.md5(data).hexdigest()


# --- corrida completa -------------------------------------------------------


def test_run_reports_per_file_conclusions_and_summary(tmp_path, monkeypatch):
    resync, _ = _make_resync(tmp_path, monkeypatch)
    resync.run()

    report = _read_report(resync)
    files = report["files"]

    # Cada candidato tiene una conclusion verificable.
    assert files["Game A (U).smc"] == {"status": "computed", "hash": HASH_A, "reason": ""}
    assert files["Game B (U).zip"] == {"status": "computed", "hash": HASH_B, "reason": ""}
    assert files["broken.zip"]["status"] == "failed"
    assert "zip corrupto" in files["broken.zip"]["reason"]
    assert files["empty.zip"]["status"] == "failed"
    assert "zip vacio" in files["empty.zip"]["reason"]
    assert files["gone.zip"]["status"] == "failed"
    assert "status 404" in files["gone.zip"]["reason"]

    # Resumen de conteos.
    assert report["summary"] == {
        "computed": 2,
        "cached": 0,
        "failed": 3,
        "matched": 2,
        "missing": 1,
        "total": 3,
    }

    # Override: solo los hashes que matchean contra nuestra base.
    with open(resync.override_file, encoding="utf-8") as f:
        override = json.load(f)
    assert override == {ROM_PATH_A: "Game A (U).smc", ROM_PATH_B: "Game B (U).zip"}

    # Faltantes: el hash que no produjo ningun archivo.
    with open(resync.missing_file, encoding="utf-8") as f:
        missing = f.read()
    assert ROM_PATH_C in missing and HASH_UNMATCHED in missing
    assert ROM_PATH_A not in missing and ROM_PATH_B not in missing


def test_second_run_reuses_cache_and_produces_identical_override(tmp_path, monkeypatch):
    resync, _ = _make_resync(tmp_path, monkeypatch)
    resync.run()
    with open(resync.override_file, "rb") as f:
        first_override = f.read()

    # Segunda corrida contra el mismo cache (backend nuevo para contar requests).
    resync2, fake2 = _make_resync(tmp_path, monkeypatch)
    resync2.run()

    # Los que ya estaban OK no se vuelven a descargar; los fallidos se reintentan.
    assert sorted(fake2.downloads) == ["broken.zip", "empty.zip", "gone.zip"]

    report = _read_report(resync2)
    assert report["files"]["Game A (U).smc"]["status"] == "cached"
    assert report["files"]["Game B (U).zip"]["status"] == "cached"
    assert report["files"]["broken.zip"]["status"] == "failed"
    assert report["summary"]["cached"] == 2
    assert report["summary"]["computed"] == 0
    assert report["summary"]["failed"] == 3

    # Misma cache -> mismo override, byte a byte.
    with open(resync2.override_file, "rb") as f:
        assert f.read() == first_override


def test_failed_cache_entries_are_retried_not_skipped(tmp_path, monkeypatch):
    resync, _ = _make_resync(tmp_path, monkeypatch)
    resync.run()  # siembra el cache, incluidos los 3 fallos

    # El zip roto "se arreglo" en la fuente: ahora sirve la ROM C.
    files = _item_files()
    files["broken.zip"] = _make_zip({"Game C (U).sfc": b"\xbb" * 2048})
    hash_c_fixed = hashlib.md5(b"\xbb" * 2048).hexdigest()
    our_hashes = {"1": [{HASH_A: ROM_PATH_A, HASH_B: ROM_PATH_B, hash_c_fixed: ROM_PATH_C}]}
    (tmp_path / "our_hashes.json").write_text(json.dumps(our_hashes), encoding="utf-8")

    resync2, fake2 = _make_resync(tmp_path, monkeypatch, files=files)
    resync2.run()

    assert "broken.zip" in fake2.downloads  # se reintento, no se salteo
    report = _read_report(resync2)
    assert report["files"]["broken.zip"]["status"] == "computed"
    assert report["files"]["broken.zip"]["hash"] == hash_c_fixed
    with open(resync2.override_file, encoding="utf-8") as f:
        override = json.load(f)
    assert override[ROM_PATH_C] == "broken.zip"


def test_legacy_string_cache_is_understood(tmp_path, monkeypatch):
    # Cache del formato viejo: filename -> hash ("" = fallo).
    data_dir = tmp_path / "Data"
    data_dir.mkdir()
    legacy = {
        "Game A (U).smc": HASH_A,  # OK viejo: se reusa
        "Game B (U).zip": "",  # fallo viejo: se reintenta
    }
    (data_dir / ".snes_hash_cache.json").write_text(json.dumps(legacy), encoding="utf-8")

    resync, fake = _make_resync(tmp_path, monkeypatch)
    resync.run()

    assert "Game A (U).smc" not in fake.downloads  # vino del cache viejo
    assert "Game B (U).zip" in fake.downloads  # fallo viejo -> reintento

    report = _read_report(resync)
    assert report["files"]["Game A (U).smc"] == {"status": "cached", "hash": HASH_A, "reason": ""}
    assert report["files"]["Game B (U).zip"]["status"] == "computed"

    # El cache quedo migrado al formato nuevo.
    with open(resync.cache_file, encoding="utf-8") as f:
        cache = json.load(f)
    assert cache["Game A (U).smc"]["status"] == "ok"
    assert cache["Game B (U).zip"] == {"hash": HASH_B, "status": "ok", "reason": ""}
    assert cache["broken.zip"]["status"] == "failed"
    assert cache["broken.zip"]["reason"]


def test_interrupted_run_resumes_from_partial_cache(tmp_path, monkeypatch):
    # Simula un corte a mitad de camino: cache con solo Game A hasheado.
    data_dir = tmp_path / "Data"
    data_dir.mkdir()
    partial = {"Game A (U).smc": {"hash": HASH_A, "status": "ok", "reason": ""}}
    (data_dir / ".snes_hash_cache.json").write_text(json.dumps(partial), encoding="utf-8")

    resync, fake = _make_resync(tmp_path, monkeypatch)
    resync.run()

    assert "Game A (U).smc" not in fake.downloads
    assert "Game B (U).zip" in fake.downloads
    report = _read_report(resync)
    assert report["summary"]["cached"] == 1
    assert report["summary"]["computed"] == 1
    assert report["summary"]["failed"] == 3
