"""
Orquestador del scraper local — lo dispara Task Scheduler 2-3×/día.

Por red × candidato: capturas (browser/redes, rotando cuentas si se queman) →
lectura con Gemini visión → dedup por red → un bloque por red → agregación
REUSANDO la lógica del backend (electoral._merge_bloques fusiona y calcula
por_red) → snapshot a Supabase.

Regla de seguridad: si la corrida no junta `min_posts_electorales` posts
electorales, o la subida falla, NO se pisa el snapshot anterior y el exit code
es 1 (Task Scheduler lo registra como fallo).

Cada corrida deja en logs/resultados/<runid>.json el resultado de CADA red que
realmente se corrió (`resultados_por_red`): ok, parcial (algún candidato salteado
o con lectura fallida) o fallido (la red no juntó ningún post usable). Con
`--reintentar-fallidas` se relee ese JSON y se corre SÓLO lo que no salió ok.

Uso:  python run.py [--dry-run] [--config ruta] [--redes twitter,tiktok]
                    [--reintentar-fallidas [twitter,tiktok]]
"""
import argparse
import json
import logging
import os
import re
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# El scraper corre desde el repo clonado en la PC de la oficina: reusa el código
# del backend agregándolo al path (mismo patrón que vision.py).
BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = str(BASE_DIR.parent / "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import accounts  # noqa: E402
import browser  # noqa: E402
import dedup  # noqa: E402
import redes  # noqa: E402
import vision  # noqa: E402
import electoral  # noqa: E402
import store  # noqa: E402
import alertas  # noqa: E402

RUTA_CONFIG = BASE_DIR / "config.json"
DIR_CAPTURAS = BASE_DIR / "capturas"
DIR_LOGS = BASE_DIR / "logs"
DIR_RESULTADOS = DIR_LOGS / "resultados"
ESPERA_REINTENTO = (20, 30)        # seg: espera antes de reintentar la misma cuenta ante challenge
UMBRAL_CORTE_CHALLENGES = 3        # challenges consecutivos por red antes de dejar de reintentar
LOCK_PATH = BASE_DIR / ".run.lock"

# Veredicto por red en logs/resultados/<runid>.json. Sólo hay tres estados y el
# corte entre ellos sale de lo que REALMENTE pasó (capturas + lectura), no de la
# config: una red sin candidatos en alcance no es un éxito, es fallida.
RESULTADO_OK = "ok"                # juntó posts y ningún candidato quedó en el camino
RESULTADO_PARCIAL = "parcial"      # juntó posts, pero algún candidato se salteó o no se pudo leer
RESULTADO_FALLIDO = "fallido"      # no juntó ningún post usable
EXIT_SIN_REINTENTO = 3             # --reintentar-fallidas sin nada que reintentar (no corrió nada)

log = logging.getLogger("urna.scraper")


class InstanciaActivaError(Exception):
    """Ya hay otra corrida del scraper en curso (el lock está tomado)."""


def _tomar_lock_os(fh) -> None:
    """Lock exclusivo NO bloqueante sobre el file handle; lanza OSError si ya está
    tomado por otra corrida. El lock lo mantiene el SO y se libera solo cuando el
    proceso muere (incluso por crash/OOM) — así nunca queda un lock obsoleto."""
    if os.name == "nt":
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _soltar_lock_os(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def lock_de_instancia(ruta: Path = LOCK_PATH):
    """Impide DOS corridas del scraper en paralelo. Corridas simultáneas colisionan
    de dos formas medidas en prod (2026-09-30): (1) race en `accounts.json` — una
    marca una cuenta y la otra la re-escribe → "Sin cuentas activas" espurio; (2)
    RAM — dos Chromium en la PC de 8 GB agotan la memoria y una corrida se cae por
    OOM. Lanza InstanciaActivaError si ya hay otra activa."""
    fh = open(ruta, "a+")
    try:
        _tomar_lock_os(fh)
    except OSError as e:
        fh.close()
        raise InstanciaActivaError(f"otra corrida activa (lock {ruta})") from e
    try:
        yield
    finally:
        _soltar_lock_os(fh)
        fh.close()

CONFIG_DEFAULT = {
    "redes": {"twitter": {"scrolls_por_candidato": 3}},
    "candidatos": None,  # None = electoral.CANDIDATOS_DEFAULT
    "espera_entre_scrolls": [2, 5],
    "espera_entre_candidatos": [20, 40],
    "viewport": [950, 1300],
    "headless": True,
    "min_posts_electorales": 1,
    "conservar_corridas": 3,
}


def cargar_config(ruta=None) -> dict:
    cfg = dict(CONFIG_DEFAULT)
    ruta = Path(ruta) if ruta else RUTA_CONFIG
    if ruta.exists():
        cfg.update(json.loads(ruta.read_text(encoding="utf-8")))
    # Formato legacy (Fase 3): "red" + "scrolls_por_candidato" planos.
    if "red" in cfg:
        cfg["redes"] = {cfg.pop("red"): {
            "scrolls_por_candidato": cfg.pop("scrolls_por_candidato", 3)}}
    return cfg


def filtrar_redes(cfg: dict, redes_csv: str | None) -> dict:
    """Acota cfg["redes"] a las de --redes (coma-separado). Aborta si no queda ninguna."""
    if redes_csv:
        pedidas = {r.strip() for r in redes_csv.split(",") if r.strip()}
        cfg["redes"] = {k: v for k, v in cfg["redes"].items() if k in pedidas}
    if not cfg["redes"]:
        msg = (
            "config sin redes activas." if redes_csv is None
            else f"--redes '{redes_csv}': ninguna red del config coincide."
        )
        sys.exit(msg)
    return cfg


# Un handle válido: alfanumérico/_ con puntos solo INTERIORES (no al borde ni dobles).
# Descarta nombres mostrados con espacios ("@El Peluca Milei") y truncados ("@algo…",
# "@algo...") que la visión a veces prefija con @ — darían una URL de perfil rota.
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9_.]*[A-Za-z0-9_])?$")


