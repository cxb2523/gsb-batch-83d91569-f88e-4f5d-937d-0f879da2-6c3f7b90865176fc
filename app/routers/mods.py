import os
import time
import shutil
import asyncio
import httpx
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Tuple
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.config import settings
from app.core.security import require_auth
from app.core.process_manager import process_manager
from app.core.activity_manager import activity_manager

router = APIRouter(prefix="/api/mods", tags=["mods"], dependencies=[Depends(require_auth)])

STEAM_WORKSHOP_API = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
_WORKSHOP_CACHE: Dict[str, Tuple[Dict[str, Any], float]] = {}
_WORKSHOP_CACHE_TTL = 600.0  # 10 minutos

# Límites para la recolección por lotes con resultados individuales
WORKSHOP_ID_MAX_LENGTH = 20  # Los IDs de Workshop son numéricos de hasta 20 dígitos (uint64)
COLLECT_ITEM_TIMEOUT = 6.0   # Tiempo máximo por cada solicitud individual
COLLECT_BATCH_TIMEOUT = 30.0  # Tiempo máximo total para todo el lote


class ModsUpdateRequest(BaseModel):
    mod_ids: str


class ModsCollectRequest(BaseModel):
    mod_ids: List[str]
    force_refresh: bool = False


def _get_local_mod_info(mod_id: str) -> Dict[str, Any]:
    """Inspecciona ShooterGame/Content/Mods/<mod_id> para verificar instalación local y fecha."""
    mods_dir = settings.ark_data_dir / "ShooterGame" / "Content" / "Mods"
    mod_folder = mods_dir / str(mod_id)
    mod_meta = mods_dir / f"{mod_id}.mod"
    installed = mod_folder.exists() or mod_meta.exists()
    local_mtime = 0
    if mod_meta.exists():
        try:
            local_mtime = int(mod_meta.stat().st_mtime)
        except OSError:
            pass
    if mod_folder.exists():
        try:
            folder_mtime = int(mod_folder.stat().st_mtime)
            local_mtime = max(local_mtime, folder_mtime)
        except OSError:
            pass
    return {
        "installed_locally": installed,
        "local_updated_ts": local_mtime,
        "local_updated_str": datetime.fromtimestamp(local_mtime).strftime("%d/%m/%Y %H:%M") if local_mtime > 0 else None
    }


