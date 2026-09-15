"""Curate the Loja Virtual Master from the client-neutral WebSite Master.

The filled reference report is deliberately not an input. This transformation
keeps the signed-off SEBRAETEC cover, fonts, TOC and Slot geometry, then writes
Loja-specific section grammar and cautious, reusable Boilerplate.
"""

from __future__ import annotations

import re
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from report_generator9000.docx_package import WORD_NS, serialize_xml


W = f"{{{WORD_NS}}}"
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "report_generator9000/assets/MASTER.docx"
TARGET = ROOT / "report_generator9000/assets/MASTER-LOJA-VIRTUAL.docx"
SOURCE_SHA256 = "f7c86324564e41ab55d60b51a2cd1b37854778ecf10ee331297ae502edbba080"
TOKEN = re.compile(r"(\{\{[^{}]+\}\})")

# Indices refer to the neutral, versioned WebSite Master. Assertions below
# prevent an accidental rebuild against a different Master revision.
REWRITES = {
    7: "IMPLANTAÇÃO DE LOJA VIRTUAL",
    28: "IMPLANTAÇÃO DE LOJA VIRTUAL",
    31: "O objetivo contratado é implantar uma loja virtual. Este relatório registra o que pode ser observado no endereço público e identifica separadamente os dados de configuração que dependem de acesso administrativo ou de entrega pelo cliente.",
    33: "Descrição geral da plataforma; a configuração desta loja requer evidência própria.",
    36: "Os materiais de entrega são identificados pelos links fornecidos abaixo. A ausência de um link permanece sinalizada:",
    37: "Materiais de implantação disponíveis quando comprovados pelos links abaixo",
    45: "Os dados de hospedagem e domínio abaixo são preenchidos a partir dos insumos declarados ou identificados durante a geração. A configuração da conta de hospedagem não é inferida do endereço público.",
    46: "A aprovação de tema, DNS, SSL e demais ajustes privados exige comprovação específica e não é afirmada por este relatório básico.",
    47: "Fornecedor da hospedagem: conforme contrato informado pelo cliente",
    51: "Recursos possíveis da plataforma, sujeitos a confirmação da configuração desta loja:",
    52: "Gerenciamento de catálogo e conteúdo",
    53: "Carrinho e finalização de pedido",
    54: "Integrações de pagamento e entrega",
    56: "O desempenho e a indexação da loja dependem de medição e configuração próprias; este relatório não declara otimizações não verificadas.",
    57: "SEO: a plataforma admite recursos de otimização para busca, sem que isto comprove sua ativação nesta loja.",
    58: "Velocidade: qualquer melhoria aplicada deve ser demonstrada por evidência da implantação.",
    61: "PLATAFORMA | WORDPRESS E WOOCOMMERCE",
    63: "WordPress é um sistema livre de gestão de conteúdo para sites. Esta descrição é geral e não comprova versões, tema ou ajustes usados nesta loja.",
    64: "WooCommerce é um plugin de comércio eletrônico para WordPress que oferece recursos de catálogo, carrinho e pedidos. Sua configuração, integrações e operação nesta loja precisam de evidência específica. Referência sobre a plataforma WordPress:",
    68: "Os plugins citados nesta seção são referências de ferramentas padrão. A lista não afirma que algum deles foi instalado ou configurado nesta loja.",
    105: "VITRINE E PÁGINAS",
    110: "SEÇÃO CARRINHO",
    112: "SEÇÃO CHECKOUT",
    124: "O endereço administrativo, quando declarado, é apresentado abaixo. Seu acesso e a configuração privada não são verificados a partir do site público:",
    128: "Imagem do acesso administrativo, se fornecida para este atendimento:",
    133: "O uso do painel exige acesso autorizado do cliente; esta seção não registra credenciais.",
    134: "A presença de plugins de segurança e suas regras de bloqueio dependem de inspeção da configuração administrativa.",
    135: "O cliente deve consultar as políticas de acesso definidas para sua instalação antes de operar o painel.",
    139: "Configuração privada do WooCommerce declarada para esta implantação: {{CONFIGURACAO_WOOCOMMERCE}}",
    140: "As imagens administrativas abaixo precisam ser fornecidas separadamente. Sem elas, as lacunas permanecem identificadas e este relatório não afirma ajustes de catálogo, pagamento ou entrega.",
    148: "O registro de orientações ou reuniões deve ser comprovado pelos materiais de entrega, sem presunção de treinamento realizado.",
    151: "FUNCIONALIDADES DA LOJA",
    152: "Evidência do fluxo público de carrinho e checkout: {{EVIDENCIA_CHECKOUT}}",
    162: "Para manter a loja disponível, o cliente deve acompanhar suas contas de hospedagem e domínio e as obrigações de renovação junto aos fornecedores contratados.",
    163: "Os materiais de entrega, quando fornecidos, devem ser baixados do link compartilhado no e-mail {{EMAIL_CLIENTE}}.",
    164: "Para a operação futura da loja, recomenda-se:",
    165: "Manter WordPress e WooCommerce atualizados após verificar compatibilidade e realizar backup.",
    166: "Revisar atualizações de plugins e integrações antes de aplicá-las em produção.",
    167: "Acompanhar a renovação do domínio e da hospedagem usados pela loja.",
    168: "Para problemas de hospedagem, consultar os canais de atendimento do fornecedor contratado.",
    171: "Após a revisão e finalização deste documento, a assinatura do representante legal registra o recebimento dos materiais e orientações comprovados neste relatório.",
    177: "Link do código fonte da loja virtual para {{RAZAO_SOCIAL}} | CNPJ: {{CNPJ}}: {{LINK_CODIGO_FONTE}}",
    185: "Os acessos administrativos são tratados fora deste relatório, pelos canais autorizados do cliente.",
}


