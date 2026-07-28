"""Read one Engagement's structurally unobtainable Gated Inputs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .artifact_paths import engagement_artifact_key
from .control_sheet import Engagement


VALUES_FILE = "valores.json"
GATED_VALUE_SLOTS = (
    ("plano_hospedagem", ("{{PLANO_HOSPEDAGEM}}",)),
    ("email_cliente", ("{{EMAIL_CLIENTE}}",)),
    ("data_entrega", ("{{DATA_ENTREGA}}",)),
    ("data_backup", ("{{DATA_BACKUP}}",)),
    ("link_codigo_fonte", ("{{LINK_CODIGO_FONTE}}",)),
    ("link_guia_rapido", ("{{LINK_GUIA_RAPIDO}}",)),
    ("link_identidade_visual", ("{{LINK_IDENTIDADE_VISUAL}}",)),
    ("link_usuarios_senhas", ("{{LINK_USUARIOS_SENHAS}}",)),
    (
        "dominio_publicado",
        ("{{DOMINIO_PUBLICADO}}", "{{WP_ADMIN_URL}}"),
    ),
)
GATED_IMAGE_PARTS = (
    ("paleta", "paleta.png", "word/media/image3.png"),
    ("login", "login.png", "word/media/image13.png"),
    ("painel", "painel.png", "word/media/image14.png"),
    ("yoast-a", "yoast-a.png", "word/media/image15.png"),
    ("yoast-b", "yoast-b.png", "word/media/image16.png"),
    ("yoast-c", "yoast-c.png", "word/media/image17.png"),
    ("drive", "drive.png", "word/media/image18.png"),
    ("kickoff", "kickoff.jpg", "word/media/image19.jpeg"),
    ("entrega", "entrega.png", "word/media/image20.png"),
)
_VALUE_KEYS = frozenset(
    {"pasta", "razao_social"}
    | {slot for slot, _tokens in GATED_VALUE_SLOTS}
)
_IGNORED_FILES = frozenset({".gitkeep", "README.md"})
_DOMAIN = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GatedInputs:
    """Validated inputs found in exactly one Engagement folder."""

    folder: Path | None
    token_values: tuple[tuple[str, str], ...] = ()
    images: tuple[tuple[str, Path, str], ...] = ()

    def values_by_token(self) -> dict[str, str]:
        return dict(self.token_values)

    def images_by_part(self) -> dict[str, tuple[str, Path]]:
        return {
            part_name: (slot, source)
            for slot, source, part_name in self.images
        }


class GatedInputError(ValueError):
    """A present Gated Drop Folder is unsafe or malformed."""


def gated_drop_folder(
    gated_drop_root: str | Path, engagement: Engagement
) -> Path:
    """Return the only folder this Engagement is allowed to read."""
    return Path(gated_drop_root) / engagement_artifact_key(engagement)


def _required_text(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GatedInputError(f"{VALUES_FILE}.{key} must be a non-empty string")
    return value.strip()


def _date(value: str, key: str) -> str:
    try:
        return datetime.strptime(value, "%d/%m/%Y").strftime("%d/%m/%Y")
    except ValueError as error:
        raise GatedInputError(
            f"{VALUES_FILE}.{key} must use DD/MM/YYYY"
        ) from error


def _drive_link(value: str, key: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "drive.google.com"
        or not parsed.path.strip("/")
    ):
        raise GatedInputError(
            f"{VALUES_FILE}.{key} must be an https://drive.google.com/ URL"
        )
    return value


def _domain(value: str) -> str:
    domain = value.casefold().rstrip(".")
    if not _DOMAIN.fullmatch(domain):
        raise GatedInputError(
            f"{VALUES_FILE}.dominio_publicado must be a bare published domain"
        )
    return domain


def _token_values(document: dict[str, object]) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for slot, tokens in GATED_VALUE_SLOTS:
        if slot not in document:
            continue
        supplied = _required_text(document, slot)
        if slot in {"data_entrega", "data_backup"}:
            supplied = _date(supplied, slot)
        elif slot.startswith("link_"):
            supplied = _drive_link(supplied, slot)
        elif slot == "email_cliente" and (
            "@" not in supplied or supplied.startswith("@") or supplied.endswith("@")
        ):
            raise GatedInputError(
                f"{VALUES_FILE}.email_cliente must be a supplied email address"
            )
        elif slot == "dominio_publicado":
            supplied = _domain(supplied)
        for token in tokens:
            value = (
                f"https://{supplied}/wp-admin/"
                if token == "{{WP_ADMIN_URL}}"
                else supplied
            )
            values.append((token, value))
    return tuple(values)


def load_gated_inputs(
    gated_drop_root: str | Path, engagement: Engagement
) -> GatedInputs:
    """Load only this Engagement's folder; an absent folder is normal."""
    folder = gated_drop_folder(gated_drop_root, engagement)
    if not folder.exists():
        return GatedInputs(folder=None)
    if folder.is_symlink() or not folder.is_dir():
        raise GatedInputError(f"Gated Drop Folder is not a directory: {folder}")
    linked = sorted(item.name for item in folder.iterdir() if item.is_symlink())
    if linked:
        raise GatedInputError(
            "Gated Drop Folder must not contain symbolic links: "
            + ", ".join(linked)
        )

    known_images = {
        filename: (slot, part_name)
        for slot, filename, part_name in GATED_IMAGE_PARTS
    }
    unknown = sorted(
        item.name
        for item in folder.iterdir()
        if item.name not in known_images
        and item.name != VALUES_FILE
        and item.name not in _IGNORED_FILES
    )
    if unknown:
        raise GatedInputError(
            f"Gated Drop Folder contains unknown input(s): {', '.join(unknown)}"
        )

    values_path = folder / VALUES_FILE
    supplied_images = [
        item for item in folder.iterdir() if item.name in known_images
    ]
    if not values_path.exists():
        if supplied_images:
            raise GatedInputError(
                f"{VALUES_FILE} is required to identify a present Gated Drop Folder"
            )
        return GatedInputs(folder=None)
    try:
        document = json.loads(values_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GatedInputError(f"{values_path}: invalid JSON: {error}") from error
    if not isinstance(document, dict):
        raise GatedInputError(f"{VALUES_FILE} must contain a JSON object")
    unknown_keys = sorted(set(document) - _VALUE_KEYS)
    if unknown_keys:
        raise GatedInputError(
            f"{VALUES_FILE} has unknown field(s): {', '.join(unknown_keys)}"
        )
    pasta = _required_text(document, "pasta")
    razao_social = _required_text(document, "razao_social")
    if pasta != engagement.pasta or razao_social != engagement.razao_social:
        raise GatedInputError(
            f"Gated Drop Folder belongs to Pasta {pasta!r} / "
            f"Razao Social {razao_social!r}, not this Engagement"
        )

    images = tuple(
        (known_images[item.name][0], item, known_images[item.name][1])
        for item in sorted(supplied_images, key=lambda candidate: candidate.name)
    )
    for _slot, source, _part_name in images:
        signature = source.read_bytes()[:8]
        expected = (
            signature.startswith(b"\xff\xd8")
            if source.suffix.casefold() == ".jpg"
            else signature == b"\x89PNG\r\n\x1a\n"
        )
        if not expected:
            raise GatedInputError(
                f"{source.name} does not contain the image format its name declares"
            )
    return GatedInputs(
        folder=folder,
        token_values=_token_values(document),
        images=images,
    )


__all__ = [
    "GATED_IMAGE_PARTS",
    "GATED_VALUE_SLOTS",
    "GatedInputError",
    "GatedInputs",
    "gated_drop_folder",
    "load_gated_inputs",
]