def _author_url(autor: str, red: str) -> str:
    """URL del PERFIL del autor a partir del @handle, o "" si `autor` no es un handle
    real (no empieza con @, o trae espacios/caracteres inválidos/truncado)."""
    autor = (autor or "").strip()
    if not autor.startswith("@"):
        return ""
    handle = autor[1:]
    if not _HANDLE_RE.match(handle):
        return ""
    if red == "twitter":
        return f"https://x.com/{handle}"
    if red == "tiktok":
        return f"https://www.tiktok.com/@{handle}"
    if red == "instagram":
        return f"https://www.instagram.com/{handle}/"
    return ""


def _slug(nombre: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in nombre.lower()).strip("-")


def _candidatos_globales(cfg: dict) -> list[str]:
    """Lista global de candidatos: `None`/ausente = la default del backend; una lista
    EXPLÍCITA (aunque venga vacía) se respeta tal cual — un `[]` significa "esta
    corrida no busca a nadie" y así se reporta, no se rellena con la default."""
    if "candidatos" in cfg and isinstance(cfg["candidatos"], list):
        return list(cfg["candidatos"])
    return list(electoral.CANDIDATOS_DEFAULT)


def candidatos_de_red(cfg: dict, red: str) -> list[str]:
    """Candidatos que ESTA red sale a buscar, no la lista global sin filtrar.

    Instagram no busca por candidato: abre los PERFILES de `candidatos_posts` y
    devuelve [] para cualquier otro término (ver `redes/instagram.py`). Su alcance
    real es, entonces, exactamente esa lista — si está vacía, la red no capturó a
    nadie y se reporta como fallida, no como "ok porque no había candidatos".
    Twitter/TikTok recorren la lista global (o la default del backend)."""
    cfg_red = cfg["redes"].get(red) or {}
    if red == "instagram":
        return list(cfg_red.get("candidatos_posts") or [])
    return _candidatos_globales(cfg)


def clasificar_resultado_red(posts: int, candidatos: int, salteados, lectura_fallida) -> str:
    """Veredicto de UNA red a partir de lo que realmente pasó (capturas + lectura).

    - `fallido`: la red no juntó ningún post usable. Incluye el caso de una red sin
      candidatos en alcance: no se puede declarar éxito algo que no se capturó.
    - `parcial`: juntó posts, pero algún candidato se salteó o su lectura falló.
    - `ok`: juntó posts y ningún candidato quedó en el camino."""
    if posts <= 0 or candidatos <= 0:
        return RESULTADO_FALLIDO
    if salteados or lectura_fallida:
        return RESULTADO_PARCIAL
    return RESULTADO_OK


