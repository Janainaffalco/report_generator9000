"""Loja Virtual reports must never claim sales or commerce settings unseen."""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from ..docx_package import DocxPackage
from ..run_context import RunContext
from .results import GateResult, result, violation


GATE = "loja-purchase-claims"


def _normalized(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


class _Claim(NamedTuple):
    rule_slug: str
    pattern: re.Pattern[str]


_DONE = r"(?:concluid|realizad|efetuad|processad|aprovad)\w*"
_SET_UP = r"(?:configurad|integrad|ativad|habilitad|implementad)\w*"
_IS = r"(?:esta|estao|foi|foram|e|sao|encontra-se|encontram-se)"

_CLAIMS = (
    _Claim(
        "completed-transactions",
        re.compile(rf"\b(?:transac\w*|vendas?|pedidos?|compras?)\s+(?:online\s+)?(?:{_IS}\s+)?{_DONE}"),
    ),
    _Claim(
        "processes-online-sales",
        re.compile(r"\b(?:processa\w*|recebe\w*)\s+(?:de\s+)?(?:pagamentos|vendas|pedidos)\s+online"),
    ),
    _Claim(
        "payment-configured",
        re.compile(rf"\b(?:pagamentos?|gateways?\s+de\s+pagamento|meios?\s+de\s+pagamento)\s+(?:online\s+)?{_IS}\s+{_SET_UP}"),
    ),
    _Claim(
        "shipping-configured",
        re.compile(rf"\b(?:frete|fretes|entregas?|envios?)\s+{_IS}\s+(?:{_SET_UP}|calculad\w*)"),
    ),
    _Claim(
        "stock-configured",
        re.compile(rf"\b(?:controle\s+de\s+)?estoques?\s+{_IS}\s+(?:{_SET_UP}|controlad\w*)"),
    ),
    _Claim(
        "secure-purchase-asserted",
        re.compile(r"\b(?:compra|pagamento|checkout|ambiente)\s+(?:100%\s+)?segur[oa]\b"),
    ),
    _Claim(
        "checkout-verified",
        re.compile(rf"\bcheckout\s+(?:no\s+proprio\s+site\s+)?(?:{_IS}\s+)?(?:verificad|testad|{_DONE})"),
    ),
)

# A negated sentence states what the report does not claim, which is exactly
# the honest wording this gate protects; only affirmative sentences count.
_NEGATION = re.compile(r"\b(?:nao|nem|sem)\b")
_SENTENCE = re.compile(r"[.;:!?]")


def check_loja_purchase_claims(package: DocxPackage, context: RunContext) -> GateResult:
    violations = []
    for paragraph in package.paragraphs:
        for sentence in _SENTENCE.split(_normalized(paragraph.text)):
            if _NEGATION.search(sentence):
                continue
            for claim in _CLAIMS:
                if claim.pattern.search(sentence):
                    violations.append(
                        violation(
                            GATE,
                            claim.rule_slug,
                            "document",
                            "remove unevidenced sale or commerce-setting claim",
                        )
                    )
    return result(GATE, violations)
