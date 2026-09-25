"""The single routing contract for contracted Temas."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


WEBSITE_TEMA = "Inserção digital - Desenvolvimento de WebSite"
LOJA_VIRTUAL_TEMA = "Implantação de Loja Virtual"

# The label the curated Loja Master binds each administrative Gated image Slot
# to. A Pendência names the label rather than the Slot, so a consultant reading
# PENDENCIAS.md knows which screenshot is missing without opening the document.
LOJA_GATED_SLOT_LABELS = (
    ("login", "PÁGINA DE LOGIN"),
    ("painel", "PAINEL DE CONFIGURAÇÃO WORDPRESS"),
    ("produtos-admin", "LISTA DE PRODUTOS"),
    ("pagamentos-admin", "CONFIGURAÇÃO DE PAGAMENTOS"),
    ("entregas-admin", "CONFIGURAÇÃO DE ENTREGAS"),
    ("drive", "COMPARTILHAMENTO DECLARADO PELO CONSULTOR"),
    ("kickoff", "PRINT DO KICKOFF"),
    ("entrega", "PRINT DA ENTREGA"),
)


def _key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


@dataclass(frozen=True)
class TemaContract:
    name: str
    supported: bool
    master: Path | None = None
    spreadsheet_tokens: tuple[tuple[str, str], ...] = ()
    gated_value_slots: tuple[tuple[str, tuple[str, ...]], ...] = ()
    gated_image_slots: tuple[tuple[str, str, str], ...] = ()
    gated_slot_labels: tuple[tuple[str, str], ...] = ()
    boilerplate_media: frozenset[str] = frozenset()
    required_blocks: tuple[str, ...] = ()
    master_gate: Callable[..., object] | None = None
    gates: tuple[Callable[..., object], ...] = ()

    @property
    def image_filenames(self) -> dict[str, str]:
        return {slot: filename for slot, filename, _part in self.gated_image_slots}

    @property
    def value_slot_names(self) -> set[str]:
        return {slot for slot, _tokens in self.gated_value_slots}

    def slot_label(self, slot: str) -> str:
        """Return the label the Master binds *slot* to, or the slot itself.

        A Tema that declares no labels keeps naming its Pendências after the
        Slot, which is how the WebSite grammar has always read.
        """
        return dict(self.gated_slot_labels).get(slot, slot)


def contract_for(tema: str) -> TemaContract | None:
    """Resolve sheet spelling without replacing its original display value."""
    loja = _key(tema) == _key(LOJA_VIRTUAL_TEMA)
    if not loja and _key(tema) != _key(WEBSITE_TEMA):
        return None

    # Import at resolution time so the contract can assemble the existing
    # WebSite grammar without creating cycles with its implementation modules.
    from .gated_inputs import GATED_IMAGE_PARTS, GATED_VALUE_SLOTS
    from .gates import GATES
    from .gates.loja_blocks import check_loja_block_grammar
    from .gates.loja_credentials import check_loja_credentials
    from .gates.loja_handover import check_loja_handover_claims
    from .gates.loja_purchase import check_loja_purchase_claims
    from .gates.master import BOILERPLATE_MEDIA, LOJA_VIRTUAL_GRAMMAR, check_loja_master, check_master_build

    if loja:
        return TemaContract(
            name=LOJA_VIRTUAL_TEMA,
            supported=True,
            master=Path(__file__).with_name("assets") / "MASTER-LOJA-VIRTUAL.docx",
            spreadsheet_tokens=(
                ("{{DEMANDA}}", "demanda"),
                ("{{RAZAO_SOCIAL}}", "razao_social"),
                ("{{CNPJ}}", "cnpj"),
                ("{{ESPECIALISTA}}", "especialista"),
                ("{{DATA_KICKOFF}}", "kick_off_br"),
            ),
            gated_value_slots=tuple(
                (slot, tokens) for slot, tokens in GATED_VALUE_SLOTS
                if slot != "link_usuarios_senhas"
            ) + (("configuracao_woocommerce", ("{{CONFIGURACAO_WOOCOMMERCE}}",)),),
            gated_image_slots=tuple(
                {
                    "yoast-a": ("produtos-admin", "produtos-admin.png", part),
                    "yoast-b": ("pagamentos-admin", "pagamentos-admin.png", part),
                    "yoast-c": ("entregas-admin", "entregas-admin.png", part),
                }.get(slot, (slot, filename, part))
                for slot, filename, part in GATED_IMAGE_PARTS
            ),
            gated_slot_labels=LOJA_GATED_SLOT_LABELS,
            boilerplate_media=BOILERPLATE_MEDIA,
            required_blocks=LOJA_VIRTUAL_GRAMMAR.block_headings,
            master_gate=check_loja_master,
            gates=(
                *GATES,
                check_loja_block_grammar,
                check_loja_credentials,
                check_loja_handover_claims,
                check_loja_purchase_claims,
            ),
        )

    return TemaContract(
        name=WEBSITE_TEMA,
        supported=True,
        master=Path(__file__).with_name("assets") / "MASTER.docx",
        spreadsheet_tokens=(
            ("{{DEMANDA}}", "demanda"),
            ("{{RAZAO_SOCIAL}}", "razao_social"),
            ("{{CNPJ}}", "cnpj"),
            ("{{ESPECIALISTA}}", "especialista"),
            ("{{DATA_KICKOFF}}", "kick_off_br"),
        ),
        gated_value_slots=GATED_VALUE_SLOTS,
        gated_image_slots=GATED_IMAGE_PARTS,
        boilerplate_media=BOILERPLATE_MEDIA,
        master_gate=check_master_build,
        gates=GATES,
    )


def supported_contract(tema: str) -> TemaContract:
    contract = contract_for(tema)
    if contract is None or not contract.supported or contract.master is None:
        raise ValueError(f"Tema {tema!r} has no approved Run path")
    return contract
