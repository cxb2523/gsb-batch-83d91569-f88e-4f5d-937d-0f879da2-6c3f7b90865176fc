"""
Modo lista de deseos - Want to Play.
Interfaz para descargar juegos desde tu lista de deseos.
"""

import os
import sys

# Permite importar src/ y config.py desde la raiz del repo cuando este
# script corre desde console/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app import create_want_to_play_app


def main():
    """Función principal para el modo lista de deseos."""
    app = create_want_to_play_app()
    app.run()


if __name__ == "__main__":
    main()
