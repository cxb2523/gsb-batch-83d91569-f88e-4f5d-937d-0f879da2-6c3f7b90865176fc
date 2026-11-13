"""
Sincroniza game_hashes.json con tu lista "Want to Play" real de RetroAchievements.
Requiere API_KEY y RETROACHIEVEMENTS_USERNAME en .env (ver ejemplo.env).
"""

import os
import sys

# Permite importar src/ y config.py desde la raiz del repo cuando este
# script corre desde scripts/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.want_to_play_sync import WantToPlaySync


def main():
    WantToPlaySync().run()


if __name__ == "__main__":
    main()
