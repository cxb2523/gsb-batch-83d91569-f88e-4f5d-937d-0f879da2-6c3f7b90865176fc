"""Tests de run.py — orquestación con browser/vision/store mockeados (sin red)."""
import json
from pathlib import Path

import pytest

import run
import browser as browser_mod
from redes import twitter


POST_MILEI = {"texto": "Gran discurso de Milei", "autor": "@fan", "fecha": "2 h",
              "red": "twitter", "es_electoral": True,
              "candidatos": [{"nombre": "Javier Milei", "postura": "a_favor", "confianza": 0.9}],
              "cita": "Gran discurso"}
POST_RUIDO = {"texto": "Partidazo de River", "autor": "@futbol", "fecha": "3 h",
              "red": "twitter", "es_electoral": False, "candidatos": [], "cita": ""}
POST_TIKTOK = {"texto": "Milei imparable en TikTok", "autor": "@tt", "fecha": "1 d",
               "red": "tiktok", "es_electoral": True,
               "candidatos": [{"nombre": "Javier Milei", "postura": "a_favor", "confianza": 0.8}],
               "cita": "imparable"}


def _cfg(**over):
    cfg = run.cargar_config(Path("no-existe.json"))
    cfg.update({"espera_entre_candidatos": [0, 0], "espera_entre_scrolls": [0, 0]})
    cfg.update(over)
    return cfg


def test_cargar_config_defaults_y_override(tmp_path):
    assert run.cargar_config(tmp_path / "nada.json")["redes"] == {
        "twitter": {"scrolls_por_candidato": 3}}
    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps({"redes": {"twitter": {"scrolls_por_candidato": 7}}}),
                    encoding="utf-8")
    cfg = run.cargar_config(ruta)
    assert cfg["redes"]["twitter"]["scrolls_por_candidato"] == 7
    assert cfg["headless"] is True  # el resto conserva el default


def test_cargar_config_traduce_formato_legacy(tmp_path):
    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps({"red": "twitter", "scrolls_por_candidato": 5,
                                "headless": False}), encoding="utf-8")
    cfg = run.cargar_config(ruta)
    assert cfg["redes"] == {"twitter": {"scrolls_por_candidato": 5}}
    assert "red" not in cfg and "scrolls_por_candidato" not in cfg
    assert cfg["headless"] is False


def test_filtrar_redes_acota_y_valida():
    cfg = {"redes": {"twitter": {"a": 1}, "tiktok": {"b": 2}}}
    assert run.filtrar_redes(dict(cfg), "tiktok")["redes"] == {"tiktok": {"b": 2}}
    assert run.filtrar_redes(dict(cfg), None)["redes"] == cfg["redes"]
    with pytest.raises(SystemExit):
        run.filtrar_redes(dict(cfg), "instagram")


def test_armar_bloque_mapea_al_shape_de_electoral():
    bloque = run.armar_bloque([POST_MILEI, POST_RUIDO], "twitter",
                              busquedas=2, crudos=5, errores=1)
    assert bloque["network"] == "twitter"
    assert bloque["posts_by_id"]["twitter_0"]["author"] == "@fan"
    assert bloque["posts_by_id"]["twitter_0"]["author_url"] == "https://x.com/fan"
    assert bloque["posts_by_id"]["twitter_1"]["author_url"] == "https://x.com/futbol"
    assert bloque["analysis"][0]["candidatos"][0]["nombre"] == "Javier Milei"
    assert bloque["analysis"][1]["es_electoral"] is False
    assert bloque["status"] == {"red": "twitter", "busquedas": 2, "crudos": 5,
                                "errores": 1, "encontrados": 2, "analizados": 2}


def test_armar_bloque_autor_sin_arroba_no_arma_url():
    bloque = run.armar_bloque([dict(POST_MILEI, autor="Nombre Visible")], "twitter", 1, 1, 0)
    assert bloque["posts_by_id"]["twitter_0"]["author_url"] == ""


def test_armar_payload_reusa_electoral():
    bloque = run.armar_bloque([POST_MILEI, POST_RUIDO], "twitter", 2, 5, 0)
    payload = run.armar_payload([bloque], ["warn-previo"])
    assert payload["candidatos"][0]["nombre"] == "Javier Milei"
    assert payload["candidatos"][0]["por_red"] == {"twitter": 1}
    assert payload["evidencia"][0]["candidato"] == "Javier Milei"
    assert isinstance(payload["comparacion"], list)
    meta = payload["meta"]
    assert meta["total_posts"] == 2 and meta["posts_electorales"] == 1
    assert meta["bloques"] == [bloque["status"]]
    assert "termómetro" in meta["disclaimer"] or "termometro" in meta["disclaimer"].lower()
    assert "warn-previo" in meta["warnings"]


def test_armar_payload_fusiona_bloques_por_red():
    b_tw = run.armar_bloque([POST_MILEI], "twitter", busquedas=1, crudos=1, errores=0)
    b_tt = run.armar_bloque([POST_TIKTOK], "tiktok", busquedas=1, crudos=2, errores=1)
    payload = run.armar_payload([b_tw, b_tt], [])
    assert payload["candidatos"][0]["nombre"] == "Javier Milei"
    assert payload["candidatos"][0]["por_red"] == {"twitter": 1, "tiktok": 1}
    meta = payload["meta"]
    assert meta["total_posts"] == 2 and meta["posts_electorales"] == 2
    assert [b["red"] for b in meta["bloques"]] == ["twitter", "tiktok"]


def test_author_url_por_red():
    assert run._author_url("@fan", "twitter") == "https://x.com/fan"
    assert run._author_url("@fan", "tiktok") == "https://www.tiktok.com/@fan"
    assert run._author_url("Nombre Visible", "tiktok") == ""


def test_author_url_rechaza_handle_con_espacios():
    # En TikTok la visión suele leer el nombre MOSTRADO y a veces lo prefija con @.
    # "@El Peluca Milei" no es un handle: armar la URL tal cual da un link roto
    # (https://www.tiktok.com/@El Peluca Milei). Mejor sin link que con uno inválido.
    assert run._author_url("@El Peluca Milei", "tiktok") == ""
    assert run._author_url("@Jorge Monta 55", "twitter") == ""


def test_author_url_rechaza_handle_truncado():
    # Nombres cortados por la UI ("@algo…", "@algo...") no son handles válidos.
    assert run._author_url("@pampabrea…", "tiktok") == ""
    assert run._author_url("@ElPeluca...", "tiktok") == ""


