"""
RetroAchievements Downloader - Aplicación unificada.
Permite elegir entre modo hash directo o lista de deseos.
"""

import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

# Permite importar src/ y config.py desde la raiz del repo cuando este
# script corre desde console/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app import AppMode, RetroAchievementsDownloader


def main():
    """Función principal que permite elegir el modo de operación."""
    console = Console()

    console.print(Panel("[bold green]🎮 RetroAchievements Downloader[/bold green]", border_style="green", expand=False))
    console.print("\n[bold blue]Seleccioná el modo de operación:[/bold blue]")
    console.print("  [cyan]1.[/cyan] Búsqueda directa por hash")
    console.print("  [cyan]2.[/cyan] Lista de deseos (Want to Play)")

    choice = Prompt.ask("\n  [bold]→[/bold]", choices=["1", "2"], default="1")

    if choice == "1":
        app = RetroAchievementsDownloader(AppMode.DIRECT_HASH)
    else:
        app = RetroAchievementsDownloader(AppMode.WANT_TO_PLAY)

    app.run()


if __name__ == "__main__":
    main()