def _text(paragraph: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{W}t"))


def _rewrite(paragraph: ElementTree.Element, value: str) -> None:
    first_run = next(paragraph.iter(f"{W}r"), None)
    run_properties = None if first_run is None else first_run.find(f"{W}rPr")
    for run in list(paragraph.findall(f"{W}r")):
        paragraph.remove(run)
    for part in TOKEN.split(value):
        if not part:
            continue
        run = ElementTree.Element(f"{W}r")
        if run_properties is not None:
            run.append(deepcopy(run_properties))
        node = ElementTree.SubElement(run, f"{W}t")
        node.text = part
        if part[:1].isspace() or part[-1:].isspace():
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        paragraph.append(run)


def build() -> Path:
    if sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source WebSite Master changed; review Loja paragraph rewrites before rebuilding")
    with ZipFile(SOURCE) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    original = parts["word/document.xml"]
    document = ElementTree.fromstring(original)
    paragraphs = list(document.iter(f"{W}p"))
    assert len(paragraphs) > max(REWRITES)
    assert _text(paragraphs[7]).strip() == "INSERÇÃO DIGITAL - DESENVOLVIMENTO DE WEBSITE"
    assert _text(paragraphs[28]).strip() == "DESENVOLVIMENTO DE WEBSITE"
    assert _text(paragraphs[185]).strip().startswith("Usuários e Senhas")
    for index, value in REWRITES.items():
        _rewrite(paragraphs[index], value)
    # The platform logo is anchored to this heading. A stable page break keeps
    # the heading and floated image together as preceding Loja prose grows.
    platform_properties = paragraphs[61].find(f"{W}pPr")
    assert platform_properties is not None
    page_break = ElementTree.Element(f"{W}pageBreakBefore", {f"{W}val": "true"})
    prior = ("pStyle", "keepNext", "keepLines")
    position = 0
    for position, child in enumerate(platform_properties):
        if child.tag.rsplit("}", 1)[-1] not in prior:
            platform_properties.insert(position, page_break)
            break
    else:
        platform_properties.append(page_break)
    parts["word/document.xml"] = serialize_xml(document, original)
    for name, content in tuple(parts.items()):
        if not re.fullmatch(r"word/(?:header|footer)\d+\.xml", name):
            continue
        root = ElementTree.fromstring(content)
        changed = False
        for paragraph in root.iter(f"{W}p"):
            if "INSERÇÃO DIGITAL" in _text(paragraph):
                _rewrite(paragraph, "IMPLANTAÇÃO DE LOJA VIRTUAL | SEBRAETEC")
                changed = True
        if changed:
            parts[name] = serialize_xml(root, content)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(TARGET, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(parts):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, parts[name], compress_type=ZIP_DEFLATED, compresslevel=9)
    return TARGET


if __name__ == "__main__":
    print(build())