def test_author_url_acepta_handle_limpio_con_punto():
    assert run._author_url("@fan.oficial", "instagram") == "https://www.instagram.com/fan.oficial/"
    assert run._author_url("@libertad_2026", "twitter") == "https://x.com/libertad_2026"


def test_capturar_candidato_rota_ante_sesion_invalida(tmp_path, monkeypatch):
    pool = {"cuentas": [
        {"alias": "muerta", "estado": "activa", "ultima_vez": "", "notas": ""},
        {"alias": "viva", "estado": "activa", "ultima_vez": "2026-09-01T00:00:00+00:00", "notas": ""},
    ]}
    usadas = []
    def fake_capturar(sesion, termino, cfg, cfg_red, carpeta, prefijo, warnings):
        usadas.append(sesion.name)
        if sesion.name == "muerta.json":
            raise browser_mod.SesionInvalidaError("challenge")
        return [{"ruta": tmp_path / "cap-1.png", "contexto": ""}]
    monkeypatch.setattr(twitter, "capturar", fake_capturar)
    warnings = []
    capturas = run.capturar_candidato("twitter", _cfg(), pool, "Javier Milei", tmp_path, warnings)
    assert usadas == ["muerta.json", "viva.json"]
    assert len(capturas) == 1
    assert pool["cuentas"][0]["estado"] == "quemada"
    assert any("quemada" in w for w in warnings)


def test_capturar_candidato_challenge_reintenta_sin_quemar_ni_rotar(tmp_path, monkeypatch):
    """DesafioTemporalError: reintenta UNA vez con la MISMA cuenta (el challenge es a la
    IP, no a la cuenta). Si persiste: warning + salteado, sin quemar ni rotar a la otra."""
    monkeypatch.setattr(run.browser, "esperar_aleatorio", lambda rango: None)
    pool = {"cuentas": [
        {"alias": "a", "estado": "activa", "ultima_vez": "", "notas": ""},
        {"alias": "b", "estado": "activa", "ultima_vez": "2026-09-01T00:00:00+00:00", "notas": ""},
    ]}
    usadas = []
    def challenge(sesion, termino, cfg, cfg_red, carpeta, prefijo, warnings):
        usadas.append(sesion.name)
        raise browser_mod.DesafioTemporalError("captcha en pantalla")
    monkeypatch.setattr(twitter, "capturar", challenge)
    warnings = []
    capturas = run.capturar_candidato("twitter", _cfg(), pool, "Javier Milei", tmp_path, warnings)
    assert capturas == []
    assert usadas == ["a.json", "a.json"]  # reintentó la MISMA cuenta, NO rotó a b
    assert all(c["estado"] == "activa" for c in pool["cuentas"])  # nadie quemada
    assert any("challenge" in w for w in warnings)


def test_capturar_candidato_reintenta_y_recupera(tmp_path, monkeypatch):
    monkeypatch.setattr(run.browser, "esperar_aleatorio", lambda rango: None)
    pool = {"cuentas": [{"alias": "a", "estado": "activa", "ultima_vez": "", "notas": ""}]}
    llamadas = []
    def challenge_luego_ok(sesion, termino, cfg, cfg_red, carpeta, prefijo, warnings):
        llamadas.append(sesion.name)
        if len(llamadas) == 1:
            raise browser_mod.DesafioTemporalError("feed lento")
        return [{"ruta": tmp_path / "cap-1.png", "contexto": ""}]
    monkeypatch.setattr(twitter, "capturar", challenge_luego_ok)
    estado = {"challenges_consecutivos": 0}
    capturas = run.capturar_candidato("twitter", _cfg(), pool, "Milei", tmp_path, [], estado)
    assert len(capturas) == 1
    assert llamadas == ["a.json", "a.json"]        # reintentó la MISMA cuenta
    assert estado["challenges_consecutivos"] == 0  # el éxito resetea el contador


def test_capturar_candidato_challenge_persistente_incrementa_contador(tmp_path, monkeypatch):
    monkeypatch.setattr(run.browser, "esperar_aleatorio", lambda rango: None)
    pool = {"cuentas": [{"alias": "a", "estado": "activa", "ultima_vez": "", "notas": ""}]}
    llamadas = []
    def challenge(sesion, termino, cfg, cfg_red, carpeta, prefijo, warnings):
        llamadas.append(sesion.name)
        raise browser_mod.DesafioTemporalError("captcha")
    monkeypatch.setattr(twitter, "capturar", challenge)
    estado = {"challenges_consecutivos": 0}
    capturas = run.capturar_candidato("twitter", _cfg(), pool, "Milei", tmp_path, [], estado)
    assert capturas == []
    assert llamadas == ["a.json", "a.json"]        # 1er intento + 1 reintento
    assert estado["challenges_consecutivos"] == 1
    assert pool["cuentas"][0]["estado"] == "activa"  # NO quemada


def test_capturar_candidato_corte_no_reintenta(tmp_path, monkeypatch):
    monkeypatch.setattr(run.browser, "esperar_aleatorio", lambda rango: None)
    pool = {"cuentas": [{"alias": "a", "estado": "activa", "ultima_vez": "", "notas": ""}]}
    llamadas = []
    def challenge(sesion, termino, cfg, cfg_red, carpeta, prefijo, warnings):
        llamadas.append(sesion.name)
        raise browser_mod.DesafioTemporalError("captcha")
    monkeypatch.setattr(twitter, "capturar", challenge)
    estado = {"challenges_consecutivos": 3}  # corte ya activo (bloqueo de IP probable)
    capturas = run.capturar_candidato("twitter", _cfg(), pool, "Milei", tmp_path, [], estado)
    assert capturas == []
    assert llamadas == ["a.json"]  # sin reintento: una sola llamada
    assert estado["challenges_consecutivos"] == 4  # el corte igual contabiliza el challenge (3 -> 4)
    assert pool["cuentas"][0]["estado"] == "activa"  # un challenge nunca quema la cuenta


def test_capturar_candidato_sin_cuentas_devuelve_vacio(tmp_path):
    warnings = []
    rutas = run.capturar_candidato("twitter", _cfg(), {"cuentas": []}, "X", tmp_path, warnings)
    assert rutas == [] and any("Sin cuentas activas" in w for w in warnings)


