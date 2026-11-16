"""Prompt templates, loaded from .txt files packaged with the agent."""

from __future__ import annotations

from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent


@cache
def load(name: str) -> str:
    return (_DIR / f"{name}.txt").read_text(encoding="utf-8")


def system_review(categories: list[str], min_confidence: float, extra_instructions: str = "") -> str:
    base = load("system_review").format(
        categories=", ".join(categories),
        min_confidence=min_confidence,
    )
    if extra_instructions.strip():
        base += (
            "\n\nRepository-specific instructions (treat as guidance from the maintainers):\n"
            + extra_instructions.strip()
        )
    return base


def system_critic() -> str:
    return load("system_critic")


def system_crossfile() -> str:
    return load("system_crossfile")
