---
status: accepted
---

# A Loja Virtual Gated Input is labelled, refused, or left as a Pendência

`Implantação de Loja Virtual` depends on records no automation can reach: the admin
`LISTA DE PRODUTOS`, the WordPress login and painel screenshots, the payment and
delivery configuration screens, the meeting prints, the delivery dates, and the Drive
links naming the declared deliverables. The report is contractual, so each of those has
exactly three honest outcomes, and this record fixes which one applies when.

**Labelled.** Every administrative Gated image Slot in the curated Master is bound to
its own `keepNext` label paragraph, and the contract declares that label in
`tema.py:LOJA_GATED_SLOT_LABELS`. Before this, `generate.py` resolved a Slot's page by
walking back to the nearest `keepNext` paragraph carrying text, and in the Loja Master
that walk landed on the Block heading `RODAPÉ` for all eight administrative Slots —
three of which shared a single paragraph and had no label at all. Every GATED Pendência
therefore told the consultant a missing admin screenshot belonged to the Rodapé.
`PENDENCIAS.md` is the artefact a consultant acts on without opening Word, so a Slot
whose gap cannot be named there is not a Gated Input; it is a guess about one. The
walk-back itself moved to `docx_package.media_location`, so the Master's sign-off gate
and the report path resolve a Slot's label through the same code.

**Refused.** The app never handles WordPress or Drive credentials. A credential-bearing
key in `valores.json` or a credential-bearing filename in the Gated Drop Folder is
rejected by name at load time, before the generic unknown-field check, because the
generic message reads like a typo rather than a refusal and a consultant who reads it
that way will try again. `configuracao_woocommerce` is accepted as a Slot but never
inserted automatically: freeform private configuration is a Word edit during review.
`link_usuarios_senhas` remains a legitimate declared link for the WebSite Tema, so the
refusal is scoped to slots the Tema's contract does not declare rather than to a second
vocabulary of forbidden words.

Drive links are accepted only as consultant-supplied declarations with a validated
`https://drive.google.com/<path>` shape. The pipeline never authenticates and never
asserts anything about what a link contains — the Master presents the Slot as
`COMPARTILHAMENTO DECLARADO PELO CONSULTOR` for exactly that reason.

**Pending.** Anything absent produces a classified Placeholder and a matching Pendência
naming the label, and the Run is a draft. A later attachment re-enters the same
unattended path: `POST /api/runs/{id}/attachments` validates the upload against this
Pasta's Gated Drop Folder, copies it in, and submits a fresh Run that passes every
Stage. Nothing about a rerun is partial and nothing about it asks a human a question.

## Consequences

The `loja-handover-claims` gate rejects language claiming a deliverable, right, backup,
training session or receipt was handed over when this Run evidences none of it, and
rejects the filled reference report's day-counted retention promise for its Drive link.
It runs on the report, not only on the Master, because Gated Input text reaches the
document too. Its patterns are deliberately narrow — the Master's own hedged sentences
(`sem presunção de treinamento realizado`, `registra o recebimento dos materiais e
orientações comprovados neste relatório`) must keep passing — which means the gate
catches the specific claims we know the reference made, not every possible overclaim.
It is a ratchet against reproducing known bad language, not a proof of honesty.

`gated_slot_labels` is empty for the WebSite Tema, which keeps naming its Pendências
after the Slot. That asymmetry is deliberate: relabelling the WebSite grammar would
change every existing `PENDENCIAS.md` for a Tema whose Master is signed off and whose
consultants already read it.