def _preparar_correr(monkeypatch, tmp_path, posts_por_captura, escritos):
    """Mockea todo lo externo de correr(): cuentas, browser, vision, store, esperas."""
    pool = {"cuentas": [{"alias": "a", "estado": "activa", "ultima_vez": "", "notas": ""}]}
    monkeypatch.setattr(run.accounts, "cargar_pool", lambda ruta=None, red="twitter": pool)
    monkeypatch.setattr(run.accounts, "guardar_pool", lambda p, ruta=None, red="twitter": None)
    monkeypatch.setattr(run, "capturar_candidato",
                        lambda red_nombre, cfg, pool, cand, carpeta, warnings, estado_red=None: [
                            {"ruta": tmp_path / f"{red_nombre}-{cand}.png", "contexto": ""}])
    monkeypatch.setattr(run.vision, "read_captures",
                        lambda rutas, red, candidatos=None, contexto="": (posts_por_captura, None))
    monkeypatch.setattr(run.store, "write_snapshot",
                        lambda payload, generado_en: escritos.append(payload) or True)
    monkeypatch.setattr(run.browser, "esperar_aleatorio", lambda rango: None)
    monkeypatch.setattr(run, "_limpiar_corridas_viejas", lambda conservar: None)
    monkeypatch.setattr(run, "DIR_CAPTURAS", tmp_path / "capturas")
    # Aislar SIEMPRE el directorio de resultados: si no, los tests escriben JSON de
    # corridas falsas en scraper_local/logs/resultados y el operador podría
    # reintentar redes que nunca se corrieron.
    monkeypatch.setattr(run, "DIR_RESULTADOS", tmp_path / "resultados")


def test_correr_feliz_sube_snapshot_deduplicado(monkeypatch, tmp_path):
    escritos = []
    # La misma captura para 2 candidatos -> el dedup deja 2 posts únicos.
    _preparar_correr(monkeypatch, tmp_path, [POST_MILEI, POST_RUIDO, POST_MILEI], escritos)
    rc = run.correr(_cfg(candidatos=["Javier Milei", "Axel Kicillof"]), dry_run=False)
    assert rc == 0
    assert len(escritos) == 1
    meta = escritos[0]["meta"]
    assert meta["total_posts"] == 2      # 6 crudos (3x2) -> 2 únicos
    assert meta["posts_electorales"] == 1
    assert escritos[0]["candidatos"][0]["nombre"] == "Javier Milei"


def test_correr_sin_electorales_no_pisa_snapshot(monkeypatch, tmp_path):
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, [POST_RUIDO], escritos)
    rc = run.correr(_cfg(candidatos=["Javier Milei"]), dry_run=False)
    assert rc == 1 and escritos == []


def test_correr_dry_run_no_sube(monkeypatch, tmp_path, capsys):
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, [POST_MILEI], escritos)
    rc = run.correr(_cfg(candidatos=["Javier Milei"]), dry_run=True)
    assert rc == 0 and escritos == []
    assert "posts_electorales" in capsys.readouterr().out


def test_correr_falla_subida_devuelve_1(monkeypatch, tmp_path):
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, [POST_MILEI], escritos)
    monkeypatch.setattr(run.store, "write_snapshot", lambda payload, generado_en: False)
    rc = run.correr(_cfg(candidatos=["Javier Milei"]), dry_run=False)
    assert rc == 1


def test_correr_lectura_fallida_cuenta_error(monkeypatch, tmp_path):
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, None, escritos)  # vision devuelve None (upstream)
    rc = run.correr(_cfg(candidatos=["Javier Milei"]), dry_run=False)
    assert rc == 1  # sin posts electorales -> no pisa
    assert escritos == []


def test_capturar_candidato_error_inesperado_no_quema_ni_aborta(tmp_path, monkeypatch):
    """Un crash de Playwright (no SesionInvalidaError) devuelve [] con warning,
    sin marcar la cuenta como quemada."""
    pool = {"cuentas": [{"alias": "a", "estado": "activa", "ultima_vez": "", "notas": ""}]}
    def explota(sesion, termino, cfg, cfg_red, carpeta, prefijo, warnings):
        raise RuntimeError("chromium se murió")
    monkeypatch.setattr(twitter, "capturar", explota)
    warnings = []
    capturas = run.capturar_candidato("twitter", _cfg(), pool, "Javier Milei", tmp_path, warnings)
    assert capturas == []
    assert pool["cuentas"][0]["estado"] == "activa"  # NO quemada
    assert any("error del navegador" in w for w in warnings)


def test_correr_pasa_candidatos_a_vision(monkeypatch, tmp_path):
    """El prompt de visión recibe la lista de candidatos del config."""
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, [POST_MILEI], escritos)
    vistos = []
    monkeypatch.setattr(run.vision, "read_captures",
                        lambda rutas, red, candidatos=None, contexto="": vistos.append(candidatos) or ([POST_MILEI], None))
    run.correr(_cfg(candidatos=["Solo Uno"]), dry_run=False)
    assert vistos and vistos[0] == ["Solo Uno"]


def test_correr_multi_red_arma_un_bloque_por_red(monkeypatch, tmp_path):
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, [POST_MILEI], escritos)
    # vision devuelve el post según la red que se está capturando:
    monkeypatch.setattr(run.vision, "read_captures",
                        lambda rutas, red, candidatos=None, contexto="":
                        ([POST_MILEI], None) if red == "twitter" else ([POST_TIKTOK], None))
    cfg = _cfg(candidatos=["Javier Milei"])
    cfg["redes"] = {"twitter": {"scrolls_por_candidato": 3},
                    "tiktok": {"scrolls_por_candidato": 3, "videos_comentarios": 2,
                               "scrolls_comentarios": 2, "candidatos_comentarios": []}}
    rc = run.correr(cfg, dry_run=False)
    assert rc == 0 and len(escritos) == 1
    assert [b["red"] for b in escritos[0]["meta"]["bloques"]] == ["twitter", "tiktok"]
    assert escritos[0]["candidatos"][0]["por_red"] == {"twitter": 1, "tiktok": 1}


def test_correr_agrupa_capturas_de_un_candidato_en_una_llamada(monkeypatch, tmp_path):
    """Varias capturas de un candidato con el mismo contexto se leen en UNA sola
    llamada a read_captures (ahorro de cuota de Gemini)."""
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, [POST_MILEI], escritos)
    monkeypatch.setattr(run, "capturar_candidato",
                        lambda red_nombre, cfg, pool, cand, carpeta, warnings, estado_red=None: [
                            {"ruta": tmp_path / f"{cand}-1.png", "contexto": ""},
                            {"ruta": tmp_path / f"{cand}-2.png", "contexto": ""},
                            {"ruta": tmp_path / f"{cand}-3.png", "contexto": ""}])
    llamadas = []
    monkeypatch.setattr(run.vision, "read_captures",
                        lambda rutas, red, candidatos=None, contexto="":
                        llamadas.append(list(rutas)) or ([POST_MILEI], None))
    run.correr(_cfg(candidatos=["Javier Milei"]), dry_run=False)
    assert len(llamadas) == 1       # 3 capturas -> 1 sola llamada
    assert len(llamadas[0]) == 3    # con las 3 imágenes juntas


