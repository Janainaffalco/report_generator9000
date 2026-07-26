# Geração de Relatórios SEBRAETEC

Produces the final technical report (`RELATÓRIO TÉCNICO FINAL`) that SEBRAETEC delivers to a
client at the close of a consultancy engagement. The report is a contractual document the
client's legal representative signs, so every statement in it must be traceable to an
observed fact or an explicitly supplied input.

## Language

### Engagement

**Demanda**:
The engagement identifier issued by SEBRAETEC, e.g. `013292/2026`. Appears on the cover.
_Avoid_: ticket, job, order

**Pasta**:
The folder number tracking an engagement, e.g. `115-2026`. Names the output directory and is
how a human refers to a run.
_Avoid_: linha, row id

**Tema**:
The contracted service type, taken verbatim from the control spreadsheet. Two exist:
`Inserção digital - Desenvolvimento de WebSite` and `Implantação de Loja Virtual`. Only the
former is in scope; each Tema needs its own Master and its own section grammar.
_Avoid_: report type, category

**Especialista**:
The consultant responsible for the engagement, named on the cover.
_Avoid_: author, owner

### The document

**Master**:
The single client-neutral base document every report is cloned from. Contains no client data
— only Tokens, boilerplate, and the styles/headers/footers/cover shape that carry the visual
identity. Authored once by a human, signed off once, then never edited per client.
_Avoid_: template, base document, modelo

**Token**:
A `{{NOME}}` marker in the Master occupying exactly one run, replaced at generation time.
Distinct from a Slot: a Token is text, a Slot is an image.
_Avoid_: variable, placeholder, merge field

**Slot**:
A position in the Master that holds an image, with fixed dimensions inherited from the
approved layout. Each Slot is filled by a Capture, by a Gated Input, or by a Placeholder.
_Avoid_: image position, figure

**Block**:
The two-paragraph unit that presents one screenshot: a heading bound to an image paragraph.
Blocks are inserted and deleted whole. Whitespace around a Block is paragraph spacing, never
an empty paragraph — an empty paragraph between heading and image would break the binding and
allow a heading to be stranded at a page foot.
_Avoid_: section, triple, group

**Lista de Páginas**:
The ordered set of things that earn a Block in a given report, assembled from three distinct
sources rather than from "the nav" alone. Generated once per run and used for both the Blocks
and the Briefing prose, so the two can never disagree.
_Avoid_: nav, menu, sitemap

**Página Principal**:
A page reachable from the site's main menu, presented as `SEÇÃO <LABEL>` — except the home
page, which is `PÁGINA HOME`.

**Área Legal**:
A policy page reachable only from the footer, such as Política de Privacidade or Política de
Cookies. Presented under its own label with no prefix. Distinct from a Página Principal
because crawling the main menu will never find it.
_Avoid_: footer page, policy page

**Elemento Transversal**:
Site chrome that appears on every page and belongs to no single one — Cabeçalho and Rodapé.
Always captured, never discovered, never named in the Briefing prose.
_Avoid_: header/footer block

**Boilerplate**:
Content identical in every report — the SEBRAE header logo, the WordPress explanation, the
plugin reference URLs. Never substituted, never a leak risk.

### Sources of truth

**Capture Origin**:
The URL the pipeline screenshots and crawls. Often a temporary Hostinger preview domain and
therefore **not** something the report may quote as the client's address.
_Avoid_: site url, link, domain

**Domínio Publicado**:
The domain the report declares as the client's, and the base of the wp-admin link. Supplied
as a Gated Input; never inferred from the Capture Origin. Absent means Placeholder, never a
guess.
_Avoid_: domain, url

**Capture**:
A screenshot the pipeline takes of a live page at the Capture Origin. Never reused across
engagements, never synthesised, never AI-generated.
_Avoid_: screenshot, print, image

**Gated Input**:
A value or image that no automation may obtain — anything behind authentication, inside
Teams, or existing only in a consultant's records. Supplied by a human via the drop folder.
_Avoid_: manual input, missing data

**Gated Drop Folder**:
The per-engagement directory a consultant fills with Gated Inputs before a run. Its contents
are consumed if present; absence is normal and never an error.

### Gaps

**Placeholder**:
A generated image or text marker standing in for content that is absent, always carrying its
class so a reader can tell a deliberate gap from a failure.

**GATED**:
Placeholder class meaning the content was structurally unobtainable and a human must supply
it. Expected; not a defect.

**TOOL_BLOCKED**:
Placeholder class meaning the content should have been captured automatically but the
attempt failed. Always a defect requiring investigation.

**Provenance**:
The record of where each artifact in a finished report came from — Boilerplate, a Capture from
this run, or a Gated Input from this run's drop folder. Anything present in an output without
Provenance is contamination by definition, regardless of what it contains.
_Avoid_: audit trail, source tracking

**Stop Condition**:
A precondition that fails loudly and abandons the row rather than guessing — a missing
Capture Origin, an unparseable nav, a Tema out of scope. Producing nothing is correct;
producing something invented is not.
_Avoid_: error, skip, validation failure

**Pendência**:
An outstanding item preventing the report from being complete, recorded for the consultant in
both `PENDENCIAS.md` and `pendencias.json`. A report with any Pendência is never described as
complete or ready to send.
_Avoid_: todo, issue, gap
