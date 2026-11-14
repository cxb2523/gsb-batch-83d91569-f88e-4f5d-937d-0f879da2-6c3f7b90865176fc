"""Decide si una corrida del scraper merece un aviso. Lógica pura, sin I/O ni UI.

El resultado lo arma run.py y lo consume aviso-matutino.ps1; acá sólo se aplica
la regla de "cuándo es alerta".
"""

TITULO = "⚠️ Boca de Urna: corrida con problemas"


def evaluar(resultado: dict, umbral_warnings: int = 8) -> dict | None:
    """Devuelve {'nivel','titulo','mensaje'} si la corrida merece alerta, o None.

    Es alerta si se cumple CUALQUIERA:
      1. exit_code no es 0 ni 2  (crash / pocos posts / subida fallida; 2 = lock, normal)
      2. alguna red corrida trajo 0 posts
      3. hubo al menos una cuenta quemada
      4. los avisos totales llegan al umbral
      5. hubo capturas sin leer por falta de cuota de Gemini (429/503)

    Distingue la causa del 0: si una red quedó en 0 por cuota de Gemini (está en
    `errores_cuota_por_red`), lo dice como problema de IA y NO como captcha/cuenta
    quemada — el scraping anduvo, lo que faltó fue la lectura.

    Si igual hay alerta y el resultado trae `resultados_por_red`, el mensaje suma
    qué redes salieron parciales y qué candidatos quedaron afuera (salteados o sin
    leer) — antes eso sólo estaba en el log. Un resultado parcial por sí solo NO
    dispara el cartel: hay configuraciones con candidatos sin perfil (Instagram)
    que quedarían avisando todos los días.
    """
    motivos: list[str] = []

    if resultado.get("exit_code") not in (0, 2):
        motivos.append("No se pudo actualizar el tablero (la corrida falló).")

    cuota = resultado.get("errores_cuota_por_red") or {}
    ceros = [red for red, n in (resultado.get("posts_por_red") or {}).items() if n == 0]
    # Los 0 causados por falta de cuota de Gemini NO son captcha/cuenta quemada.
    ceros_scraping = [r for r in ceros if cuota.get(r, 0) == 0]
    if ceros_scraping:
        motivos.append(f"Sin posts en: {', '.join(ceros_scraping)} (captcha / cuenta quemada).")

    total_cuota = sum(cuota.values())
    if total_cuota > 0:
        motivos.append(
            f"La lectura con IA (Gemini) quedó sin cuota: {total_cuota} captura(s) sin leer. "
            "El scraping anduvo; reintentá más tarde o ampliá la cuota.")

    quemadas = resultado.get("cuentas_quemadas") or []
    if quemadas:
        motivos.append(f"{len(quemadas)} cuenta(s) quemada(s) en esta corrida.")

    total_avisos = resultado.get("warnings_total") or 0
    if total_avisos >= umbral_warnings:
        motivos.append(f"{total_avisos} avisos en la corrida.")

    if not motivos:
        return None
    parciales = _redes_parciales(resultado)
    if parciales:
        motivos.append("Corrida parcial en: " + "; ".join(parciales) + ".")
    return {"nivel": "alerta", "titulo": TITULO, "mensaje": " ".join(motivos)}


def _redes_parciales(resultado: dict) -> list[str]:
    """Describe las redes con resultado `parcial`: 'tiktok (salteados: A, B)'.

    Un JSON viejo sin `resultados_por_red` no aporta este detalle y devuelve [] —
    el resto de las alertas sigue funcionando igual."""
    registros = resultado.get("resultados_por_red") or {}
    detalle: list[str] = []
    for red, reg in registros.items():
        if not isinstance(reg, dict) or reg.get("resultado") != "parcial":
            continue
        salteados = [c for c in (reg.get("candidatos_salteados") or []) if c]
        fallidas = [c for c in (reg.get("candidatos_lectura_fallida") or []) if c]
        partes = []
        if salteados:
            partes.append("salteados: " + ", ".join(salteados))
        if fallidas:
            partes.append("sin leer: " + ", ".join(fallidas))
        detalle.append(f"{red} ({'; '.join(partes)})" if partes else red)
    return detalle
