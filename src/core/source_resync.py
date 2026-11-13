"""
Resincroniza la fuente de descarga de una consola contra un item nuevo de
archive.org, cuando el item viejo murio y el nuevo tiene una estructura de
carpetas/nombres distinta.

No alcanza con comparar nombres de archivo (la nomenclatura puede diferir
entre colecciones) ni con el MD5 que expone la metadata de archive.org (es
el hash del .zip, no el de la ROM que RetroAchievements espera). Por eso
este script descarga cada candidato, lo descomprime, calcula el hash al
estilo RetroAchievements sobre la ROM de adentro, y matchea contra los
hashes que ya tenemos en Data/TamperMonkeyRetroachievements.json. Lo que no
matchea queda listado aparte para resolver a mano.

Cada corrida deja ademas un reporte auditable
(Data/<label>_resync_report.json) con la conclusion de cada candidato:
"computed" (hasheado en esta corrida), "cached" (hash reusado del cache en
disco) o "failed" (descarga/descompresion fallo, con razon corta), mas un
resumen de conteos. Las entradas fallidas del cache se reintentan en la
corrida siguiente en vez de quedar descartadas para siempre.
"""

import hashlib
import io
import json
import os
import sys
import time
import zipfile
from typing import Dict, List, Tuple

import requests

import config

from .rom_info import extract_game_name, get_console_from_rom_path

MAX_ATTEMPTS = 3  # shortcut: reintentos fijos sin backoff, igual que el resto de los sync scripts
REQUEST_TIMEOUT = 30


def _safe_console_text(text: str) -> str:
    try:
        encoding = sys.stdout.encoding or "utf-8"
        return text.encode(encoding, errors="replace").decode(encoding)
    except Exception:
        return text


def _ra_hash(data: bytes, header_modulus: int = 8192) -> str:
    """Hash estilo RetroAchievements: MD5, salvo que el tamano sea 512 bytes
    mas que un multiplo de `header_modulus` (header de copiadora), en cuyo
    caso se ignoran los primeros 512 bytes. La regla (confirmada en
    docs.retroachievements.org) es igual en espiritu para varias consolas
    pero el modulo cambia: SNES/Super Famicom usa 8KB (8192), PC Engine/
    TurboGrafx-16/SuperGrafx (cartucho) usa 128KB (131072)."""
    if len(data) % header_modulus == 512:
        data = data[512:]
    return hashlib.md5(data).hexdigest()


def _get_with_retries(url: str, **kwargs) -> requests.Response:
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
            if response.status_code == 200:
                return response
            last_error = f"status {response.status_code}"
        except requests.RequestException as e:
            last_error = f"error de red ({e})"
        if attempt < MAX_ATTEMPTS:
            time.sleep(1)
    # Sin la URL en el mensaje: el caller ya sabe que archivo estaba bajando
    # y asi el texto sirve directo como razon corta de fallo en el reporte.
    raise RuntimeError(f"{last_error} (despues de {MAX_ATTEMPTS} intentos)")


def _normalize_cache_entry(entry) -> Dict[str, str]:
    """Normaliza una entrada de cache al formato actual
    {hash, status, reason}. Admite el formato viejo (filename -> hash en
    texto plano, "" = fallo) para no perder caches de corridas anteriores."""
    if isinstance(entry, str):
        if entry:
            return {"hash": entry, "status": "ok", "reason": ""}
        return {"hash": "", "status": "failed", "reason": "fallo registrado en un cache viejo"}
    return {
        "hash": entry.get("hash", ""),
        "status": entry.get("status") or ("ok" if entry.get("hash") else "failed"),
        "reason": entry.get("reason", ""),
    }