def _registro_red(red: str, resultado: str, candidatos: int, posts: int,
                  salteados, lectura_fallida, posts_crudos: int = 0,
                  errores_lectura: int = 0, errores_cuota: int = 0) -> dict:
    """Entrada de `resultados_por_red`: veredicto + números + quiénes quedaron afuera."""
    salteados = list(salteados)
    lectura_fallida = list(lectura_fallida)
    con_problemas = salteados + [c for c in lectura_fallida if c not in salteados]
    return {
        "red": red,
        "resultado": resultado,
        "candidatos": candidatos,
        "posts": posts,
        "candidatos_salteados": salteados,
        "candidatos_lectura_fallida": lectura_fallida,
        # Lista combinada: el "quién quedó afuera" en un solo lugar para el operador.
        "candidatos_con_problemas": con_problemas,
        "posts_crudos": posts_crudos,
        "errores_lectura": errores_lectura,
        "errores_cuota": errores_cuota,
    }


def armar_bloque(posts: list[dict], red: str, busquedas: int, crudos: int, errores: int) -> dict:
    """Mapea los posts de visión (ya deduplicados) al shape de bloque de electoral.
    En visión extraer y clasificar es UNA pasada, así que analizados == encontrados.
    Los IDs usan f"{red}_{i}" para evitar colisiones al fusionar bloques de distintas redes."""
    posts_by_id: dict[str, dict] = {}
    analysis: list[dict] = []
    for i, post in enumerate(posts):
        pid = f"{red}_{i}"
        autor = post.get("autor") or ""
        posts_by_id[pid] = {
            "network": red, "author": autor, "author_url": _author_url(autor, red),
            "text": post.get("texto") or "", "post_url": "", "date": post.get("fecha") or "",
        }
        analysis.append({
            "id": pid,
            "candidatos": post.get("candidatos") or [],
            "cita": post.get("cita") or "",
            "es_electoral": bool(post.get("es_electoral", False)),
        })
    status = {"red": red, "busquedas": busquedas, "crudos": crudos, "errores": errores,
              "encontrados": len(posts), "analizados": len(posts)}
    return {"network": red, "posts_by_id": posts_by_id, "analysis": analysis, "status": status}


def armar_payload(bloques: list[dict], warnings: list[str]) -> dict:
    """Arma el payload del snapshot con la MISMA forma que electoral.run_boca_de_urna."""
    candidatos, baja_conf, posts_by_id, analysis = electoral._merge_bloques(bloques)
    evidencia = electoral.build_evidence(analysis, posts_by_id)
    comparacion, comp_warnings = electoral.compare_vs_pollsters(candidatos, [])
    warnings = list(warnings) + list(comp_warnings)
    if baja_conf:
        warnings.append(
            f"{baja_conf} mención(es) descartada(s) por baja confianza (< {electoral.CONF_MIN}).")
    posts_electorales = sum(1 for a in analysis if a.get("es_electoral"))
    return {
        "candidatos": candidatos, "evidencia": evidencia, "comparacion": comparacion,
        "meta": {"total_posts": sum(b["status"]["encontrados"] for b in bloques),
                 "posts_electorales": posts_electorales,
                 "analizados": sum(b["status"]["analizados"] for b in bloques),
                 "bloques": [b["status"] for b in bloques],
                 "disclaimer": electoral.DISCLAIMER, "warnings": warnings},
    }


