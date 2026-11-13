import os
import sys
from html import escape

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, session

# Permite importar el paquete src/ (core de dominio compartido con la app de
# consola) cuando este archivo corre como función serverless en Vercel.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.core.data_manager import RetroAchievementsDataManager
from src.core.link_checker import is_download_url_reachable, is_hash_recognized_by_ra
from src.core.retroachievements_api import RetroAchievementsAPIError, RetroAchievementsClient
from src.core.rom_info import analyze_rom_info, extract_game_name, get_console_from_rom_path
from src.factories.url_factory import URLGeneratorFactory

load_dotenv(config.ENV_FILE)

app = Flask(__name__)

# Sesión de servidor (cookie firmada, HttpOnly) para la API Key de RA de
# /api/ra/connect -- nunca queda en localStorage/JS. FLASK_SECRET_KEY *tiene*
# que ser una variable de entorno real en producción (Vercel): sin ella, la
# firma de la cookie es este valor público del código fuente y cualquiera
# podría forjar una sesión (igual queda protegida de lectura por XSS gracias
# a HttpOnly, pero no de falsificación).
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-insecure-secret-cambiar-en-produccion")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("VERCEL"))

# Ruta al archivo JSON local
JSON_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Data", "TamperMonkeyRetroachievements.json")
RA_METADATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Data", "retroachievements_metadata.json")

data_manager = RetroAchievementsDataManager(json_file_path=JSON_FILE_PATH)
cached_games_index = None  # Índice cacheado para listados
cached_ra_metadata = None  # {game_id: {id, title, image_icon, achievements}}, gen. por scripts/sync_games_metadata.py
cached_console_icons = None  # {nombre_canonico_consola: icon_url}, generado por scripts/sync_games_metadata.py


# Cargar el archivo JSON local
def load_json_file():
    return data_manager.load_data()


def load_ra_metadata():
    """Carga Data/retroachievements_metadata.json (titulos/caratulas/logros reales).
    Si no existe todavia (no se corrio scripts/sync_games_metadata.py), /games sigue
    funcionando sin esos datos."""
    global cached_ra_metadata
    if cached_ra_metadata is None:
        try:
            import json

            with open(RA_METADATA_FILE, "r", encoding="utf-8") as f:
                cached_ra_metadata = json.load(f).get("games", {})
        except (FileNotFoundError, ValueError):
            cached_ra_metadata = {}
    return cached_ra_metadata


def load_console_icons():
    """Carga el mapa de iconos por consola (mismo archivo que load_ra_metadata,
    generado por scripts/sync_games_metadata.py). Degrada a {} si no existe todavia."""
    global cached_console_icons
    if cached_console_icons is None:
        try:
            import json

            with open(RA_METADATA_FILE, "r", encoding="utf-8") as f:
                cached_console_icons = json.load(f).get("console_icons", {})
        except (FileNotFoundError, ValueError):
            cached_console_icons = {}
    return cached_console_icons


# Función para contar total de juegos en la base de datos (optimizada)
def count_total_games(json_data):
    # Simplemente contar el número de IDs únicos de juegos
    return len(json_data) if json_data else 0


# Construir índice de juegos para listados/filtrado
def build_games_index():
    global cached_games_index
    if cached_games_index is not None:
        return cached_games_index
    data = load_json_file()
    if not data:
        cached_games_index = []
        return cached_games_index
    ra_metadata = load_ra_metadata()
    games = []
    for game_id, hash_list in data.items():
        game_name = None
        consoles = set()
        total_versions = 0
        sample_rom_path = None
        for item in hash_list:
            for _hash, rom_path in item.items():
                if sample_rom_path is None:
                    sample_rom_path = rom_path
                total_versions += 1
                current_name = extract_game_name(rom_path)
                if not game_name:
                    game_name = current_name
                consoles.add(get_console_from_rom_path(rom_path))
        ra_info = ra_metadata.get(game_id)
        games.append(
            {
                "id": game_id,
                "name": game_name or f"Game {game_id}",
                "consoles": sorted(list(consoles)),
                "versions": total_versions,
                "sample_rom_path": sample_rom_path,
                "image_icon": ra_info.get("image_icon") if ra_info else None,
                "achievements": ra_info.get("achievements") if ra_info else None,
            }
        )
    games.sort(key=lambda g: (g["name"] or "").lower())
    cached_games_index = games
    return cached_games_index