class SourceResync:
    """Orquesta el resync de la fuente de descarga de una consola."""

    def __init__(
        self,
        console: str,
        item: str,
        label: str = None,
        header_modulus: int = 8192,
        data_dir: str = "Data",
        json_file: str = None,
    ):
        # `console` puede ser una sola consola o varias separadas por coma
        # (ej: "TurboGrafx-16,PC Engine" -- dos valores distintos de
        # get_console_from_rom_path que en la practica son la misma
        # plataforma, por un merge viejo de datos con folders distintos).
        self.consoles = [c.strip() for c in console.split(",")]
        self.item = item
        self.base_url = f"https://archive.org/download/{item}/"
        file_label = (label or self.consoles[0]).lower().replace(" ", "_")
        self.data_dir = data_dir
        self.json_file = json_file or config.JSON_FILE_PATH
        self.override_file = os.path.join(data_dir, f"{file_label}_source_override.json")
        self.missing_file = os.path.join(data_dir, f"{file_label}_missing_sources.txt")
        # Cache de resumen (hash por archivo ya calculado) -- el job puede
        # tardar bastante (un archivo por request a archive.org) y cortarse
        # a mitad de camino, esto evita perder el progreso ya hecho.
        self.cache_file = os.path.join(data_dir, f".{file_label}_hash_cache.json")
        # Reporte por archivo: conclusion de ESTA corrida para cada candidato
        # (nuevo / cache / fallo + razon), para auditar de donde salio cada
        # hash en vez de quedarse solo con el porcentaje final.
        self.report_file = os.path.join(data_dir, f"{file_label}_resync_report.json")
        self.header_modulus = header_modulus

    # Extensiones de ROM cruda que se hashean directo, sin descomprimir.
    RAW_EXTENSIONS = (".pce", ".sgx", ".sfc", ".smc", ".nes", ".bin", ".gb", ".gbc", ".gba")

    def _fetch_item_files(self) -> List[Tuple[str, int]]:
        """Devuelve [(nombre, tamano)] de los archivos descargables del item
        nuevo (.zip, o ROMs crudas sin comprimir)."""
        response = _get_with_retries(f"https://archive.org/metadata/{self.item}")
        data = response.json()
        return [
            (f["name"], int(f.get("size", 0)))
            for f in data.get("files", [])
            if f.get("name", "").lower().endswith((".zip",) + self.RAW_EXTENSIONS)
        ]

    def _hash_candidate(self, filename: str) -> Tuple[str, str]:
        """Descarga un archivo del item nuevo y devuelve (hash estilo RA de
        la ROM, ""). Si es .zip, extrae el archivo mas grande de adentro;
        si no, hashea el archivo tal cual (ya es la ROM cruda). Si algo
        sale mal devuelve ("", razon corta) -- se reporta y se sigue."""
        url = self.base_url + requests.utils.quote(filename, safe="")
        try:
            content = _get_with_retries(url).content
        except RuntimeError as e:
            return "", f"descarga fallo: {e}"
        if filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    infos = [i for i in zf.infolist() if not i.is_dir()]
                    if not infos:
                        return "", "zip vacio (sin archivos adentro)"
                    largest = max(infos, key=lambda i: i.file_size)
                    rom_bytes = zf.read(largest)
            except zipfile.BadZipFile:
                return "", "zip corrupto o invalido"
        else:
            rom_bytes = content
        return _ra_hash(rom_bytes, self.header_modulus), ""

    def _load_our_hashes(self) -> Dict[str, str]:
        """{hash: rom_path} de todas las entradas de las consolas pedidas en
        Data/TamperMonkeyRetroachievements.json."""
        with open(self.json_file, encoding="utf-8") as f:
            data = json.load(f)
        ours: Dict[str, str] = {}
        for game_id, versions in data.items():
            for item in versions:
                for hash_value, rom_path in item.items():
                    if get_console_from_rom_path(rom_path) in self.consoles:
                        ours[hash_value.upper()] = rom_path
        return ours

    def run(self):
        consoles_label = ", ".join(self.consoles)
        print(f"Resync de {consoles_label} contra el item '{self.item}' de archive.org...")

        our_hashes = self._load_our_hashes()
        print(f"{len(our_hashes)} hashes de {consoles_label} en nuestra base.")

        files = self._fetch_item_files()
        print(f"{len(files)} archivos en el item nuevo. Descargando y hasheando...")

        # filename -> {hash, status, reason}, cacheado en disco por si el
        # job se corta a mitad de camino -- al reiniciar, se saltea lo que
        # ya esta OK en el cache en vez de volver a descargar todo. Las
        # entradas con status "failed" NO se saltean: se reintentan, porque
        # un fallo viejo (red caida, archive.org caido) no es definitivo.
        cache: Dict[str, Dict[str, str]] = {}
        if os.path.exists(self.cache_file):
            with open(self.cache_file, encoding="utf-8") as f:
                cache = {name: _normalize_cache_entry(e) for name, e in json.load(f).items()}
            cached_ok = sum(1 for e in cache.values() if e["status"] == "ok")
            cached_failed = len(cache) - cached_ok
            print(f"Retomando desde cache: {cached_ok} OK, {cached_failed} fallidos a reintentar.")

        # Conclusion de ESTA corrida por archivo: "computed" (hasheado
        # ahora), "cached" (salio del cache) o "failed" (con razon corta).
        report: Dict[str, Dict[str, str]] = {}

        for i, (filename, _size) in enumerate(files, start=1):
            entry = cache.get(filename)
            if entry and entry["status"] == "ok":
                report[filename] = {"status": "cached", "hash": entry["hash"], "reason": ""}
                continue
            if entry:
                print(f"[{i}/{len(files)}] {_safe_console_text(filename)} (reintento: {entry['reason']})")
            else:
                print(f"[{i}/{len(files)}] {_safe_console_text(filename)}")
            h, reason = self._hash_candidate(filename)
            if h:
                cache[filename] = {"hash": h, "status": "ok", "reason": ""}
                report[filename] = {"status": "computed", "hash": h, "reason": ""}
            else:
                print(f"  [!] {_safe_console_text(filename)}: {reason}")
                cache[filename] = {"hash": "", "status": "failed", "reason": reason}
                report[filename] = {"status": "failed", "hash": "", "reason": reason}
            if i % 20 == 0:
                self._save_cache(cache)

        self._save_cache(cache)

        summary = self.write_outputs(cache, our_hashes, partial=False)
        summary["computed"] = sum(1 for r in report.values() if r["status"] == "computed")
        summary["cached"] = sum(1 for r in report.values() if r["status"] == "cached")
        summary["failed"] = sum(1 for r in report.values() if r["status"] == "failed")
        self._write_report(report, summary)

    def _save_cache(self, cache: Dict[str, Dict[str, str]]):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, sort_keys=True)

    def _write_report(self, report: Dict[str, Dict[str, str]], summary: Dict[str, int]):
        """Escribe el reporte auditable de la corrida: la conclusion de cada
        candidato (nuevo / cache / fallo + razon) y el resumen de conteos."""
        os.makedirs(self.data_dir, exist_ok=True)
        payload = {
            "item": self.item,
            "consoles": self.consoles,
            "summary": summary,
            "files": {name: report[name] for name in sorted(report)},
        }
        with open(self.report_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        print("\nResumen de la corrida:")
        print(f"  Hasheados nuevos:     {summary['computed']}")
        print(f"  Reusados del cache:   {summary['cached']}")
        print(f"  Fallidos:             {summary['failed']}")
        print(f"  Hashes con match:     {summary['matched']}/{summary['total']}")
        print(f"  Faltantes:            {summary['missing']}")
        print(f"Reporte por archivo: {self.report_file}")

    def write_outputs(self, cache: Dict[str, Dict[str, str]], our_hashes: Dict[str, str] = None, partial: bool = True):
        """Arma override_file/missing_file a partir de lo que haya en el
        cache en este momento. Se puede llamar con un cache a medio
        terminar (partial=True) para tener un preview mientras el resync
        completo sigue corriendo -- se reescribe igual al final con el
        cache completo. Devuelve el resumen {total, matched, missing}."""
        if our_hashes is None:
            our_hashes = self._load_our_hashes()

        new_hash_to_filename: Dict[str, str] = {}
        for filename, entry in cache.items():
            entry = _normalize_cache_entry(entry)
            if entry["status"] == "ok" and entry["hash"]:
                new_hash_to_filename[entry["hash"].upper()] = filename

        override: Dict[str, str] = {}
        missing: List[Tuple[str, str, str]] = []  # (nombre, rom_path, hash)
        for hash_value, rom_path in our_hashes.items():
            filename = new_hash_to_filename.get(hash_value)
            if filename:
                override[rom_path] = filename
            else:
                missing.append((extract_game_name(rom_path), rom_path, hash_value))

        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.override_file, "w", encoding="utf-8") as f:
            json.dump(override, f, ensure_ascii=False, indent=2, sort_keys=True)

        missing.sort(key=lambda x: x[0].lower())
        with open(self.missing_file, "w", encoding="utf-8") as f:
            for name, rom_path, hash_value in missing:
                f.write(f"{name}\t{rom_path}\t{hash_value}\n")

        total = len(our_hashes)
        matched = len(override)
        pct = (matched / total * 100) if total else 0
        label = "PARCIAL -- resync todavia corriendo" if partial else "final"
        print(f"\n[{label}] {matched}/{total} hashes con match ({pct:.1f}%).")
        print(f"Override: {self.override_file}")
        partial_note = " -- incluye lo todavia no hasheado" if partial else ""
        print(f"Faltantes: {self.missing_file} ({len(missing)}{partial_note})")
        return {"total": total, "matched": matched, "missing": len(missing)}


if __name__ == "__main__":
    assert _ra_hash(b"x" * 8192) == hashlib.md5(b"x" * 8192).hexdigest()
    headered = b"h" * 512 + b"x" * 8192
    assert _ra_hash(headered) == hashlib.md5(b"x" * 8192).hexdigest()
    print("source_resync smoke check: OK")
