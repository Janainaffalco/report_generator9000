"""What this run is allowed to have produced, declared before it is checked."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


ORIGINS = ("boilerplate", "capture", "gated", "placeholder")
CLASSIFICATIONS = ("GATED", "TOOL_BLOCKED")


@dataclass(frozen=True)
class Artifact:
    """One media file this run is entitled to embed, and where it came from."""

    digest: str
    origin: str
    label: str
    source: str | None = None


@dataclass(frozen=True)
class Pendencia:
    """An outstanding item, and how it manifests in the document."""

    slot: str
    classification: str
    reason: str
    evidence: str


@dataclass(frozen=True)
class RunContext:
    pasta: str = ""
    media: tuple[Artifact, ...] = ()
    boilerplate_links: frozenset[str] = frozenset()
    input_origins: frozenset[str] = frozenset()
    drop_folder: str | None = None
    capture_folder: str | None = None
    output_paths: tuple[str, ...] = ()
    blocks: tuple[str, ...] = ()
    pendencias: tuple[Pendencia, ...] = ()

    @property
    def declares_a_location(self) -> bool:
        """True once this run declares a path it read from or wrote to."""
        return bool(
            self.drop_folder
            or self.capture_folder
            or self.output_paths
            or any(artifact.source for artifact in self.media)
        )

    def media_by_digest(self) -> dict[str, tuple[Artifact, ...]]:
        grouped: dict[str, list[Artifact]] = {}
        for artifact in self.media:
            grouped.setdefault(artifact.digest.lower(), []).append(artifact)
        return {digest: tuple(items) for digest, items in grouped.items()}

    def artifacts_of(self, origin: str) -> tuple[Artifact, ...]:
        return tuple(item for item in self.media if item.origin == origin)


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(
            f"{where}: expected an object, got {type(value).__name__}"
        )
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: tuple[str, ...], where: str
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ValueError(f"{where}: unknown field(s) {', '.join(unknown)}")


def _require_str(value: Mapping[str, Any], key: str, where: str) -> str:
    if key not in value:
        raise ValueError(f"{where}: missing required field {key}")
    item = value[key]
    if not isinstance(item, str):
        raise ValueError(f"{where}.{key}: expected a string")
    return item


def _string_tuple(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError(f"{where}: expected a list of strings")
    return tuple(value)


def _artifact(value: Any, where: str) -> Artifact:
    mapping = _require_mapping(value, where)
    _reject_unknown(mapping, ("digest", "origin", "label", "source"), where)
    origin = _require_str(mapping, "origin", where)
    if origin not in ORIGINS:
        raise ValueError(
            f"{where}.origin: {origin!r} is not one of {', '.join(ORIGINS)}"
        )
    source = mapping.get("source")
    if source is not None and not isinstance(source, str):
        raise ValueError(f"{where}.source: expected a string or null")
    return Artifact(
        digest=_require_str(mapping, "digest", where).lower(),
        origin=origin,
        label=_require_str(mapping, "label", where),
        source=source,
    )


def _pendencia(value: Any, where: str) -> Pendencia:
    mapping = _require_mapping(value, where)
    _reject_unknown(
        mapping, ("slot", "classification", "reason", "evidence"), where
    )
    classification = _require_str(mapping, "classification", where)
    if classification not in CLASSIFICATIONS:
        raise ValueError(
            f"{where}.classification: {classification!r} is not one of "
            f"{', '.join(CLASSIFICATIONS)}"
        )
    return Pendencia(
        slot=_require_str(mapping, "slot", where),
        classification=classification,
        reason=_require_str(mapping, "reason", where),
        evidence=_require_str(mapping, "evidence", where),
    )


def parse_run_context(document: Any) -> RunContext:
    """Build a RunContext from decoded JSON, rejecting anything unknown."""
    mapping = _require_mapping(document, "run context")
    _reject_unknown(
        mapping,
        (
            "pasta",
            "media",
            "boilerplate_links",
            "input_origins",
            "drop_folder",
            "capture_folder",
            "output_paths",
            "blocks",
            "pendencias",
        ),
        "run context",
    )
    for key in ("drop_folder", "capture_folder"):
        if mapping.get(key) is not None and not isinstance(mapping[key], str):
            raise ValueError(f"run context.{key}: expected a string or null")
    pasta = mapping.get("pasta", "")
    if not isinstance(pasta, str):
        raise ValueError("run context.pasta: expected a string")
    media = tuple(
        _artifact(item, f"run context.media[{index}]")
        for index, item in enumerate(mapping.get("media", []))
    )
    pendencias = tuple(
        _pendencia(item, f"run context.pendencias[{index}]")
        for index, item in enumerate(mapping.get("pendencias", []))
    )
    return RunContext(
        pasta=pasta,
        media=media,
        boilerplate_links=frozenset(
            _string_tuple(
                mapping.get("boilerplate_links", []),
                "run context.boilerplate_links",
            )
        ),
        input_origins=frozenset(
            _string_tuple(
                mapping.get("input_origins", []), "run context.input_origins"
            )
        ),
        drop_folder=mapping.get("drop_folder"),
        capture_folder=mapping.get("capture_folder"),
        output_paths=_string_tuple(
            mapping.get("output_paths", []), "run context.output_paths"
        ),
        blocks=_string_tuple(mapping.get("blocks", []), "run context.blocks"),
        pendencias=pendencias,
    )


def load_run_context(path: str | Path) -> RunContext:
    """Read a run context from *path*, a JSON file."""
    location = Path(path)
    try:
        document = json.loads(location.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{location}: invalid JSON: {error}") from error
    try:
        return parse_run_context(document)
    except ValueError as error:
        raise ValueError(f"{location}: {error}") from error


def is_within(candidate: str, folder: str) -> bool:
    """True when *candidate* is *folder* itself or sits underneath it."""
    inner = PurePosixPath(candidate.replace("\\", "/"))
    outer = PurePosixPath(folder.replace("\\", "/"))
    return inner == outer or outer in inner.parents
