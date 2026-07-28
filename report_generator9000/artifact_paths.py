"""Canonical filesystem keys for one Engagement's artifacts."""

from __future__ import annotations

import re

from .control_sheet import Engagement


_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


def engagement_artifact_key(engagement: Engagement) -> str:
    """Return one safe Pasta + Razao Social key used by every artifact path."""
    component = " ".join(
        _UNSAFE_FILENAME.sub("-", engagement.output_key).split()
    ).rstrip(". ")
    if not component:
        raise ValueError("Engagement artifact key has no usable characters")
    if component.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        component = f"_{component}"
    return component


__all__ = ["engagement_artifact_key"]