def capturar_candidato(red_nombre: str, cfg: dict, pool: dict, candidato: str,
                       carpeta: Path, warnings: list[str],
                       estado_red: dict | None = None) -> list[dict]:
    """Capturas de UN candidato en UNA red, rotando la cuenta UNA vez si se quema.
    Ante challenge (DesafioTemporalError) reintenta UNA vez con la MISMA cuenta tras una
    espera: el challenge es a la IP, no a la cuenta; rotar chocaría el mismo muro. El
    redirect a login (SesionInvalidaError) sí quema y rota. `estado_red` lleva los
    challenges consecutivos de la red en la corrida: al llegar a UMBRAL_CORTE_CHALLENGES
    se asume bloqueo de IP y se saltea rápido, sin reintentar. Devuelve [] si no se pudo."""
    red_mod = redes.POR_NOMBRE[red_nombre]
    if estado_red is None:
        estado_red = {"challenges_consecutivos": 0}
    estado_red.setdefault("challenges_consecutivos", 0)
    for _intento in range(2):  # cuenta actual + una rotación ante quema
        cuenta = accounts.proxima_cuenta(pool)
        if cuenta is None:
            warnings.append(f"[{red_nombre}] Sin cuentas activas: '{candidato}' quedó sin capturar.")
            return []
        reintentar = estado_red["challenges_consecutivos"] < UMBRAL_CORTE_CHALLENGES
        for _reintento in range(2 if reintentar else 1):  # 1er intento (+1 reintento si corresponde)
            try:
                capturas = red_mod.capturar(
                    sesion=accounts.ruta_sesion(cuenta["alias"], red_nombre), termino=candidato,
                    cfg=cfg, cfg_red=cfg["redes"][red_nombre], carpeta=carpeta,
                    prefijo=f"{red_nombre}-{_slug(candidato)}", warnings=warnings)
                accounts.registrar_uso(pool, cuenta["alias"])
                estado_red["challenges_consecutivos"] = 0  # éxito: resetea el corte
                return capturas
            except browser.DesafioTemporalError as e:
                if _reintento == 0 and reintentar:
                    log.warning("[%s] Challenge con '%s' (%s); reintento con la misma cuenta "
                                "en %d-%ds.", red_nombre, candidato, e, *ESPERA_REINTENTO)
                    browser.esperar_aleatorio(ESPERA_REINTENTO)
                    continue  # reintenta la MISMA cuenta
                estado_red["challenges_consecutivos"] += 1
                log.warning("[%s] Challenge temporal con '%s': %s (se saltea; la cuenta sigue activa).",
                            red_nombre, candidato, e)
                warnings.append(f"[{red_nombre}] '{candidato}' salteado por challenge temporal "
                                f"({e}); la cuenta sigue activa.")
                return []
            except browser.SesionInvalidaError as e:
                log.warning("[%s] Cuenta '%s' quemada/challenge: %s", red_nombre, cuenta["alias"], e)
                accounts.marcar_quemada(pool, cuenta["alias"])
                warnings.append(f"[{red_nombre}] Cuenta '{cuenta['alias']}' marcada como quemada.")
                break  # rompe el reintento → el loop externo rota de cuenta
            except Exception as e:
                log.error("[%s] Error inesperado capturando '%s': %s", red_nombre, candidato, e)
                warnings.append(f"[{red_nombre}] '{candidato}' quedó sin capturar (error del navegador: {e}).")
                return []
    warnings.append(f"[{red_nombre}] '{candidato}' quedó sin capturar (dos cuentas fallaron).")
    return []


def _limpiar_corridas_viejas(conservar: int) -> None:
    """Borra las carpetas de capturas más viejas, conservando las últimas N."""
    if conservar <= 0 or not DIR_CAPTURAS.exists():
        return
    corridas = sorted((d for d in DIR_CAPTURAS.iterdir() if d.is_dir()), key=lambda d: d.name)
    for vieja in corridas[:-conservar]:
        shutil.rmtree(vieja, ignore_errors=True)


def _umbral_de(cfg: dict) -> int:
    """Umbral de avisos del config; default 8 si falta o está malformado."""
    alertas_cfg = cfg.get("alertas")
    if isinstance(alertas_cfg, dict):
        return alertas_cfg.get("umbral_warnings", 8)
    return 8


def _armar_resultado(runid, redes_corridas, exit_code, posts_por_red,
                     warnings_finales, posts_electorales, umbral_warnings,
                     errores_cuota_por_red=None, resultados_por_red=None,
                     reintento_de=None):
    """Arma el dict de resultado de una corrida y le pega el veredicto de alertas.

    `resultados_por_red` es el veredicto de CADA red que se corrió (ok / parcial /
    fallido) con sus números y los candidatos que quedaron afuera. Los campos
    viejos se mantienen tal cual para no romper a `aviso-matutino.ps1`."""
    cuentas_quemadas = [w for w in warnings_finales if "marcada como quemada" in w]
    resultado = {
        "runid": runid,
        "fin_utc": datetime.now(timezone.utc).isoformat(),
        "redes": list(redes_corridas),
        "exit_code": exit_code,
        "posts_por_red": dict(posts_por_red),
        "warnings_total": len(warnings_finales),
        "cuentas_quemadas": cuentas_quemadas,
        "posts_electorales": posts_electorales,
        # Solo las redes que tuvieron capturas sin leer por cuota de Gemini (429/503).
        "errores_cuota_por_red": {k: v for k, v in (errores_cuota_por_red or {}).items() if v},
        # Veredicto por red (campo nuevo; los viejos no cambian de forma).
        "resultados_por_red": dict(resultados_por_red or {}),
        # runid de la corrida cuyas redes fallidas se están reintentando ("" = corrida normal).
        "reintento_de": reintento_de or "",
    }
    veredicto = alertas.evaluar(resultado, umbral_warnings=umbral_warnings)
    resultado["nivel"] = veredicto["nivel"] if veredicto else "ok"
    resultado["titulo"] = veredicto["titulo"] if veredicto else ""
    resultado["mensaje"] = veredicto["mensaje"] if veredicto else ""
    return resultado