# Función para buscar por hash
def find_hash_in_json(json_data, hash_value):
    return data_manager.find_hash(hash_value)


# Función para obtener la URL de descarga
def get_download_url(rom_path: str) -> str:
    return URLGeneratorFactory.generate_url(rom_path)


# Consolas disponibles y conteos (usado por /api/games)
def _console_counts(games):
    console_counts = {}
    for g in games:
        for c in g["consoles"]:
            console_counts[c] = console_counts.get(c, 0) + 1
    return sorted(console_counts.items(), key=lambda x: x[0])


def _console_list_with_icons(games):
    icons = load_console_icons()
    return [{"name": c, "count": n, "icon_url": icons.get(c)} for c, n in _console_counts(games)]


# API para obtener juegos filtrados/paginados
@app.route("/api/games")
def api_games():
    games = build_games_index()
    q = request.args.get("q", "", type=str).strip().lower()
    console = request.args.get("console", "", type=str).strip()
    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(400, max(10, request.args.get("page_size", 50, type=int)))

    filtered = games
    if console:
        c_l = console.lower()
        filtered = [g for g in filtered if any((cc or "").lower() == c_l for cc in g["consoles"])]
    if q:
        filtered = [g for g in filtered if q in (g["name"] or "").lower()]

    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size if page_size else 1
    if page > total_pages and total_pages > 0:
        page = total_pages
    start = (page - 1) * page_size
    end = start + page_size
    items = filtered[start:end]

    return {
        "success": True,
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "consoles": _console_list_with_icons(games),
    }


@app.route("/dl")
def dl_redirect():
    """Redirige al enlace de descarga a partir de un hash."""
    hash_value = request.args.get("hash", "", type=str)
    data = load_json_file()
    if not data or not hash_value:
        return "Hash no provisto o base de datos no disponible", 400
    rom_path = find_hash_in_json(data, hash_value)
    if not rom_path:
        return f"No se encontró el hash '{escape(hash_value)}'", 404
    url = get_download_url(rom_path)
    return redirect(url)


@app.route("/get_game_versions", methods=["POST"])
def get_game_versions():
    game_id = request.form.get("game_id", "")
    json_data = load_json_file()

    if json_data and game_id in json_data:
        versions = []
        for item in json_data[game_id]:
            for hash_key, rom_path in item.items():
                rom_info = analyze_rom_info(rom_path)
                versions.append({"hash": hash_key, "rom_path": rom_path, "info": rom_info})

        # Ordenar por prioridad
        versions.sort(key=lambda x: x["info"]["priority"])

        return {"success": True, "versions": versions}
    else:
        return {"success": False, "versions": []}


@app.route("/search", methods=["POST"])
def search():
    search_term = request.form["search_term"]
    json_data = load_json_file()

    if json_data:
        rom_path = find_hash_in_json(json_data, search_term)
        if rom_path:
            download_url = get_download_url(rom_path)
            return {
                "success": True,
                "download_url": download_url,
                "link_ok": is_download_url_reachable(download_url),
                "ra_recognized": is_hash_recognized_by_ra(search_term),
                "name": extract_game_name(rom_path),
                "console": get_console_from_rom_path(rom_path),
            }
        else:
            message = f"No se encontró el hash '{escape(search_term)}' en la base de datos."
            return {"success": False, "message": message}, 404
    else:
        return {"success": False, "message": "Error al cargar el archivo JSON local."}, 500


