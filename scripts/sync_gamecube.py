"""
Da de alta Nintendo GameCube en Data/TamperMonkeyRetroachievements.json
cruzando el .dat de RetroAchievements contra el item de archive.org
'RetroAchievementsGameCube', sin descargar ningun juego (matchea por MD5
del .rvz, no por nombre -- ver src/core/gamecube_sync.py).

Uso:
    python scripts/sync_gamecube.py
"""

import os
import sys

# Permite importar src/ y config.py desde la raiz del repo cuando este
# script corre desde scripts/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.gamecube_sync import GameCubeSync

if __name__ == "__main__":
    GameCubeSync().run()