def test_correr_cuenta_errores_de_cuota_por_red(monkeypatch, tmp_path):
    """read_captures con None + status 429/503 se cuenta como error de cuota de la red,
    para que el aviso sepa que fue Gemini y no el scraping."""
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, [POST_MILEI], escritos)
    monkeypatch.setattr(run.vision, "read_captures",
                        lambda rutas, red, candidatos=None, contexto="": (None, 429))
    capturados = []
    monkeypatch.setattr(run, "_escribir_resultado", lambda r: capturados.append(r))
    run.correr(_cfg(candidatos=["Javier Milei"]), dry_run=False)
    assert capturados
    assert capturados[0]["errores_cuota_por_red"]["twitter"] >= 1


# --- Instagram ---

POST_INSTAGRAM = {
    "texto": "Milei imparable en Instagram", "autor": "@fan.ig", "fecha": "2 d",
    "red": "instagram", "es_electoral": True,
    "candidatos": [{"nombre": "Javier Milei", "postura": "a_favor", "confianza": 0.85}],
    "cita": "imparable"
}


def test_author_url_instagram():
    assert run._author_url("@fan.ig", "instagram") == "https://www.instagram.com/fan.ig/"
    assert run._author_url("Nombre Visible", "instagram") == ""


# --- Lock de instancia única ---

def test_lock_impide_segunda_instancia(tmp_path):
    """Con el lock tomado, un segundo intento sobre el mismo archivo se rechaza."""
    ruta = tmp_path / ".run.lock"
    with run.lock_de_instancia(ruta):
        with pytest.raises(run.InstanciaActivaError):
            with run.lock_de_instancia(ruta):
                pass


def test_lock_se_libera_al_salir(tmp_path):
    """Al salir del context (o si el proceso muere) el lock queda libre para otra corrida."""
    ruta = tmp_path / ".run.lock"
    with run.lock_de_instancia(ruta):
        pass
    with run.lock_de_instancia(ruta):  # no debe lanzar
        pass


def test_main_rechaza_si_ya_hay_corrida(tmp_path, monkeypatch):
    """main() no corre el scraper y devuelve código != 0 si el lock está tomado."""
    monkeypatch.setattr(run, "LOCK_PATH", tmp_path / ".run.lock")
    monkeypatch.setattr(run, "DIR_LOGS", tmp_path / "logs")
    corrio = []
    monkeypatch.setattr(run, "correr", lambda cfg, dry_run=False: corrio.append(True) or 0)
    with run.lock_de_instancia(tmp_path / ".run.lock"):
        rc = run.main(["--dry-run", "--redes", "twitter"])
    assert rc != 0
    assert corrio == []  # nunca ejecutó la corrida


def test_correr_multi_red_tres_bloques(monkeypatch, tmp_path):
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, [POST_MILEI], escritos)
    monkeypatch.setattr(
        run.vision, "read_captures",
        lambda rutas, red, candidatos=None, contexto="": ({
            "twitter": [POST_MILEI],
            "tiktok": [POST_TIKTOK],
            "instagram": [POST_INSTAGRAM],
        }.get(red, []), None))
    cfg = _cfg(candidatos=["Javier Milei"])
    cfg["redes"] = {
        "twitter": {"scrolls_por_candidato": 3},
        "tiktok": {"scrolls_por_candidato": 3, "videos_comentarios": 2,
                   "scrolls_comentarios": 2, "candidatos_comentarios": []},
        "instagram": {"scrolls_por_candidato": 1, "posts_por_candidato": 3,
                      "candidatos_posts": ["Javier Milei"]},
    }
    rc = run.correr(cfg, dry_run=False)
    assert rc == 0 and len(escritos) == 1
    assert [b["red"] for b in escritos[0]["meta"]["bloques"]] == ["twitter", "tiktok", "instagram"]
    assert escritos[0]["candidatos"][0]["por_red"] == {"twitter": 1, "tiktok": 1, "instagram": 1}


def test_armar_resultado_sano_es_ok():
    r = run._armar_resultado("20261013-1903", ["twitter", "tiktok", "instagram"],
                             exit_code=0, posts_por_red={"twitter": 116, "tiktok": 319,
                             "instagram": 47}, warnings_finales=["x", "y"],
                             posts_electorales=332, umbral_warnings=8)
    assert r["nivel"] == "ok" and r["mensaje"] == "" and r["runid"] == "20261013-1903"
    assert r["warnings_total"] == 2 and r["cuentas_quemadas"] == []
    assert r["fin_utc"].endswith("+00:00")


def test_armar_resultado_tiktok_cero_es_alerta():
    r = run._armar_resultado("20261007-1900", ["twitter", "tiktok", "instagram"],
                             exit_code=0, posts_por_red={"twitter": 79, "tiktok": 0,
                             "instagram": 38}, warnings_finales=["a"] * 19,
                             posts_electorales=78, umbral_warnings=8)
    assert r["nivel"] == "alerta" and "tiktok" in r["mensaje"]


def test_armar_resultado_detecta_cuenta_quemada():
    r = run._armar_resultado("20261005-1900", ["twitter"], exit_code=0,
                             posts_por_red={"twitter": 90},
                             warnings_finales=["[twitter] Cuenta 'cuenta1' marcada como quemada."],
                             posts_electorales=90, umbral_warnings=8)
    assert r["cuentas_quemadas"] == ["[twitter] Cuenta 'cuenta1' marcada como quemada."]
    assert r["nivel"] == "alerta"


def test_escribir_resultado_crea_json_y_poda(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "DIR_RESULTADOS", tmp_path / "resultados")
    for i in range(63):
        run._escribir_resultado({"runid": f"202610{i:02d}-1200", "nivel": "ok"})
    quedan = sorted((tmp_path / "resultados").glob("*.json"))
    assert len(quedan) == 60  # podó las 3 más viejas
    assert (tmp_path / "resultados" / "20261062-1200.json").exists()


