"""
Modo consola - Búsqueda directa por hash.
Interfaz de línea de comandos para buscar ROMs por hash.
"""

import os
import sys

# Permite importar src/ y config.py desde la raiz del repo cuando este
# script corre desde console/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app import create_direct_hash_app


def main():
    """Función principal para el modo consola."""
    app = create_direct_hash_app()
    app.run()


if __name__ == "__main__":
    main()
