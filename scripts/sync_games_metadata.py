"""
Genera Data/retroachievements_metadata.json cruzando nuestra coleccion
contra el catalogo de RetroAchievements (titulos reales, caratulas,
cantidad de logros, y el set de hashes que RA reconoce).
Requiere API_KEY en .env (ver ejemplo.env).
"""

import os
import sys

# Permite importar src/ y config.py desde la raiz del repo cuando este
# script corre desde scripts/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.games_metadata_sync import GamesMetadataSync


def main():
    GamesMetadataSync().run()


if __name__ == "__main__":
    main()
