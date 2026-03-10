"""Shared rich Console instance and logging helpers."""
from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

_theme = Theme({
    "info": "cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "step": "bold blue",
    "dim": "dim white",
})

console = Console(theme=_theme, highlight=False)


def log(msg: str) -> None:
    console.print(f"[info]>[/info] {msg}")


def success(msg: str) -> None:
    console.print(f"[success]✓[/success] {msg}")


def warn(msg: str) -> None:
    console.print(f"[warning]![/warning] {msg}")


def error(msg: str) -> None:
    console.print(f"[error]✗[/error] {msg}")


def step(msg: str) -> None:
    console.print(f"\n[step]==[/step] {msg}")
