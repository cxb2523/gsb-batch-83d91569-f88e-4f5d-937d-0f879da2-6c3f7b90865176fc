# Configuración para RetroAchievements Downloader

import os

# Rutas absolutas ancladas a la raíz del repo (donde vive este archivo), no al
# directorio de trabajo actual: así funcionan igual si se corre `python
# console/main.py` desde la raíz o `python main.py` parado dentro de console/.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

## Rutas de archivos
JSON_FILE_PATH = os.path.join(_BASE_DIR, "Data", "TamperMonkeyRetroachievements.json")
WANT_TO_PLAY_FILE = os.path.join(_BASE_DIR, "game_hashes.json")
MISSING_GAMES_FILE = os.path.join(_BASE_DIR, "missing_games.txt")
ENV_FILE = os.path.join(_BASE_DIR, ".env")
ENV_EXAMPLE_FILE = os.path.join(_BASE_DIR, "ejemplo.env")

## Preferencias de región (orden de prioridad)
PREFERRED_REGIONS = {
    "ES": 1,  # Español tiene la mayor prioridad
    "USA": 2,  # Luego USA
    "WORLD": 3,  # El resto del mundo
    "EUROPE": 4,  # Luego Europa
    "JPN": 5,  # Por último Japón
}

## Configuración de validación
MIN_HASH_LENGTH = 8