def _podar_resultados(conservar: int) -> None:
    """Deja sólo los últimos N json de resultados (son chicos; evita acumular)."""
    if conservar <= 0 or not DIR_RESULTADOS.exists():
        return
    archivos = sorted(DIR_RESULTADOS.glob("*.json"), key=lambda p: p.name)
    for viejo in archivos[:-conservar]:
        viejo.unlink(missing_ok=True)


def _escribir_resultado(resultado: dict) -> None:
    """Escribe logs/resultados/<runid>.json. Nunca rompe la corrida."""
    try:
        DIR_RESULTADOS.mkdir(parents=True, exist_ok=True)
        ruta = DIR_RESULTADOS / f"{resultado['runid']}.json"
        ruta.write_text(json.dumps(resultado, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        _podar_resultados(60)
    except Exception:
        log.exception("No se pudo escribir el resultado de la corrida (se ignora).")


def _agrupar_por_contexto(capturas: list[dict]) -> list[list[dict]]:
    """Agrupa las capturas que comparten `contexto` para leerlas en UNA sola llamada a
    visión. Preserva el orden de primera aparición de cada contexto (dict ordenado)."""
    grupos: dict[str, list[dict]] = {}
    for cap in capturas:
        grupos.setdefault(cap["contexto"], []).append(cap)
    return list(grupos.values())


def ruta_ultimo_resultado(directorio: Path | None = None) -> Path | None:
    """JSON de resultado más reciente (`<runid>.json`, el nombre ordena cronológicamente).
    Devuelve None si todavía no hay ninguno.

    Un runid `--dry-run` jamás se escribe (ver `correr`), así que una prueba en seco no
    puede convertirse acá en "la última corrida a reintentar"; un JSON ilegible o de un
    crash se saltea porque no sirve para decidir qué reintentar."""
    directorio = Path(directorio) if directorio is not None else DIR_RESULTADOS
    if not directorio.exists():
        return None
    archivos = sorted((p for p in directorio.glob("*.json") if p.is_file()),
                      key=lambda p: p.name)
    if not archivos:
        return None
    # Saltear JSON corruptos (escritura cortada a mitad) hacia atrás.
    for archivo in reversed(archivos):
        try:
            json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        return archivo
    return None


def cargar_ultimo_resultado(directorio: Path | None = None) -> tuple[dict | None, Path | None]:
    """(resultado, ruta) del último JSON válido; (None, None) si no hay ninguno."""
    ruta = ruta_ultimo_resultado(directorio)
    if ruta is None:
        return None, None
    try:
        return json.loads(ruta.read_text(encoding="utf-8")), ruta
    except (OSError, ValueError):
        return None, ruta


def redes_fallidas(resultado: dict) -> list[str]:
    """Redes cuyo desenlace en `resultado` NO fue `ok`, en el orden de la corrida.

    Sólo considera redes de las que hay evidencia de que se corrieron: las que tienen
    entrada en `resultados_por_red` (formato nuevo) o en `posts_por_red`. Una red de
    `redes` sin ninguno de los dos no se ejecutó (p.ej. nombre desconocido en el
    config) y no se puede declarar fallida.

    Para un JSON viejo sin `resultados_por_red`, una red con 0 posts es fallida; el
    resto no se puede distinguir de `ok` sin el detalle, así que no se marca."""
    registros = resultado.get("resultados_por_red") or {}
    posts = resultado.get("posts_por_red") or {}
    orden = list(resultado.get("redes") or [])
    for fuente in (registros, posts):
        for red in fuente:
            if red not in orden:
                orden.append(red)
    fallidas: list[str] = []
    for red in orden:
        registro = registros.get(red)
        if isinstance(registro, dict):
            if registro.get("resultado") != RESULTADO_OK:
                fallidas.append(red)
        elif red in posts and posts.get(red, 0) == 0:
            fallidas.append(red)  # JSON legacy: sin detalle, sólo el 0 es concluyente
    return fallidas


def seleccionar_redes_reintento(resultado: dict, pedidas: list[str] | None) -> list[str]:
    """Redes a reintentar: las no-`ok` del último resultado, opcionalmente acotadas a
    `pedidas`. Nunca devuelve una red que no falló."""
    fallidas = redes_fallidas(resultado)
    if pedidas is not None:
        fallidas = [r for r in fallidas if r in set(pedidas)]
    return fallidas


def alcance_reintento(flag_val: str, redes_csv: str | None) -> list[str] | None:
    """Nombres que acotan el reintento, combinando --reintentar-fallidas y --redes por
    INTERSECCIÓN (los dos acotan; ninguno puede ampliar lo que el otro pidió).

    Devuelve None si no se pidió ningún nombre (reintentar TODAS las fallidas), o la
    lista de nombres (posiblemente vacía si los dos pedidos no se solapan)."""
    pedidos = []
    if flag_val:
        pedidos.append({r.strip() for r in flag_val.split(",") if r.strip()})
    if redes_csv:
        pedidos.append({r.strip() for r in redes_csv.split(",") if r.strip()})
    if not pedidos:
        return None
    return sorted(set.intersection(*pedidos) if len(pedidos) > 1 else pedidos[0])


def _preparar_reintento(cfg: dict, pedidas: list[str] | None) -> tuple[dict | None, str, str]:
    """Resuelve qué redes reintentar a partir del último resultado.

    Devuelve `(cfg, runid_origen, "")` con `cfg["redes"]` acotado a las redes que
    NO salieron `ok`, o `(None, "", motivo)` —sin arrancar nada— si no hay último
    resultado, si no tiene redes fallidas, o si ninguna de ésas se puede correr."""
    directorio = DIR_RESULTADOS
    if not directorio.exists() or ruta_ultimo_resultado(directorio) is None:
        return None, "", ("--reintentar-fallidas: no hay ningún resultado previo en "
                          f"{directorio}; corré una corrida normal antes "
                          "(una prueba --dry-run no escribe resultado y no cuenta).")
    ultimo, _ruta = cargar_ultimo_resultado(directorio)
    if ultimo is None:
        return None, "", (f"--reintentar-fallidas: no se pudo leer ningún resultado válido en "
                          f"{directorio}; corré una corrida normal antes.")
    runid = str(ultimo.get("runid") or "")
    a_reintentar = seleccionar_redes_reintento(ultimo, pedidas)
    if not a_reintentar:
        if pedidas is not None:
            return None, "", (f"--reintentar-fallidas: lo pedido ({', '.join(pedidas) or 'nada'}) "
                              "no incluye ninguna red fallida de la última corrida "
                              f"({runid or '?'}); no hay nada que reintentar.")
        return None, "", (f"--reintentar-fallidas: la última corrida ({runid or '?'}) no tiene "
                          f"redes con resultado distinto de '{RESULTADO_OK}'; "
                          "no hay nada que reintentar.")
    # Una red que ya no está en el config (o que el scraper no conoce) no se puede
    # correr; si quedan otras, se corre el resto y se avisa.
    corribles = [r for r in a_reintentar
                 if r in cfg["redes"] and r in redes.POR_NOMBRE]
    omitidas = [r for r in a_reintentar if r not in corribles]
    if omitidas:
        log.warning("--reintentar-fallidas: %s no se puede(n) correr (no está(n) en el "
                    "config o no es una red conocida); se omite(n).", ", ".join(omitidas))
    if not corribles:
        return None, "", ("--reintentar-fallidas: las redes fallidas de la última corrida "
                          f"({runid or '?'}) no se pueden correr con el config actual "
                          f"({', '.join(a_reintentar)}); no hay nada que reintentar.")
    cfg = dict(cfg)
    cfg["redes"] = {r: cfg["redes"][r] for r in corribles}
    cfg["_reintento_de"] = runid
    log.info("Reintento de las redes no-%s de %s: %s", RESULTADO_OK,
             runid or "la corrida anterior", ", ".join(corribles))
    return cfg, runid, ""


def correr(cfg: dict, dry_run: bool = False) -> int:
    # `_reintento_de` lo inyecta main() al usar --reintentar-fallidas; viaja en el cfg
    # para no cambiar la firma de correr() (la usan run.ps1 y los tests con mocks).
    reintento_de = str(cfg.get("_reintento_de") or "")
    inicio = datetime.now(timezone.utc)
    carpeta = DIR_CAPTURAS / inicio.strftime("%Y%m%d-%H%M")
    warnings: list[str] = []
    # Lista de referencia que recibe el prompt de visión (NO exhaustiva).
    candidatos_ref = _candidatos_globales(cfg)

    bloques: list[dict] = []
    posts_por_red: dict[str, int] = {}
    errores_cuota_por_red: dict[str, int] = {}
    resultados_por_red: dict[str, dict] = {}
    for red_nombre in cfg["redes"]:
        if red_nombre not in redes.POR_NOMBRE:
            warnings.append(f"Red desconocida en config: '{red_nombre}' (se saltea).")
            # No se corrió: no se inventa un veredicto para una red que ni se intentó.
            continue
        # Lo que la red realmente sale a buscar (Instagram sólo los punteros configurados).
        candidatos_red = candidatos_de_red(cfg, red_nombre)
        pool = accounts.cargar_pool(red=red_nombre)
        crudos_red: list[dict] = []
        errores = 0
        errores_cuota = 0  # subconjunto de `errores` por falta de cuota de Gemini (429/503)
        salteados: list[str] = []        # candidatos sin ninguna captura
        lectura_fallida: list[str] = []  # candidatos con capturas que Gemini no pudo leer
        estado_red = {"challenges_consecutivos": 0}
        for i, candidato in enumerate(candidatos_red):
            log.info("[%s] Candidato %d/%d: %s", red_nombre, i + 1, len(candidatos_red), candidato)
            capturas = capturar_candidato(red_nombre, cfg, pool, candidato, carpeta, warnings, estado_red)
            if not capturas:
                # Sin capturas = el candidato quedó afuera (cuenta, challenge, error del
                # navegador o red que no lo busca). Es una falla REAL, no un "no había posts".
                salteados.append(candidato)
            fallo_lectura_candidato = False
            # Las capturas de un candidato que comparten contexto se leen JUNTAS en una
            # sola llamada a visión (varias imágenes por request) para no gastar una
            # llamada de cuota por cada scroll.
            for grupo in _agrupar_por_contexto(capturas):
                rutas = [c["ruta"] for c in grupo]
                leidos, status = vision.read_captures(rutas, red_nombre, candidatos_ref,
                                                      contexto=grupo[0]["contexto"])
                if leidos is None:
                    errores += len(grupo)
                    fallo_lectura_candidato = True
                    if status in (429, 503):
                        errores_cuota += len(grupo)
                    nombres = ", ".join(r.name for r in rutas)
                    warnings.append(f"Lectura fallida (Gemini) de {len(grupo)} captura(s): {nombres}.")
                    continue
                crudos_red.extend(leidos)
            if fallo_lectura_candidato:
                lectura_fallida.append(candidato)
            if i + 1 < len(candidatos_red) and capturas:
                browser.esperar_aleatorio(tuple(cfg["espera_entre_candidatos"]))
        accounts.guardar_pool(pool, red=red_nombre)
        errores_cuota_por_red[red_nombre] = errores_cuota
        posts_red = dedup.dedup_posts(crudos_red)
        posts_por_red[red_nombre] = len(posts_red)
        log.info("[%s] Posts: %d crudos, %d tras dedup, %d errores de lectura.",
                 red_nombre, len(crudos_red), len(posts_red), errores)
        resultado_red = clasificar_resultado_red(
            posts=len(posts_red), candidatos=len(candidatos_red),
            salteados=salteados, lectura_fallida=lectura_fallida)
        resultados_por_red[red_nombre] = _registro_red(
            red_nombre, resultado_red, candidatos=len(candidatos_red),
            posts=len(posts_red), salteados=salteados, lectura_fallida=lectura_fallida,
            posts_crudos=len(crudos_red), errores_lectura=errores,
            errores_cuota=errores_cuota)
        if resultado_red != RESULTADO_OK:
            log.warning("[%s] Resultado %s: %d/%d post(s), salteados=%s, lectura fallida=%s",
                        red_nombre, resultado_red, len(posts_red), len(candidatos_red),
                        salteados, lectura_fallida)
        bloques.append(armar_bloque(posts_red, red_nombre, busquedas=len(candidatos_red),
                                    crudos=len(crudos_red), errores=errores))

    payload = armar_payload(bloques, warnings)
    pe = payload["meta"]["posts_electorales"]
    warnings_finales = payload["meta"]["warnings"]

    if dry_run:
        log.info("[dry-run] NO se sube el snapshot.")
        print(json.dumps(payload["meta"], ensure_ascii=False, indent=2))
        return 0

    exit_code = 0
    if pe < cfg["min_posts_electorales"]:
        log.error("Solo %d post(s) electoral(es) (mínimo %d): NO se pisa el snapshot anterior.",
                  pe, cfg["min_posts_electorales"])
        exit_code = 1
    elif not store.write_snapshot(payload, inicio.isoformat()):
        log.error("La subida a Supabase falló: el snapshot anterior queda vigente.")
        exit_code = 1
    else:
        log.info("Snapshot subido: %d candidatos, %d posts electorales, %d warnings.",
                 len(payload["candidatos"]), pe, len(warnings_finales))
        _limpiar_corridas_viejas(cfg["conservar_corridas"])

    umbral = _umbral_de(cfg)
    resultado = _armar_resultado(inicio.strftime("%Y%m%d-%H%M"), cfg["redes"].keys(),
                                 exit_code, posts_por_red, warnings_finales, pe, umbral,
                                 errores_cuota_por_red=errores_cuota_por_red,
                                 resultados_por_red=resultados_por_red,
                                 reintento_de=reintento_de)
    _escribir_resultado(resultado)
    return exit_code


def _registro_red_caida(red: str) -> dict:
    """Entrada para una red que estaba en la corrida pero no llegó a terminar (crash).
    Se marca `fallido`, nunca `ok`: sin resultados no se puede afirmar que anduvo."""
    return _registro_red(red, RESULTADO_FALLIDO, candidatos=0, posts=0,
                         salteados=[], lectura_fallida=[])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Corrida del scraper local de la Boca de Urna.")
    ap.add_argument("--dry-run", action="store_true",
                    help="no sube el snapshot ni limpia capturas; imprime el meta")
    ap.add_argument("--config", default=None, help="ruta alternativa de config.json")
    ap.add_argument("--redes", default=None,
                    help="coma-separado (ej. twitter,tiktok); acota la corrida a esas redes")
    ap.add_argument("--reintentar-fallidas", dest="reintentar_fallidas",
                    nargs="?", const="", default=None, metavar="REDES",
                    help="corre SÓLO las redes cuyo resultado en el último JSON no fue "
                         f"'{RESULTADO_OK}' (coma-separado opcional para acotar; p.ej. "
                         "--reintentar-fallidas tiktok,instagram). Si no hay último resultado "
                         "o no hay redes fallidas, avisa y sale con código != 0 sin scrapear")
    args = ap.parse_args(argv)
    DIR_LOGS.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(
                      DIR_LOGS / f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.log",
                      encoding="utf-8")])
    cfg = cargar_config(args.config)
    reintento_de = ""
    if args.reintentar_fallidas is not None:
        # El flag acota por sí solo; --redes, si vino, se INTERSECTA (nunca amplía).
        pedidas = alcance_reintento(args.reintentar_fallidas, args.redes)
        cfg, reintento_de, motivo = _preparar_reintento(cfg, pedidas)
        if motivo:
            log.error(motivo)
            print(f"ERROR: {motivo}", file=sys.stderr)
            return EXIT_SIN_REINTENTO
    else:
        cfg = filtrar_redes(cfg, args.redes)
    try:
        with lock_de_instancia(LOCK_PATH):
            return correr(cfg, dry_run=args.dry_run)
    except InstanciaActivaError as e:
        log.error("No arranco: %s. Ya hay una corrida en curso; evito colisionar "
                  "por las cuentas y la RAM.", e)
        return 2
    except Exception:
        log.exception("La corrida crasheó sin terminar.")
        if not args.dry_run:
            runid = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
            redes_cfg = list(cfg.get("redes", {}))
            _escribir_resultado({
                "runid": runid,
                "fin_utc": datetime.now(timezone.utc).isoformat(),
                "redes": redes_cfg,
                "exit_code": 1, "posts_por_red": {}, "warnings_total": 0,
                "cuentas_quemadas": [], "posts_electorales": 0,
                # La corrida no terminó: ninguna red puede declararse sana.
                "resultados_por_red": {r: _registro_red_caida(r) for r in redes_cfg},
                "reintento_de": reintento_de,
                "nivel": "alerta", "titulo": alertas.TITULO,
                "mensaje": "La corrida crasheó, revisá el log.",
            })
        return 1


if __name__ == "__main__":
    sys.exit(main())
