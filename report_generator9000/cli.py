from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .docx_package import DocxPackage, open_docx_package
from .gates import run_gates
from .run_context import RunContext, load_run_context


def _inventory_text(package: DocxPackage) -> str:
    lines = [f"PARTS ({len(package.parts)})"]
    lines.extend(f"{part.name}\t{part.size} bytes" for part in package.parts)

    lines.extend(("", f"MEDIA ({len(package.media)})"))
    lines.extend(
        f"{media.part_name}\tsha256={media.sha256}\t"
        f"{media.width} x {media.height} px\t{media.image_format}"
        for media in package.media
    )

    lines.extend(("", f"RELATIONSHIPS ({len(package.relationships)})"))
    for relationship in package.relationships:
        destination = (
            relationship.target
            if relationship.external
            else relationship.resolved_target
        )
        mode = "external" if relationship.external else "internal"
        lines.append(
            f"{relationship.source_part}\t{relationship.relationship_id}\t"
            f"{mode}\t{relationship.relationship_type}\t{destination}"
        )

    lines.extend(("", f"SLOTS ({len(package.slots)})"))
    lines.extend(
        f"{slot.source_part}\tp={slot.paragraph_index}\tr={slot.run_index}\t"
        f"{slot.relationship_id}\t{slot.media_part}\t"
        f"{slot.width_emu} x {slot.height_emu} EMU"
        for slot in package.slots
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="report-generator9000")
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser(
        "inventory", help="print the package, relationship, and Slot inventory"
    )
    inventory.add_argument("document", type=Path)
    check = commands.add_parser(
        "check", help="run the correctness gates against a generated package"
    )
    check.add_argument("document", type=Path)
    check.add_argument(
        "--context",
        type=Path,
        default=None,
        help="JSON run context declaring this run's Provenance",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "inventory":
        try:
            package = open_docx_package(arguments.document)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(_inventory_text(package))
        return 0
    if arguments.command == "check":
        try:
            package = open_docx_package(arguments.document)
            context = (
                RunContext()
                if arguments.context is None
                else load_run_context(arguments.context)
            )
        except (OSError, ValueError) as error:
            parser.error(str(error))
        report = run_gates(package, context)
        print(report.format())
        return 0 if report.passed else 1
    return 0


def inventory_main(argv: Sequence[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return main(("inventory", *arguments))


def check_main(argv: Sequence[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    return main(("check", *arguments))