async def fetch_workshop_details(mod_ids: List[str], force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """Consulta la API pública de Steam Workshop para enriquecer mods con nombre, miniatura y actualizaciones."""
    clean_ids = [m.strip() for m in mod_ids if m.strip().isdigit()]
    if not clean_ids:
        return {}

    now = time.time()
    results: Dict[str, Dict[str, Any]] = {}
    to_fetch: List[str] = []

    for mid in clean_ids:
        cached = _WORKSHOP_CACHE.get(mid)
        if not force_refresh and cached and (now - cached[1] < _WORKSHOP_CACHE_TTL):
            results[mid] = dict(cached[0])
        else:
            to_fetch.append(mid)

    if to_fetch:
        form_data: Dict[str, str] = {"itemcount": str(len(to_fetch))}
        for idx, mid in enumerate(to_fetch):
            form_data[f"publishedfileids[{idx}]"] = mid

        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.post(STEAM_WORKSHOP_API, data=form_data)
                if resp.status_code == 200:
                    payload = resp.json()
                    details_list = payload.get("response", {}).get("publishedfiledetails", [])
                    for item in details_list:
                        mid = str(item.get("publishedfileid", ""))
                        if not mid:
                            continue
                        time_updated = int(item.get("time_updated", 0) or 0)
                        file_size = int(item.get("file_size", 0) or 0)
                        info = {
                            "id": mid,
                            "title": item.get("title") or f"Workshop Mod #{mid}",
                            "preview_url": item.get("preview_url") or "",
                            "creator": item.get("creator") or "",
                            "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size > 0 else 0.0,
                            "time_updated": time_updated,
                            "remote_updated_str": datetime.fromtimestamp(time_updated).strftime("%d/%m/%Y %H:%M") if time_updated > 0 else None,
                            "subscriptions": int(item.get("subscriptions", 0) or 0),
                            "Banned": bool(item.get("banned", 0)),
                        }
                        _WORKSHOP_CACHE[mid] = (info, now)
                        results[mid] = dict(info)
        except Exception:
            pass

    # Enriquecer con estado local y detección de actualizaciones pendientes
    for mid in clean_ids:
        base = results.get(mid, {
            "id": mid,
            "title": f"Steam Workshop Mod #{mid}",
            "preview_url": "",
            "creator": "",
            "file_size_mb": 0.0,
            "time_updated": 0,
            "remote_updated_str": None,
            "subscriptions": 0,
        })
        local_info = _get_local_mod_info(mid)
        base.update(local_info)
        remote_ts = int(base.get("time_updated") or 0)
        local_ts = int(local_info.get("local_updated_ts") or 0)
        # Si está instalado localmente y Steam tiene una versión más reciente (>60s de margen)
        base["update_available"] = bool(local_info["installed_locally"] and remote_ts > 0 and local_ts > 0 and remote_ts > local_ts + 60)
        results[mid] = base

    return results


def _is_valid_workshop_id(raw: str) -> bool:
    """Un ID válido es numérico, no vacío y de longitud plausible (uint64 de Steam)."""
    return bool(raw) and raw.isdigit() and len(raw) <= WORKSHOP_ID_MAX_LENGTH


def _create_collect_client() -> httpx.AsyncClient:
    """Fábrica del cliente HTTP (sustituible en pruebas)."""
    return httpx.AsyncClient(timeout=COLLECT_ITEM_TIMEOUT)


def _empty_collect_entry(original: str) -> Dict[str, Any]:
    return {
        "id": original,
        "status": None,
        "title": None,
        "author": None,
        "file_size_mb": None,
        "time_updated": None,
        "remote_updated_str": None,
    }


def _fill_entry_from_info(entry: Dict[str, Any], info: Dict[str, Any]) -> None:
    entry.update({
        "status": "success",
        "title": info.get("title"),
        "author": info.get("creator"),
        "file_size_mb": info.get("file_size_mb"),
        "time_updated": info.get("time_updated"),
        "remote_updated_str": info.get("remote_updated_str"),
    })


async def _fetch_single_workshop_details(client, mod_id: str) -> Dict[str, Any]:
    """Solicita los metadatos de un único mod; lanza excepción si no hay datos válidos."""
    form_data = {"itemcount": "1", f"publishedfileids[0]": mod_id}
    resp = await client.post(STEAM_WORKSHOP_API, data=form_data)
    if resp.status_code != 200:
        raise RuntimeError(f"Steam respondió HTTP {resp.status_code}")
    payload = resp.json()
    details_list = payload.get("response", {}).get("publishedfiledetails", [])
    item = next((d for d in details_list if str(d.get("publishedfileid", "")) == mod_id), None)
    if item is None:
        raise RuntimeError("Steam no devolvió datos para este ID")
    time_updated = int(item.get("time_updated", 0) or 0)
    file_size = int(item.get("file_size", 0) or 0)
    return {
        "id": mod_id,
        "title": item.get("title") or f"Workshop Mod #{mod_id}",
        "preview_url": item.get("preview_url") or "",
        "creator": item.get("creator") or "",
        "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size > 0 else 0.0,
        "time_updated": time_updated,
        "remote_updated_str": datetime.fromtimestamp(time_updated).strftime("%d/%m/%Y %H:%M") if time_updated > 0 else None,
    }


async def collect_workshop_metadata(
    mod_ids: List[str],
    force_refresh: bool = False,
    client=None,
    item_timeout: float = COLLECT_ITEM_TIMEOUT,
    batch_timeout: float = COLLECT_BATCH_TIMEOUT,
) -> Dict[str, Any]:
    """
    Recolecta metadatos de Workshop ID a ID, devolviendo un resultado por cada entrada.
    Ningún fallo individual interrumpe el lote ni propaga excepciones al llamador.
    """
    owns_client = client is None
    if owns_client:
        client = _create_collect_client()

    now = time.time()
    deadline = now + max(0.0, batch_timeout)
    entries: List[Dict[str, Any]] = []
    first_index: Dict[str, int] = {}

    try:
        for raw in mod_ids:
            original = raw if isinstance(raw, str) else str(raw)
            normalized = original.strip()
            entry = _empty_collect_entry(original)
            entries.append(entry)
            idx = len(entries) - 1

            # IDs vacíos, no numéricos o de longitud ilegal: inválidos sin emitir solicitud
            if not _is_valid_workshop_id(normalized):
                entry["status"] = "invalid"
                continue

            # Duplicados: solo se recolecta la primera aparición
            if normalized in first_index:
                first = first_index[normalized]
                entry["status"] = "duplicate"
                entry["duplicate_of"] = entries[first]["id"]
                entry["first_index"] = first
                continue
            first_index[normalized] = idx

            # Caché de 10 minutos: si hay acierto no se vuelve a solicitar
            cached = _WORKSHOP_CACHE.get(normalized)
            if not force_refresh and cached and (now - cached[1] < _WORKSHOP_CACHE_TTL):
                _fill_entry_from_info(entry, cached[0])
                entry["cached"] = True
                continue

            # Límite de tiempo del lote: el resto de entradas quedan como timeout
            remaining = deadline - time.time()
            if remaining <= 0:
                entry["status"] = "timeout"
                entry["error"] = "Se agotó el tiempo máximo del lote"
                continue

            try:
                info = await asyncio.wait_for(
                    _fetch_single_workshop_details(client, normalized),
                    timeout=min(item_timeout, remaining),
                )
                _WORKSHOP_CACHE[normalized] = (info, time.time())
                _fill_entry_from_info(entry, info)
                entry["cached"] = False
            except (asyncio.TimeoutError, httpx.TimeoutException):
                entry["status"] = "timeout"
                entry["error"] = "Tiempo de espera agotado para esta solicitud"
            except Exception as exc:
                entry["status"] = "failed"
                entry["error"] = str(exc) or exc.__class__.__name__
    finally:
        if owns_client:
            try:
                await client.aclose()
            except Exception:
                pass

    success_count = sum(1 for e in entries if e["status"] == "success")
    failed_count = sum(1 for e in entries if e["status"] in ("invalid", "timeout", "failed"))
    duplicate_count = sum(1 for e in entries if e["status"] == "duplicate")
    return {
        "total": len(entries),
        "success_count": success_count,
        "failed_count": failed_count,
        "duplicate_count": duplicate_count,
        "results": entries,
    }


@router.get("")
async def api_get_mods(enrich: bool = Query(True), refresh: bool = Query(False)):
    """Obtiene la lista de mods configurados y sus metadatos enriquecidos de Steam Workshop."""
    cfg = settings.runtime_config
    mod_ids_str = cfg.get("mod_ids", os.getenv("MOD_IDS", "")).strip()
    mods = [m.strip() for m in mod_ids_str.split(",") if m.strip()]
    details: Dict[str, Dict[str, Any]] = {}
    if enrich and mods:
        details = await fetch_workshop_details(mods, force_refresh=refresh)

    updates_count = sum(1 for d in details.values() if d.get("update_available"))
    return {
        "mod_ids_raw": mod_ids_str,
        "mods": mods,
        "count": len(mods),
        "details": details,
        "updates_available": updates_count
    }


@router.post("/collect")
async def api_collect_mods(req: ModsCollectRequest):
    """Recolecta metadatos de Workshop por ID, devolviendo un resultado verificable por entrada."""
    result = await collect_workshop_metadata(req.mod_ids, force_refresh=req.force_refresh)
    activity_manager.log(
        "Mods",
        f"Recolección de metadatos de Workshop: {result['success_count']} exitosos, "
        f"{result['failed_count']} fallidos (total {result['total']} IDs)"
    )
    return result


@router.post("")
async def api_save_mods(req: ModsUpdateRequest):
    """Guarda la lista de mods en la configuración activa y arkmanager.cfg."""
    raw_mods = ",".join([m.strip() for m in req.mod_ids.split(",") if m.strip()])
    if raw_mods:
        for token in raw_mods.split(","):
            if not token.strip().isdigit():
                return {"success": False, "error": "La lista de mods solo puede contener IDs numéricos separados por comas."}

    settings.runtime_config["mod_ids"] = raw_mods
    settings.save_runtime_config({"mod_ids": raw_mods})

    cfg_file = Path("/etc/arkmanager/arkmanager.cfg")
    if cfg_file.exists():
        try:
            lines = cfg_file.read_text(encoding="utf-8").splitlines()
            new_lines = [line for line in lines if not line.startswith("ark_GameModIds=")]
            if raw_mods:
                new_lines.append(f'ark_GameModIds="{raw_mods}"')
            cfg_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except Exception:
            pass

    count = len(raw_mods.split(",")) if raw_mods else 0
    activity_manager.log("Mods", f"Lista de mods actualizada ({count} mods configurados)")
    return {"success": True, "mod_ids": raw_mods, "count": count}


@router.post("/update")
async def api_update_mods():
    """Ejecuta la actualización y descarga de mods en segundo plano."""
    activity_manager.log("Mods", "Iniciando verificación y actualización de mods...")
    await process_manager.broadcast_log("[ARK Server Manager] Comprobando y actualizando mods de Steam Workshop...")
    if shutil.which("arkmanager"):
        async def _run_update():
            proc = await asyncio.create_subprocess_exec(
                "arkmanager", "update", "--no-background", "--update-mods", "@main",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await process_manager.broadcast_log(f"[ArkManager] {line.decode('utf-8', errors='replace').rstrip()}")
            await proc.wait()
            await process_manager.broadcast_log("[ARK Server Manager] Actualización de mods finalizada.")
        asyncio.create_task(_run_update())
        return {"success": True, "message": "Actualización de mods iniciada en segundo plano."}
    else:
        await process_manager.broadcast_log("[ARK Server Manager] Simulación: Mods actualizados correctamente.")
        return {"success": True, "message": "Simulación: Mods actualizados."}
