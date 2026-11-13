"""
Utilidades comunes para el sistema.
"""

from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule


class UIHelper:
    """Helper para operaciones de interfaz de usuario."""

    def __init__(self):
        self.console = Console()

    def select_from_list(self, items: List[str], title: str, allow_all: bool = False) -> Optional[str]:
        """Permite al usuario seleccionar de una lista de elementos.

        Agrega al final dos opciones numeradas: cambiar de modo y salir.
        """
        if not items:
            self.console.print(f"[bold red]❌ No hay {title.lower()} disponibles.[/bold red]")
            return None

        self.console.print(Rule(f"[bold blue]{title.capitalize()}[/bold blue]", style="blue", align="left"))

        for i, item in enumerate(items, 1):
            self.console.print(f"  [cyan]{i}.[/cyan] {item}")

        next_index = len(items) + 1
        all_index = None
        if allow_all:
            self.console.print(f"  [cyan]{next_index}.[/cyan] [dim]Todos[/dim]")
            all_index = next_index
            next_index += 1

        cambiar_index = next_index
        salir_index = next_index + 1
        self.console.print(f"  [cyan]{cambiar_index}.[/cyan] [dim]Cambiar de modo[/dim]")
        self.console.print(f"  [cyan]{salir_index}.[/cyan] [dim]Salir[/dim]")

        choice = Prompt.ask("  [bold]→[/bold] Elegí una opción", default="1", show_default=True)

        try:
            choice_num = int(choice)
        except ValueError:
            self.console.print(f"[bold red]❌ Entrada no válida, usando {items[0]!r} por defecto.[/bold red]")
            return items[0]

        if choice_num == salir_index:
            return "salir"
        if choice_num == cambiar_index:
            return "cambiar"
        if allow_all and choice_num == all_index:
            return "todos"
        if 1 <= choice_num <= len(items):
            return items[choice_num - 1]

        self.console.print(f"[bold red]❌ Selección no válida, usando {items[0]!r} por defecto.[/bold red]")
        return items[0]

    def get_hash_input(self) -> str:
        """Obtiene un hash del usuario. Atajos: 'M' cambia de modo, 'S' sale."""
        hash_value = Prompt.ask("\n[bold]🔎 Hash a buscar[/bold] [dim](M: cambiar de modo, S: salir)[/dim]")

        normalized = hash_value.strip().lower()
        if normalized == "s":
            self.console.print("[bold yellow]👋 Saliendo...[/bold yellow]")
            return "salir"

        if normalized == "m":
            return "cambiar"

        return hash_value

    def display_welcome_message(self, app_name: str, subtitle: Optional[str] = None):
        """Muestra el panel de bienvenida con el nombre de la app y, opcionalmente, el modo activo."""
        text = f"[bold green]🎮 {app_name}[/bold green]"
        if subtitle:
            text += f"\n[dim]{subtitle}[/dim]"
        self.console.print(Panel(text, border_style="green", expand=False))

    def display_success_message(self, message: str):
        """Muestra mensaje de éxito."""
        self.console.print(f"[bold green]✅ {message}[/bold green]")

    def display_error_message(self, message: str):
        """Muestra mensaje de error."""
        self.console.print(f"[bold red]❌ {message}[/bold red]")

    def display_info_message(self, message: str):
        """Muestra mensaje informativo."""
        self.console.print(f"[bold blue]ℹ️  {message}[/bold blue]")


class ValidationHelper:
    """Helper para validaciones."""

    @staticmethod
    def is_valid_hash(hash_value: str) -> bool:
        """Valida si el hash tiene un formato válido."""
        if not hash_value or not isinstance(hash_value, str):
            return False

        try:
            import config

            min_length = config.MIN_HASH_LENGTH
        except ImportError:
            min_length = 8

        # Un hash típico debe tener al menos min_length caracteres y ser hexadecimal
        return len(hash_value) >= min_length and all(c in "0123456789ABCDEFabcdef" for c in hash_value)

    @staticmethod
    def is_valid_file_path(file_path: str) -> bool:
        """Valida si la ruta del archivo es válida."""
        try:
            from pathlib import Path

            return Path(file_path).exists()
        except Exception:
            return False