def test_correr_feliz_escribe_resultado_ok(monkeypatch, tmp_path):
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, [POST_MILEI], escritos)
    monkeypatch.setattr(run, "DIR_RESULTADOS", tmp_path / "resultados")
    run.correr(_cfg(candidatos=["Javier Milei"]), dry_run=False)
    jsons = list((tmp_path / "resultados").glob("*.json"))
    assert len(jsons) == 1
    data = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert data["exit_code"] == 0 and data["nivel"] == "ok"
    assert data["posts_por_red"]["twitter"] >= 1


def test_correr_dry_run_no_escribe_resultado(monkeypatch, tmp_path):
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, [POST_MILEI], escritos)
    monkeypatch.setattr(run, "DIR_RESULTADOS", tmp_path / "resultados")
    run.correr(_cfg(candidatos=["Javier Milei"]), dry_run=True)
    assert not (tmp_path / "resultados").exists()


def test_correr_falla_subida_escribe_alerta(monkeypatch, tmp_path):
    escritos = []
    _preparar_correr(monkeypatch, tmp_path, [POST_MILEI], escritos)
    monkeypatch.setattr(run, "DIR_RESULTADOS", tmp_path / "resultados")
    monkeypatch.setattr(run.store, "write_snapshot", lambda payload, generado_en: False)
    rc = run.correr(_cfg(candidatos=["Javier Milei"]), dry_run=False)
    assert rc == 1
    data = json.loads(next((tmp_path / "resultados").glob("*.json")).read_text(encoding="utf-8"))
    assert data["exit_code"] == 1 and data["nivel"] == "alerta"


def test_umbral_de_default_y_config():
    assert run._umbral_de({}) == 8
    assert run._umbral_de({"alertas": {"umbral_warnings": 4}}) == 4
    assert run._umbral_de({"alertas": {}}) == 8
    assert run._umbral_de({"alertas": 8}) == 8       # malformado -> default, no crash
    assert run._umbral_de({"alertas": None}) == 8


# --- Resultado por red (ok / parcial / fallido) ---

def _cfg_redes(redes: dict, **over):
    cfg = _cfg(**over)
    cfg["redes"] = redes
    return cfg


def _preparar_correr_por_red(monkeypatch, tmp_path, capturar_fn, vision_fn, escritos):
    """Como _preparar_correr pero dejando capturar/vision a medida del test."""
    pool = {"cuentas": [{"alias": "a", "estado": "activa", "ultima_vez": "", "notas": ""}]}
    monkeypatch.setattr(run.accounts, "cargar_pool", lambda ruta=None, red="twitter": pool)
    monkeypatch.setattr(run.accounts, "guardar_pool", lambda p, ruta=None, red="twitter": None)
    monkeypatch.setattr(run, "capturar_candidato", capturar_fn)
    monkeypatch.setattr(run.vision, "read_captures", vision_fn)
    monkeypatch.setattr(run.store, "write_snapshot",
                        lambda payload, generado_en: escritos.append(payload) or True)
    monkeypatch.setattr(run.browser, "esperar_aleatorio", lambda rango: None)
    monkeypatch.setattr(run, "_limpiar_corridas_viejas", lambda conservar: None)
    monkeypatch.setattr(run, "DIR_CAPTURAS", tmp_path / "capturas")
    monkeypatch.setattr(run, "DIR_RESULTADOS", tmp_path / "resultados")


def _leer_unico_resultado(tmp_path):
    jsons = sorted((tmp_path / "resultados").glob("*.json"))
    assert len(jsons) == 1
    return json.loads(jsons[0].read_text(encoding="utf-8"))


def test_clasificar_resultado_red_tres_estados():
    assert run.clasificar_resultado_red(10, 2, [], []) == run.RESULTADO_OK
    assert run.clasificar_resultado_red(10, 2, ["B"], []) == run.RESULTADO_PARCIAL
    assert run.clasificar_resultado_red(10, 2, [], ["B"]) == run.RESULTADO_PARCIAL
    assert run.clasificar_resultado_red(0, 3, [], []) == run.RESULTADO_FALLIDO
    # Sin candidatos en alcance NO es éxito: no se capturó nada.
    assert run.clasificar_resultado_red(0, 0, [], []) == run.RESULTADO_FALLIDO


def test_candidatos_de_red_instagram_usa_solo_los_punteros_configurados():
    """Instagram abre sólo los perfiles de `candidatos_posts`: esos son sus
    candidatos; el resto de la lista global ni se navega y no cuenta como salteado."""
    cfg = _cfg_redes(
        {"twitter": {"scrolls_por_candidato": 3},
         "instagram": {"scrolls_por_candidato": 1,
                       "candidatos_posts": ["Javier Milei", "Axel Kicillof"]}},
        candidatos=["Javier Milei", "Axel Kicillof", "Sergio Massa"])
    assert run.candidatos_de_red(cfg, "instagram") == ["Javier Milei", "Axel Kicillof"]
    assert run.candidatos_de_red(cfg, "twitter") == ["Javier Milei", "Axel Kicillof",
                                                     "Sergio Massa"]
    cfg["redes"]["instagram"]["candidatos_posts"] = []
    assert run.candidatos_de_red(cfg, "instagram") == []


def test_candidatos_globales_respeta_lista_explicita_vacia():
    # `candidatos: []` significa "esta corrida no busca a nadie" (no la default).
    assert run._candidatos_globales({"candidatos": []}) == []
    assert len(run._candidatos_globales({"candidatos": None})) > 0


def test_red_con_capturas_pero_sin_posts_es_fallida(monkeypatch, tmp_path):
    """Capturó pero la visión no vio ninguna publicación -> sin post usable: fallida."""
    escritos = []
    _preparar_correr_por_red(
        monkeypatch, tmp_path,
        capturar_fn=lambda red, cfg, pool, cand, carpeta, warnings, estado_red=None: [
            {"ruta": tmp_path / f"{red}-{cand}.png", "contexto": ""}],
        vision_fn=lambda rutas, red, candidatos=None, contexto="": ([], None),
        escritos=escritos)
    run.correr(_cfg_redes({"twitter": {"scrolls_por_candidato": 3}},
                          candidatos=["Javier Milei"]), dry_run=False)
    reg = _leer_unico_resultado(tmp_path)["resultados_por_red"]["twitter"]
    assert reg["resultado"] == run.RESULTADO_FALLIDO
    assert reg["candidatos"] == 1 and reg["posts"] == 0
    assert reg["candidatos_salteados"] == []  # sí se capturó; lo que faltó fueron posts


