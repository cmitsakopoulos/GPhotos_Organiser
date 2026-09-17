"""
UI and Terminal Theme System for Google Photos Takeout Organizer.
Provides a modern, delightful terminal aesthetic with vibrant colors,
custom badges, card formatting, and ASCII banners using colorama.
"""

import sys
from typing import Optional

try:
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=True)
    _COLORAMA_AVAILABLE = True
except ImportError:
    _COLORAMA_AVAILABLE = False
    Fore = None
    Style = None

_USE_COLOR = True


def set_use_color(enabled: bool):
    global _USE_COLOR
    _USE_COLOR = enabled


def is_color_enabled() -> bool:
    return _USE_COLOR and _COLORAMA_AVAILABLE and sys.stdout.isatty()


# Theme Palette
class Theme:
    @staticmethod
    def primary(text: str) -> str:
        return f"{Fore.CYAN}{Style.BRIGHT}{text}{Style.RESET_ALL}" if is_color_enabled() else text

    @staticmethod
    def secondary(text: str) -> str:
        return f"{Fore.MAGENTA}{Style.BRIGHT}{text}{Style.RESET_ALL}" if is_color_enabled() else text

    @staticmethod
    def success(text: str) -> str:
        return f"{Fore.GREEN}{Style.BRIGHT}{text}{Style.RESET_ALL}" if is_color_enabled() else text

    @staticmethod
    def warning(text: str) -> str:
        return f"{Fore.YELLOW}{Style.BRIGHT}{text}{Style.RESET_ALL}" if is_color_enabled() else text

    @staticmethod
    def danger(text: str) -> str:
        return f"{Fore.RED}{Style.BRIGHT}{text}{Style.RESET_ALL}" if is_color_enabled() else text

    @staticmethod
    def muted(text: str) -> str:
        return f"{Fore.LIGHTBLACK_EX}{text}{Style.RESET_ALL}" if is_color_enabled() else text

    @staticmethod
    def bold(text: str) -> str:
        return f"{Style.BRIGHT}{text}{Style.RESET_ALL}" if is_color_enabled() else text

    @staticmethod
    def value(text: str) -> str:
        return f"{Fore.WHITE}{Style.BRIGHT}{text}{Style.RESET_ALL}" if is_color_enabled() else text


# Styled Badges (100% Pure ASCII for universal platform compatibility)
def badge_info(msg: str = "") -> str:
    tag = Theme.primary("[DISCOVER]")
    return f"{tag} {msg}" if msg else tag


def badge_archive(msg: str = "") -> str:
    tag = Theme.secondary("[ARCHIVE]")
    return f"{tag} {msg}" if msg else tag


def badge_match(msg: str = "") -> str:
    tag = Theme.success("[MATCH]")
    return f"{tag} {msg}" if msg else tag


def badge_gps(msg: str = "") -> str:
    tag = f"{Fore.MAGENTA}{Style.BRIGHT}[GPS]{Style.RESET_ALL}" if is_color_enabled() else "[GPS]"
    return f"{tag} {msg}" if msg else tag


def badge_dedup(msg: str = "") -> str:
    tag = Theme.warning("[DEDUP]")
    return f"{tag} {msg}" if msg else tag


def badge_clean(msg: str = "") -> str:
    tag = f"{Fore.BLUE}{Style.BRIGHT}[CLEANUP]{Style.RESET_ALL}" if is_color_enabled() else "[CLEANUP]"
    return f"{tag} {msg}" if msg else tag


def badge_success(msg: str = "") -> str:
    tag = Theme.success("[COMPLETE]")
    return f"{tag} {msg}" if msg else tag


def badge_warn(msg: str = "") -> str:
    tag = Theme.warning("[WARN]")
    return f"{tag} {msg}" if msg else tag


def print_banner():
    """Prints a clean, universal ASCII banner."""
    c_border = Fore.CYAN if is_color_enabled() else ""
    c_title = f"{Fore.MAGENTA}{Style.BRIGHT}" if is_color_enabled() else ""
    c_sub = f"{Fore.WHITE}{Style.DIM}" if is_color_enabled() else ""
    reset = Style.RESET_ALL if is_color_enabled() else ""

    banner_lines = [
        f"{c_border}+-------------------------------------------------------------+{reset}",
        f"{c_border}|  {c_title}Google Photos Takeout Organizer{reset}{c_border}                            |{reset}",
        f"{c_border}|  {c_sub}Restoring memories, metadata & chronology with care{reset}{c_border}         |{reset}",
        f"{c_border}+-------------------------------------------------------------+{reset}",
    ]
    print("\n" + "\n".join(banner_lines) + "\n")
