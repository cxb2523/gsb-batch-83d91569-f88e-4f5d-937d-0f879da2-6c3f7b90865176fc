"""
Da de alta Wii en Data/TamperMonkeyRetroachievements.json cruzando el .dat
de RetroAchievements contra el item de archive.org 'RetroAchievementsWii',
sin descargar ningun juego (matchea por MD5, no por nombre -- ver
src/core/dat_archive_sync.py).

Uso:
    python scripts/sync_wii.py
"""

import os
import sys

# Permite importar src/ y config.py desde la raiz del repo cuando este
# script corre desde scripts/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.wii_sync import WiiSync

if __name__ == "__main__":
    WiiSync().run()