def test_instagram_cuenta_como_candidatos_solo_los_punteros(monkeypatch, tmp_path):
    escritos = []
    _preparar_correr_por_red(
        monkeypatch, tmp_path,
        capturar_fn=lambda red, cfg, pool, cand, carpeta, warnings, estado_red=None: [
            {"ruta": tmp_path / f"{red}-{cand}.png", "contexto": ""}],
        vision_fn=lambda rutas, red, candidatos=None, contexto="": ([POST_INSTAGRAM], None),
        escritos=escritos)
    cfg = _cfg_redes(
        {"instagram": {"scrolls_por_candidato": 1,
                       "candidatos_posts": ["Javier Milei", "Axel Kicillof"]}},
        candidatos=["Javier Milei", "Axel Kicillof", "Sergio Massa", "Mauricio Macri"])
    run.correr(cfg, dry_run=False)
    reg = _leer_unico_resultado(tmp_path)["resultados_por_red"]["instagram"]
    assert reg["candidatos"] == 2   # sólo los punteros, no los 4 de la lista global
    assert reg["resultado"] == run.RESULTADO_OK


def test_red_sin_candidatos_no_se_reporta_como_ok(monkeypatch, tmp_path):
    """Una red que no tenía a quién buscar no puede figurar como éxito (regla del
    requisito): se reporta fallida con candidatos=0 y posts=0."""
    escritos = []
    _preparar_correr_por_red(
        monkeypatch, tmp_path,
        capturar_fn=lambda red, cfg, pool, cand, carpeta, warnings, estado_red=None: [
            {"ruta": tmp_path / f"{red}-{cand}.png", "contexto": ""}],
        vision_fn=lambda rutas, red, candidatos=None, contexto="": ([POST_MILEI], None),
        escritos=escritos)
    cfg = _cfg_redes({"twitter": {"scrolls_por_candidato": 3}}, candidatos=[])
    rc = run.correr(cfg, dry_run=False)
    assert rc == 1  # sin posts -> no pisa el snapshot
    data = _leer_unico_resultado(tmp_path)
    reg = data["resultados_por_red"]["twitter"]
    assert reg["resultado"] == run.RESULTADO_FALLIDO
    assert reg["candidatos"] == 0 and reg["posts"] == 0


def test_red_todos_candidatos_salteados_es_fallida(monkeypatch, tmp_path):
    """Todos los candidatos de la red quedan sin capturar -> red fallida, con la
    lista de salteados y 0 posts."""
    escritos = []
    _preparar_correr_por_red(
        monkeypatch, tmp_path,
        capturar_fn=lambda red, cfg, pool, cand, carpeta, warnings, estado_red=None: [],
        vision_fn=lambda rutas, red, candidatos=None, contexto="": ([POST_MILEI], None),
        escritos=escritos)
    cfg = _cfg_redes({"twitter": {"scrolls_por_candidato": 3}},
                     candidatos=["Javier Milei", "Axel Kicillof"])
    rc = run.correr(cfg, dry_run=False)
    assert rc == 1  # sin posts
    data = _leer_unico_resultado(tmp_path)
    reg = data["resultados_por_red"]["twitter"]
    assert reg["resultado"] == run.RESULTADO_FALLIDO
    assert reg["candidatos"] == 2 and reg["posts"] == 0
    assert reg["candidatos_salteados"] == ["Javier Milei", "Axel Kicillof"]
    assert reg["candidatos_con_problemas"] == ["Javier Milei", "Axel Kicillof"]


def test_red_con_parte_ok_y_parte_salteada_es_parcial(monkeypatch, tmp_path):
    """Un candidato capturó y otro fue salteado -> la red es parcial (no fallida),
    con sus números y el nombre del salteado."""
    escritos = []
    def capturar(red, cfg, pool, cand, carpeta, warnings, estado_red=None):
        if cand == "Axel Kicillof":
            return []
        return [{"ruta": tmp_path / f"{red}-{cand}.png", "contexto": ""}]
    _preparar_correr_por_red(
        monkeypatch, tmp_path, capturar_fn=capturar,
        vision_fn=lambda rutas, red, candidatos=None, contexto="": ([POST_MILEI], None),
        escritos=escritos)
    cfg = _cfg_redes({"twitter": {"scrolls_por_candidato": 3}},
                     candidatos=["Javier Milei", "Axel Kicillof"])
    rc = run.correr(cfg, dry_run=False)
    assert rc == 0  # hay posts: la corrida global no falla por esto
    data = _leer_unico_resultado(tmp_path)
    reg = data["resultados_por_red"]["twitter"]
    assert reg["resultado"] == run.RESULTADO_PARCIAL
    assert reg["candidatos"] == 2 and reg["posts"] >= 1
    assert reg["candidatos_salteados"] == ["Axel Kicillof"]
    assert reg["candidatos_lectura_fallida"] == []


def test_red_con_lectura_fallida_es_parcial(monkeypatch, tmp_path):
    """Capturas tomadas pero Gemini no las pudo leer -> parcial, con el candidato
    en candidatos_lectura_fallida."""
    escritos = []
    def vision(rutas, red, candidatos=None, contexto=""):
        if "Kicillof" in str(rutas[0]):
            return None, 429
        return [POST_MILEI], None
    _preparar_correr_por_red(
        monkeypatch, tmp_path,
        capturar_fn=lambda red, cfg, pool, cand, carpeta, warnings, estado_red=None: [
            {"ruta": tmp_path / f"{red}-{cand}.png", "contexto": ""}],
        vision_fn=vision, escritos=escritos)
    cfg = _cfg_redes({"twitter": {"scrolls_por_candidato": 3}},
                     candidatos=["Javier Milei", "Axel Kicillof"])
    run.correr(cfg, dry_run=False)
    reg = _leer_unico_resultado(tmp_path)["resultados_por_red"]["twitter"]
    assert reg["resultado"] == run.RESULTADO_PARCIAL
    assert reg["candidatos_salteados"] == []
    assert reg["candidatos_lectura_fallida"] == ["Axel Kicillof"]
    assert reg["errores_cuota"] >= 1


def test_resultado_por_red_conserva_campos_viejos(monkeypatch, tmp_path):
    """El campo nuevo no cambia la forma de los campos que ya consumía el aviso."""
    escritos = []
    _preparar_correr_por_red(
        monkeypatch, tmp_path,
        capturar_fn=lambda red, cfg, pool, cand, carpeta, warnings, estado_red=None: [
            {"ruta": tmp_path / f"{red}-{cand}.png", "contexto": ""}],
        vision_fn=lambda rutas, red, candidatos=None, contexto="": ([POST_MILEI], None),
        escritos=escritos)
    run.correr(_cfg_redes({"twitter": {"scrolls_por_candidato": 3}},
                          candidatos=["Javier Milei"]), dry_run=False)
    data = _leer_unico_resultado(tmp_path)
    for campo in ("runid", "fin_utc", "redes", "exit_code", "posts_por_red",
                  "warnings_total", "cuentas_quemadas", "posts_electorales"):
        assert campo in data
    assert data["redes"] == ["twitter"]
    assert data["resultados_por_red"]["twitter"]["resultado"] == run.RESULTADO_OK
    assert data["reintento_de"] == ""


