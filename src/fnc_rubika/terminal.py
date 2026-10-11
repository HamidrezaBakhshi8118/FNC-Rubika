"""Small, secret-safe terminal presentation helpers for first session login."""

from __future__ import annotations

try:  # The dependency is installed by default on supported Windows terminals.
    from chroma_term_console import bold as _bold
    from chroma_term_console import fg as _fg
except ImportError:  # Keep headless/non-Windows use functional without ANSI codes.
    def _fg(_: str, text: str) -> str:
        return text

    def _bold(text: str) -> str:
        return text


def prompt_label(text: str) -> str:
    """Return a Chroma-styled terminal prompt without including secret input."""

    return _bold(_fg("cyan", f"{text}: "))


def info(text: str) -> None:
    """Print non-sensitive login progress in a Chroma-styled form."""

    print(_fg("blue", text))


def success(text: str) -> None:
    """Print a non-sensitive success status in green."""

    print(_bold(_fg("green", text)))