def _resolve_want_to_play(api_key: str, username: str):
    """Cruza la lista "Want to Play" de RA contra nuestro catálogo local por ID
    de juego (ambos indexados por el ID real de RA -- ver build_games_index).
    No hace falta resolver hashes/regiones acá: eso ya lo hace
    /get_game_versions una vez que se abre una card. Puede lanzar
    RetroAchievementsAPIError."""
    wtp_games = RetroAchievementsClient(api_key).get_want_to_play_list(username)
    wanted_ids = {str(g["ID"]) for g in wtp_games}
    items = [g for g in build_games_index() if g["id"] in wanted_ids]
    return items, len(items), len(wtp_games)


@app.route("/api/ra/connect", methods=["POST"])
def ra_connect():
    """Valida la API Key contra la API de RA y, si funciona, la guarda en la
    sesión del servidor (cookie firmada + HttpOnly) -- nunca en la respuesta
    ni en ningún storage del browser."""
    api_key = request.form.get("api_key", "").strip()
    username = request.form.get("username", "").strip()
    if not api_key or not username:
        return {"success": False, "message": "Falta API Key o usuario."}, 400

    try:
        # Validación: no hace falta el resultado, solo confirmar que la API
        # Key puede llamar a la API de RA. El frontend trae los conteos de
        # want_to_play y el perfil por separado apenas ve la cuenta conectada.
        RetroAchievementsClient(api_key).get_want_to_play_list(username)
    except RetroAchievementsAPIError:
        app.logger.exception("Error al conectar la cuenta de RetroAchievements.")
        return {"success": False, "message": "No pudimos conectar: revisá tu API Key y usuario."}, 502

    session["ra_api_key"] = api_key
    session["ra_username"] = username
    # No se devuelve `username`: es el mismo valor que el cliente acaba de
    # mandar, reflejarlo de vuelta no aporta nada y CodeQL lo marca como
    # posible XSS reflejado (el frontend ya lo tiene en su propio form).
    return {"success": True}


@app.route("/api/ra/disconnect", methods=["POST"])
def ra_disconnect():
    session.pop("ra_api_key", None)
    session.pop("ra_username", None)
    return {"success": True}


@app.route("/api/ra/status")
def ra_status():
    username = session.get("ra_username")
    return {"connected": username is not None, "username": username}


@app.route("/api/ra/profile")
def ra_profile():
    """Perfil público de RA (avatar, puntos, motto) de la cuenta conectada --
    separado de /api/want_to_play porque es una llamada liviana a una API de
    RA distinta (GetUserProfile) que no necesita cruzar nada contra el
    catálogo local."""
    api_key = session.get("ra_api_key")
    username = session.get("ra_username")
    if not api_key or not username:
        return {"success": False, "message": "No hay una cuenta de RetroAchievements conectada."}, 401

    try:
        profile = RetroAchievementsClient(api_key).get_user_profile(username)
    except RetroAchievementsAPIError:
        app.logger.exception("Error al consultar el perfil de RetroAchievements.")
        return {"success": False, "message": "No pudimos traer tu perfil."}, 502

    user_pic = profile.get("UserPic") or ""
    return {
        "success": True,
        "avatar_url": f"https://media.retroachievements.org{user_pic}" if user_pic else None,
        "total_points": profile.get("TotalPoints"),
        "total_true_points": profile.get("TotalTruePoints"),
        "motto": profile.get("Motto") or None,
    }


@app.route("/api/want_to_play")
def want_to_play():
    api_key = session.get("ra_api_key")
    username = session.get("ra_username")
    if not api_key or not username:
        return {"success": False, "message": "No hay una cuenta de RetroAchievements conectada."}, 401

    try:
        items, total, requested = _resolve_want_to_play(api_key, username)
    except RetroAchievementsAPIError:
        app.logger.exception("Error al consultar Want to Play en RetroAchievements.")
        return {"success": False, "message": "No pudimos traer tu lista de deseos."}, 502

    return {"success": True, "items": items, "total": total, "requested": requested}


@app.errorhandler(404)
def page_not_found(e):
    return {"success": False, "message": "Not found"}, 404


@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500


if __name__ == "__main__":
    app.run(debug=True)