# --- --reintentar-fallidas ---

def _escribir_resultado_viejo(tmp_path, runid, resultados, redes=None):
    monkeypatch_dir = tmp_path / "resultados"
    monkeypatch_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "runid": runid,
        "fin_utc": "2026-10-14T19:00:00+00:00",
        "redes": list(redes or resultados.keys()),
        "exit_code": 0,
        "posts_por_red": {r: v.get("posts", 0) for r, v in resultados.items()},
        "warnings_total": 0, "cuentas_quemadas": [], "posts_electorales": 1,
        "resultados_por_red": resultados,
        "nivel": "ok", "titulo": "", "mensaje": "",
    }
    (monkeypatch_dir / f"{runid}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _preparar_main(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "DIR_LOGS", tmp_path / "logs")
    monkeypatch.setattr(run, "DIR_RESULTADOS", tmp_path / "resultados")
    monkeypatch.setattr(run, "LOCK_PATH", tmp_path / ".run.lock")
    corridas = []
    monkeypatch.setattr(run, "correr",
                        lambda cfg, dry_run=False:
                        corridas.append((cfg, dry_run, cfg.get("_reintento_de", ""))) or 0)
    return corridas


def test_reintentar_sin_resultado_previo_no_scrapea_y_sale_noncero(monkeypatch, tmp_path):
    corridas = _preparar_main(monkeypatch, tmp_path)
    rc = run.main(["--reintentar-fallidas"])
    assert rc != 0
    assert corridas == []  # no arrancó scraping


def test_reintentar_sin_redes_fallidas_no_scrapea_y_sale_noncero(monkeypatch, tmp_path, capsys):
    corridas = _preparar_main(monkeypatch, tmp_path)
    _escribir_resultado_viejo(tmp_path, "20261014-1600", {
        "twitter": {"red": "twitter", "resultado": run.RESULTADO_OK,
                    "candidatos": 1, "posts": 10},
        "tiktok": {"red": "tiktok", "resultado": run.RESULTADO_OK,
                   "candidatos": 1, "posts": 20},
    })
    rc = run.main(["--reintentar-fallidas"])
    assert rc != 0
    assert corridas == []  # nada que reintentar -> no corre
    salida = capsys.readouterr()
    assert "reintentar" in (salida.err + salida.out).lower()


def test_reintentar_dry_run_no_crea_resultado_y_no_es_reintentable(monkeypatch, tmp_path, capsys):
    """Un --dry-run nunca escribe resultado: tras una prueba en seco no hay 'última
    corrida' para reintentar, así que el flag avisa y sale non-cero."""
    escritos = []
    _preparar_correr_por_red(
        monkeypatch, tmp_path,
        capturar_fn=lambda red, cfg, pool, cand, carpeta, warnings, estado_red=None: [
            {"ruta": tmp_path / f"{red}-{cand}.png", "contexto": ""}],
        vision_fn=lambda rutas, red, candidatos=None, contexto="": ([POST_MILEI], None),
        escritos=escritos)
    run.correr(_cfg_redes({"twitter": {"scrolls_por_candidato": 3}},
                          candidatos=["Javier Milei"]), dry_run=True)
    assert not (tmp_path / "resultados").exists()
    corridas = _preparar_main(monkeypatch, tmp_path)
    rc = run.main(["--reintentar-fallidas"])
    assert rc != 0 and corridas == []


def test_reintentar_corre_solo_las_redes_no_ok(monkeypatch, tmp_path):
    """Con resultados mixtos, el flag corre SÓLO las redes parcial/fallidas, no las ok."""
    corridas = _preparar_main(monkeypatch, tmp_path)
    _escribir_resultado_viejo(tmp_path, "20261014-1600", {
        "twitter": {"red": "twitter", "resultado": run.RESULTADO_OK,
                    "candidatos": 2, "posts": 50},
        "tiktok": {"red": "tiktok", "resultado": run.RESULTADO_FALLIDO,
                   "candidatos": 2, "posts": 0},
        "instagram": {"red": "instagram", "resultado": run.RESULTADO_PARCIAL,
                      "candidatos": 3, "posts": 4},
    })
    rc = run.main(["--reintentar-fallidas"])
    assert rc == 0
    assert len(corridas) == 1
    cfg, dry_run, reintento_de = corridas[0]
    assert list(cfg["redes"]) == ["tiktok", "instagram"]  # twitter (ok) queda afuera
    assert dry_run is False
    assert reintento_de == "20261014-1600"


def test_reintentar_acepta_lista_de_redes_para_acotar(monkeypatch, tmp_path):
    corridas = _preparar_main(monkeypatch, tmp_path)
    _escribir_resultado_viejo(tmp_path, "20261014-1600", {
        "tiktok": {"red": "tiktok", "resultado": run.RESULTADO_FALLIDO,
                   "candidatos": 2, "posts": 0},
        "instagram": {"red": "instagram", "resultado": run.RESULTADO_PARCIAL,
                      "candidatos": 3, "posts": 4},
    })
    rc = run.main(["--reintentar-fallidas", "instagram"])
    assert rc == 0 and len(corridas) == 1
    assert list(corridas[0][0]["redes"]) == ["instagram"]


def test_reintentar_ignora_redes_ok_aunque_se_pidan(monkeypatch, tmp_path):
    """Pedir por nombre una red que salió ok no la corre: el flag sólo reintenta fallas."""
    corridas = _preparar_main(monkeypatch, tmp_path)
    _escribir_resultado_viejo(tmp_path, "20261014-1600", {
        "twitter": {"red": "twitter", "resultado": run.RESULTADO_OK,
                    "candidatos": 1, "posts": 30},
    })
    rc = run.main(["--reintentar-fallidas", "twitter"])
    assert rc != 0 and corridas == []


def test_reintentar_dry_run_pasa_dry_run_y_no_corre_normal(monkeypatch, tmp_path):
    corridas = _preparar_main(monkeypatch, tmp_path)
    _escribir_resultado_viejo(tmp_path, "20261014-1600", {
        "tiktok": {"red": "tiktok", "resultado": run.RESULTADO_FALLIDO,
                   "candidatos": 1, "posts": 0},
    })
    rc = run.main(["--reintentar-fallidas", "--dry-run"])
    assert rc == 0 and len(corridas) == 1
    assert corridas[0][1] is True           # dry-run se respeta
    assert list(corridas[0][0]["redes"]) == ["tiktok"]


def test_redes_fallidas_soporta_resultado_legacy_sin_detalle():
    """Un JSON viejo (sin resultados_por_red) sólo deja concluir el 0 de posts_por_red."""
    legacy = {"redes": ["twitter", "tiktok"], "posts_por_red": {"twitter": 10, "tiktok": 0}}
    assert run.redes_fallidas(legacy) == ["tiktok"]


def test_redes_fallidas_no_omite_red_ausente_de_la_lista_redes():
    """Si el JSON es inconsistente (una red fallida no figura en `redes`), igual se
    detecta: un resultado parcial no debe quedar escondido."""
    data = {"redes": ["twitter"],
            "posts_por_red": {"twitter": 10, "tiktok": 0},
            "resultados_por_red": {"twitter": {"resultado": "ok"},
                                   "tiktok": {"resultado": "fallido"}}}
    assert run.redes_fallidas(data) == ["tiktok"]


def test_alcance_reintento_interseccion_y_none():
    assert run.alcance_reintento("", None) is None                 # sin acotar
    assert run.alcance_reintento("", "") is None
    assert run.alcance_reintento("tiktok,instagram", None) == ["instagram", "tiktok"]
    # Flag y --redes se INTERSECTAN: ninguno puede ampliar lo que el otro pidió.
    assert run.alcance_reintento("tiktok,instagram", "instagram,twitter") == ["instagram"]
    assert run.alcance_reintento("tiktok", "instagram") == []


def test_reintentar_con_redes_ok_pedidas_no_las_corre(monkeypatch, tmp_path):
    """--redes no puede ampliar el alcance del reintento a una red que salió ok."""
    corridas = _preparar_main(monkeypatch, tmp_path)
    _escribir_resultado_viejo(tmp_path, "20261014-1600", {
        "twitter": {"red": "twitter", "resultado": run.RESULTADO_OK,
                    "candidatos": 1, "posts": 30},
        "tiktok": {"red": "tiktok", "resultado": run.RESULTADO_FALLIDO,
                   "candidatos": 1, "posts": 0},
    })
    rc = run.main(["--reintentar-fallidas", "tiktok", "--redes", "twitter"])
    assert rc != 0 and corridas == []  # intersección vacía -> nada que reintentar


def test_reintentar_saltea_json_corrupto_y_usa_uno_valido(monkeypatch, tmp_path):
    corridas = _preparar_main(monkeypatch, tmp_path)
    (tmp_path / "resultados").mkdir(parents=True, exist_ok=True)
    (tmp_path / "resultados" / "20261015-1000.json").write_text("{cortado", encoding="utf-8")
    _escribir_resultado_viejo(tmp_path, "20261014-1600", {
        "tiktok": {"red": "tiktok", "resultado": run.RESULTADO_FALLIDO,
                   "candidatos": 1, "posts": 0},
    })
    rc = run.main(["--reintentar-fallidas"])
    assert rc == 0 and len(corridas) == 1
    assert list(corridas[0][0]["redes"]) == ["tiktok"]
    assert corridas[0][2] == "20261014-1600"


def test_reintentar_omite_red_fallida_que_ya_no_esta_en_config(monkeypatch, tmp_path):
    """Si la red fallida ya no está en el config, se omite y se corre lo que sí está."""
    corridas = _preparar_main(monkeypatch, tmp_path)
    _escribir_resultado_viejo(tmp_path, "20261014-1600", {
        "tiktok": {"red": "tiktok", "resultado": run.RESULTADO_FALLIDO,
                   "candidatos": 1, "posts": 0},
        "myspace": {"red": "myspace", "resultado": run.RESULTADO_FALLIDO,
                    "candidatos": 1, "posts": 0},
    })
    rc = run.main(["--reintentar-fallidas"])
    assert rc == 0 and len(corridas) == 1
    assert list(corridas[0][0]["redes"]) == ["tiktok"]


def test_crash_registra_todas_las_redes_como_fallidas(monkeypatch, tmp_path):
    """Una corrida que crashea no puede declarar ninguna red sana: el JSON de resultado
    deja todas las redes configuradas en `fallido` (y así son reintentables)."""
    monkeypatch.setattr(run, "DIR_LOGS", tmp_path / "logs")
    monkeypatch.setattr(run, "DIR_RESULTADOS", tmp_path / "resultados")
    monkeypatch.setattr(run, "LOCK_PATH", tmp_path / ".run.lock")
    cfg_fija = _cfg_redes({
        "twitter": {"scrolls_por_candidato": 3},
        "tiktok": {"scrolls_por_candidato": 3},
    }, candidatos=["Javier Milei"])
    monkeypatch.setattr(run, "cargar_config", lambda ruta=None: cfg_fija)

    def explota(cfg, dry_run=False, reintento_de=""):
        raise RuntimeError("chromium se murió")

    monkeypatch.setattr(run, "correr", explota)
    rc = run.main(["--redes", "twitter,tiktok"])
    assert rc == 1
    jsons = list((tmp_path / "resultados").glob("*.json"))
    assert len(jsons) == 1
    data = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert data["resultados_por_red"]["twitter"]["resultado"] == run.RESULTADO_FALLIDO
    assert data["resultados_por_red"]["tiktok"]["resultado"] == run.RESULTADO_FALLIDO
    assert run.redes_fallidas(data) == ["twitter", "tiktok"]


def test_correr_registra_reintento_de(monkeypatch, tmp_path):
    """Una corrida de reintento deja el runid de origen en su propio resultado."""
    escritos = []
    _preparar_correr_por_red(
        monkeypatch, tmp_path,
        capturar_fn=lambda red, cfg, pool, cand, carpeta, warnings, estado_red=None: [
            {"ruta": tmp_path / f"{red}-{cand}.png", "contexto": ""}],
        vision_fn=lambda rutas, red, candidatos=None, contexto="": ([POST_MILEI], None),
        escritos=escritos)
    cfg = _cfg_redes({"twitter": {"scrolls_por_candidato": 3}},
                     candidatos=["Javier Milei"])
    cfg["_reintento_de"] = "20261014-1600"
    run.correr(cfg, dry_run=False)
    assert _leer_unico_resultado(tmp_path)["reintento_de"] == "20261014-1600"


