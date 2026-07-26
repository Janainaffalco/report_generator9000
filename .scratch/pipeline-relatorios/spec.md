# Geração determinística de Relatórios Técnicos Finais — Inserção Digital / WebSite

Status: ready-for-agent

## Problem Statement

Every SEBRAETEC final report for the Tema `Inserção digital - Desenvolvimento de WebSite`
is produced today by opening a previous client's approved report, saving a copy, and
editing it by hand. The consultant retypes the Demanda, Razão Social, CNPJ and dates,
swaps roughly a dozen screenshots, deletes or duplicates whole sections depending on how
many pages the client's site has, and hand-adjusts the summary.

That process has four costs, and all four are visible in the artifact we have:

1. **It leaks between clients.** The approved ARGEL report contains a live hyperlink to a
   *different* client's WordPress admin panel, left behind by a previous copy-paste. The
   document a client signs points at a third party's credentials surface.
2. **The summary is wrong.** Its page numbers are hand-typed literals with no tab stops
   and hand-typed dot leaders, and it lists a section that does not exist (`2.10
   Indicadores`) while omitting two that do — including the Termo de Cessão de Direitos.
   A TOC field once existed and was destroyed; a single orphaned bookmark is all that
   remains of it.
3. **It drifts.** Because each report is edited from the last one, defects propagate and
   accumulate: a French word in a plugin description, a doubled URL prefix in the login
   instructions, a section that trails dot leaders to no page number at all.
4. **It does not scale.** There are 34 engagements on this Tema, of which 8 are
   immediately actionable, and each takes a consultant most of a day.

The consultant's real bottleneck is not writing — it is the mechanical work. Roughly 85%
of the document is substitution, screenshot swapping, and section arithmetic that a human
should not be doing by hand on a document a client legally signs.

## Solution

A Python CLI that produces a near-complete report package per engagement, which the
consultant opens in Word, completes, and signs off.

```
gerar_relatorio.py --linha 115-2026 [--gated ./gated/115-2026] [--no-llm]
```

Reports are cloned from a **Master** — a client-neutral base document built once from the
approved ARGEL report by a scripted, reviewable transformation, and signed off once. The
Master carries the visual identity (Montserrat, the cover shape, three header/footer
pairs), a live TOC field, and `{{TOKEN}}` markers where client values go. It contains no
client data at all. See ADR-0001.

Per engagement, the pipeline reads the row from the control spreadsheet, crawls the site
to derive its Lista de Páginas, captures screenshots, consumes whatever the consultant
left in the Gated Drop Folder, generates two paragraphs of grounded prose, and emits a
`.docx` plus a Pendências report naming everything still missing and why.

The deliverable is deliberately *not* a finished document. It is a draft that a consultant
finishes — which is what makes the honest handling of gaps the central feature rather than
an afterthought. The product promise is: **drop nine files into a folder, get a finished
report.**

## User Stories

### The Master

1. As a responsável pelo Master, I want the Master built by a script rather than by hand,
   so that I can re-derive it if the source document is re-sourced or a decision changes.
2. As a responsável pelo Master, I want a written diff of every change the build made to
   the approved document, so that I can review the deviations in one sitting instead of
   comparing two binaries.
3. As a responsável pelo Master, I want to open the Master in Word and see the summary,
   typography, and cover render correctly, so that I can sign it off on what I can see
   rather than on a description.
4. As a responsável pelo Master, I want the Master to contain no client data whatsoever,
   so that cross-client contamination is impossible by construction rather than caught by
   a check.
5. As a responsável pelo Master, I want the third party's `wp-admin` hyperlink removed at
   source, so that it can never be carried into a new client's contractual document.
6. As a responsável pelo Master, I want obvious typos corrected once, so that every future
   report is free of them without anyone re-fixing them per run.
7. As a responsável pelo Master, I want passages that appear to quote a normative source
   left untouched and flagged instead, so that we never silently misquote the Ficha
   Técnica SEBRAETEC.
8. As a responsável pelo Master, I want the orphaned summary entry escalated rather than
   silently dropped or silently kept, so that a human decides whether the section should
   exist.
9. As a desenvolvedor, I want the Master build to be re-runnable and its output diffable,
   so that changing a decision means editing a script rather than redoing manual work.

### Reading the engagement

10. As an operador, I want the pipeline to read the engagement's row from the control
    spreadsheet, so that I never retype the Demanda, Razão Social, CNPJ, Kick off, or
    Especialista.
11. As an operador, I want only rows on the in-scope Tema to be processed, so that Loja
    Virtual engagements are never generated from the wrong template.
12. As an operador, I want rows that already have a finished report to be skipped, so that
    a batch run never overwrites completed work.
13. As an operador, I want the CNPJ normalised to the standard formatting regardless of
    how it was typed in the spreadsheet, so that the cover and the Termo de Cessão read
    consistently.
14. As an operador, I want the Kick off datetime rendered in Brazilian date format, so
    that it matches the rest of the document.
15. As an operador, I want a row with no usable site URL to stop loudly rather than
    produce a partial report, so that I am never handed something that looks finished and
    is not.
16. As an operador, I want a row whose Link column contains a delivery date rather than a
    URL to be recognised as such and stopped, so that a type confusion in the spreadsheet
    never becomes a malformed report.
17. As an operador, I want a row with two domains concatenated in one cell to be parsed
    into its two parts rather than rejected, so that a known data-entry pattern does not
    cost me a report.
18. As an operador, I want a row with no Pasta to stop rather than write to an
    unpredictable output location.
19. As an operador, I want output directories keyed on both Pasta and Razão Social, so
    that two engagements sharing a Pasta number cannot collide.

### Domain handling

20. As a cliente, I want the domain named in my report to be the domain my site actually
    lives at, so that the wp-admin link in a document I signed still resolves next year.
21. As a consultor, I want the URL used for screenshots to be separable from the domain
    printed in the report, so that I can generate a report from a staging site before the
    real domain is pointed.
22. As a consultor, I want a missing Domínio Publicado to produce a visible placeholder
    and a Pendência, so that a temporary hosting slug can never be asserted as the
    client's address.
23. As a consultor, I want the wp-admin instructions built from the Domínio Publicado
    rather than the Capture Origin, so that the login URL I hand the client is the one
    that will keep working.

### Deriving the section structure

24. As a consultor, I want the report's screenshot sections derived from the client's
    actual site rather than from a previous client's, so that I am not deleting or
    duplicating blocks by hand.
25. As a consultor, I want pages reachable only from the site footer — privacy and cookie
    policies — to be included, so that the report matches what the approved model covers.
26. As a consultor, I want social links, mailto links and "developed by" credits excluded
    from the section list, so that the report does not sprout sections for things that are
    not pages.
27. As a consultor, I want links on other hosts excluded, so that a client portal on a
    different subdomain does not become a section of this report.
28. As a consultor, I want section headings named the way the approved model names them —
    the home page, main sections, and legal areas each following their own convention —
    so that the output reads as the same document.
29. As a consultor, I want Cabeçalho and Rodapé always present, so that the site chrome is
    documented regardless of what the crawl found.
30. As a consultor, I want to be able to declare the page list explicitly when the crawl
    gets it wrong, so that an unusual site shape costs me one line of configuration rather
    than a blocked report.
31. As a consultor, I want my declared page list to win over the crawl, so that I am never
    fighting the tool over a site I built myself.
32. As a consultor, I want the Briefing paragraph that lists the site's pages to be
    generated from the same list that produced the sections, so that the prose and the
    screenshots can never disagree.

### Capturing the site

33. As a consultor, I want screenshots taken at a resolution suitable for print, so that
    the report does not look degraded.
34. As a consultor, I want lazy-loaded content to be fully rendered before capture, so
    that hero images are not blank in the report.
35. As a consultor, I want cookie banners dismissed before capture where possible, so that
    every screenshot is not covered by a consent overlay.
36. As a consultor, I want a banner that cannot be dismissed without accepting to be
    captured as-is and flagged, so that I know why a screenshot looks wrong.
37. As a consultor, I want images fitted to the document's text column without stretching,
    so that the client's site is not shown distorted.
38. As a consultor, I want captures downscaled before embedding, so that the delivered
    file is not needlessly large.
39. As a consultor, I want a capture that silently failed to be detected automatically,
    so that a blank screenshot never reaches the client.

### Gated content

40. As a consultor, I want a per-engagement folder where I can drop the things automation
    cannot obtain, so that supplying them is a file copy rather than a document edit.
41. As a consultor, I want anything I did not supply to become a clearly marked
    placeholder, so that the gap is obvious to me and never mistaken for finished content.
42. As a consultor, I want a missing gated file to be normal rather than an error, so that
    I can generate a draft before I have gathered everything.
43. As a consultor, I want the same drop folder to carry values as well as images, so that
    the hosting plan, delivery dates, Drive links and client e-mail come from one place.
44. As a consultor, I want the credentials-handoff e-mail to come only from what I
    supplied, so that the report never asserts that a client's passwords went to an
    address scraped off their website.
45. As a consultor, I want the pipeline to read only my engagement's drop folder, so that
    another client's login screenshot cannot reach my report.

### The generated prose

46. As a consultor, I want the company description and briefing paragraph drafted from the
    site's own words, so that I am editing rather than writing from scratch.
47. As a cliente, I want nothing asserted about my company that does not come from my own
    site, so that the report I sign contains no invented claims.
48. As a consultor, I want the tool to tell me when the site had too little content to
    ground a paragraph, so that I write it myself rather than discovering an invented one
    later.
49. As a consultor, I want generated prose explicitly flagged for review in the Pendências
    report, so that I read it deliberately instead of skimming past it.
50. As a consultor, I want a mode that skips generation entirely and leaves marked gaps, so
    that I can produce a report with no model involvement at all.
51. As an operador, I want prose that was cut off mid-sentence to fail the run rather than
    ship, so that a truncated paragraph never reaches a signed document.
52. As a desenvolvedor, I want the model and its output budget to be configuration rather
    than constants, so that I can tune them from measured runs instead of guesses.

### Correctness gates

53. As a cliente, I want it to be structurally impossible for another client's screenshot
    to appear in my report, so that my report is about my business only.
54. As an operador, I want every image in the output to be traceable to boilerplate, this
    run's captures, or this run's drop folder, so that anything unaccounted for fails the
    build.
55. As an operador, I want every external link in the output to be either known
    boilerplate or derived from this engagement's inputs, so that no stray URL survives.
56. As an operador, I want any unfilled token to fail the build, so that a `{{...}}` marker
    never reaches a client.
57. As an operador, I want the run to fail if it read a drop folder belonging to a
    different engagement, so that a mis-keyed path is caught rather than shipped.
58. As an operador, I want every heading to be paired with its image, so that the document
    never contains a section title with nothing under it.
59. As an operador, I want a report that fails any gate to not be written at all, so that
    a broken artifact cannot be sent by mistake.

### The output package

60. As a consultor, I want a human-readable list of what is missing and why, so that I know
    exactly what to gather before sending.
61. As a consultor, I want gaps that are expected distinguished from gaps caused by a
    failure, so that I can tell what I need to fetch from what broke.
62. As a consultor, I want the same information in machine-readable form, so that it can
    drive a dashboard or a batch summary later.
63. As a consultor, I want the raw screenshots kept alongside the report, so that I can
    re-crop or re-use one without re-running the capture.
64. As a consultor, I want page previews of the finished document, so that I can eyeball
    the result without opening Word.
65. As an operador, I want a report containing any placeholder to never be described as
    complete or ready to send, so that nobody is misled by the tool's own output.

### Finishing in Word

66. As a consultor, I want the summary to recompute itself when I open the document, so
    that the page numbers are correct for this client's page count without me touching
    them.
67. As a consultor, I want the document to render in the correct typeface on any machine,
    so that a colleague without the fonts installed does not export a wrong-looking PDF.
68. As a consultor, I want a section heading to never sit alone at the bottom of a page
    separated from its screenshot, so that the document does not look hand-assembled.
69. As a consultor, I want to fill remaining gaps and export the signed PDF from Word, so
    that my existing workflow is unchanged from the point I take over.

## Implementation Decisions

### Architecture

- **Clone-and-substitute from a curated Master, never regenerate.** Reports are produced
  by scripted XML editing of a cloned Master package — never by building a document with a
  document-construction library, which would lose the Montserrat runs, the anchored cover
  shape, and the three header/footer pairs. This is ADR-0001.
- **The Master is a build artifact, not a hand-edited binary.** A dedicated build tool
  transforms the approved source document into the Master and emits a human-reviewable
  diff alongside it. A human opens the result in Word to sign off, but does not save over
  it — corrections are made by changing the build and re-running, so the Master stays
  reproducible.
- **Word is in the delivery path.** The pipeline emits a `.docx`; a consultant opens it,
  completes it, and exports the signed artifact. This removes any headless-office
  dependency from delivery. A render step remains available for optional QA only.
- **One in-scope Tema.** Only `Inserção digital - Desenvolvimento de WebSite` is
  generated. The Loja Virtual document is used as a structural reference for the TOC
  mechanism and heading styles, not as a generation template.

### The Master's construction

- Client values become named `{{TOKEN}}` markers, each occupying a single run. This
  eliminates run-defragmentation at generation time, per-variable occurrence assertions,
  and the class of bugs where a literal search string matched a different number of places
  than expected — or matched nothing because the text was split across elements.
- Section titles carry real heading styles, and the hand-typed summary is replaced with a
  TOC field at two levels, with field-updating enabled in document settings so Word
  recomputes it on open. Auto-numbering follows from the styles, which also fixes the
  point at which the original's numbering ran out.
- Nav-stamped Blocks are deliberately *not* heading-styled, so a client with a nine-item
  Lista de Páginas does not flood the summary and shift every page number.
- Two sections present in the body but absent from the summary are added. The orphaned
  summary entry and one passage that appears to quote a normative source are left
  untouched and escalated in the diff for a human ruling.
- A Block is canonicalised to **two paragraphs** — a heading bound to its image paragraph
  with keep-with-next — with spacing expressed as paragraph properties. The approved
  document's blocks vary from two to six paragraphs because the extra empty paragraphs are
  hand-pressed manual spacing; reproducing that variance would make block insertion and
  deletion unsafe. A spacer paragraph between heading and image is specifically excluded,
  because keep-with-next binds to the immediately following paragraph and would bind to
  the spacer.
- The three floating images that form a deliberate two-column composition, and the
  remaining anchored images, stay anchored. They are positioned relative to their host
  paragraph and therefore reflow correctly.
- Montserrat is embedded in the package and set in the style definitions. Both are
  required: the source document's styles all specify a different typeface and its
  appearance comes entirely from direct run formatting, so applying heading styles without
  fixing the style definitions would silently change the typeface of every heading.
- Client media is replaced with neutral stamps; the two boilerplate images (the SEBRAE
  header mark and the platform logo) are retained.
- The third-party admin hyperlink is deleted along with its relationship entry, and six
  textual defects are corrected.

### Inputs

- **The control spreadsheet** is the source for Demanda, Pasta, Tema, CNPJ, Razão Social,
  Especialista and Kick off. Header strings contain irregular whitespace and must be
  matched by position or normalised. The Link column is overloaded and holds either a URL
  or a datetime; every cell is type-checked, and a non-URL value is a Stop Condition.
- **Capture Origin and Domínio Publicado are separate concepts.** The spreadsheet's Link
  column supplies only the Capture Origin — where to screenshot from. The domain the
  report declares comes from the Gated Drop Folder. Six of the eight currently actionable
  rows point at disposable preview subdomains, and one row has both values jammed into a
  single cell; treating them as one value would print a temporary hosting slug as the
  client's address in a contractual document.
- **The Gated Drop Folder** supplies the nine unobtainable images plus a values file
  carrying the hosting plan, client e-mail, delivery and backup dates, the Drive links, and
  the Domínio Publicado. Absence is never an error — it produces a Placeholder and a
  Pendência.
- CNPJ is normalised to the standard mask. One current row supplies it unformatted.

### Deriving the Lista de Páginas

The Lista de Páginas is assembled from three distinct sources rather than from "the nav",
because the approved model demonstrably draws on all three:

- **Página Principal** — from the main menu, presented as a section heading, with the home
  page following its own convention.
- **Área Legal** — from footer links, presented under its own label with no prefix. Social
  links, mail and telephone links, and attribution links are filtered out. A crawl of the
  main menu alone would miss these entirely; the approved model includes one.
- **Elemento Transversal** — Cabeçalho and Rodapé, always appended, never discovered.

A declared list in the Gated Drop Folder overrides the crawl entirely. This is the escape
hatch for one-page sites with anchor navigation, hamburger-only menus, and unusual shapes,
replacing an unconditional Stop Condition with a deterministic answer the consultant
controls. The Briefing paragraph naming the site's pages is generated from this same list,
so prose and Blocks agree by construction — the approved model violates its own ordering
rule, which is exactly the failure this removes.

### Capture

- Screenshots are taken at a viewport and device scale factor sufficient for print
  density. Lazy-loaded content is forced to render by scrolling to the bottom, waiting for
  network idle, and scrolling back before capture.
- A dismissal selector list handles common consent frameworks, always declining
  non-essential cookies. A banner that cannot be dismissed without accepting is captured
  visible and flagged.
- Images hold the slot width and recompute height from the real aspect ratio — never
  stretched — and are downscaled before embedding.
- Failed lazy-load is detected by a colour-count threshold, which separates cleanly in
  measurement between a blank capture and a rendered page.

### The generated prose

- The model authors only the company description and the objective clause of the first
  briefing paragraph. The second briefing paragraph is a deterministic template filled from
  the Lista de Páginas. This roughly halves the surface on which the document can assert
  something untrue, and removes a constraint that the approved model itself breaks.
- The model is Haiku-tier, chosen deliberately: this is grounded rewriting of text the
  pipeline already extracted, and the task was previously performed by a mid-tier general
  assistant. Both the model identifier and the output budget are configuration values.
- The output budget is to be set from measurement, not assumption. The approved model's two
  paragraphs total roughly 124 tokens; the equivalent section of the sibling report runs to
  roughly 360. The provisional budget is generous, to be tightened from observed usage
  across the real sites. A response that hit the budget is a hard failure classified as a
  tool failure, never a shipped partial paragraph.
- Input is script-extracted page text — never raw markup. No outside research: no company
  registries, news, or social profiles. Unverifiable and out of scope.

The response is constrained to a schema, so "the site had too little content" is a value
the pipeline branches on rather than an instruction we hope was honoured:

```
sobre_empresa:          string | null
sobre_fundamentado:     boolean
briefing_objetivo:      string | null
briefing_fundamentado:  boolean
```

An unset flag or null value produces a marked gap and a Pendência, never invented prose.

### Correctness gates

The anti-contamination check is **Provenance**, not keyword matching. With a
client-neutral Master, searching output for a previous client's name is a tautology that
can never fire — while the real risk has moved to cross-*run* contamination: a stale
working directory, a mis-keyed drop folder, a reused capture. The gates are therefore:

- Every media file traces by digest to the boilerplate allowlist, this run's captures, or
  this run's drop folder. Anything else fails.
- Every external link target is either known boilerplate or derived from this row's inputs.
- No unreplaced token survives in any part of the package.
- The drop folder read matches this engagement, and every output path carries its Pasta.
- Every heading is paired with an image; no orphaned relationships or unreferenced media.
- The Pendências report and the document agree in both directions.

The same gate module validates the Master itself at build time, so the rules are expressed
once and serve as both the Master's acceptance criteria and the per-report check.

### Placeholders and Pendências

Two Placeholder classes are kept strictly distinct in the manifest, in the human-readable
report, and in the caption rendered into the placeholder image itself: content that was
structurally unobtainable and is awaiting a human, versus content that should have been
captured and was not. Conflating them makes the gap report useless — a reader cannot tell
what to go and fetch from what broke.

### Output package

Per engagement: the document, a human-readable Pendências report, a machine-readable
manifest carrying slot, name, page, class, reason and required action, page previews, and
the raw captures at native resolution. Output containing any Placeholder is never described
as complete or ready to send.

### Non-negotiables carried forward

- Never authenticate to anything — no CMS, host, cloud drive, or collaboration tool, and
  no credentials from any source.
- Never reuse another engagement's Capture, and never synthesise, mock, or generate a
  substitute for one.
- Never infer a Gated Input from what it usually is.

## Testing Decisions

**What makes a good test here:** it drives the real entry point and asserts on the produced
artifact. The two things this system emits — the Master, and the per-engagement package —
are both files, which is the highest possible place to observe behaviour. A test that
reaches into a module to check how substitution was performed is testing implementation;
a test that opens the resulting document and asserts that no token survived is testing
behaviour. Prefer the latter without exception.

**Seams.** Exactly one, confirmed with the developer:

- **The prose provider** is swappable. Tests supply canned structured responses covering
  the grounded case, the ungrounded case, and the budget-exhausted case, so the LLM
  contract is exercised without network access or spend. This is nearly free because a
  no-model mode is already a required product feature.

Everything else is controlled by *environment* rather than by injected code:

- **Site capture** runs the real browser automation against a fixture site served over
  local HTTP. Real navigation, real lazy-load handling, real consent-banner dismissal,
  deterministic content. Making capture injectable was considered and rejected: it would
  leave precisely the fragile parts — lazy loading, cookie banners, aspect-ratio
  preservation — permanently untested.
- **The spreadsheet** is a fixture workbook exercising every Stop Condition: URL rows,
  datetime rows, empty rows, the concatenated-domain row, the unformatted-CNPJ row, the
  already-complete row, and the missing-Pasta row.
- **The Gated Drop Folder** is a fixture directory, run in several states: complete,
  entirely absent, and partially populated.

**What is asserted on the Master:** no data from the source client survives in any part;
the summary is a real field rather than literal text; field updating is enabled; the fonts
are embedded and named in the style definitions; every expected token is present exactly
where expected; the third-party link and its relationship are gone; every Block is
well-formed with its heading bound to its image; the package opens as a valid document.

**What is asserted on an engagement package:** no token survives; the number of Blocks
equals the length of the derived Lista de Páginas and their headings follow the naming
conventions; every media digest is accounted for by Provenance; every external link is
boilerplate or derived; the declared domain is the Gated value and never the Capture
Origin; Placeholders and the Pendências report agree in both directions and carry the
correct class; and a package that fails any gate is not written at all.

**Coverage the fixtures must force**, since these are the failure modes the design exists
to prevent: a mis-keyed drop folder must fail rather than produce a report; a
budget-exhausted prose response must fail rather than ship; an ungrounded prose response
must produce a marked gap rather than invented text; a staging Capture Origin with no
declared domain must produce a placeholder rather than print the hosting slug; and a
declared page list must override the crawl.

**Prior art:** none — the repository currently contains no code. These tests establish the
convention, so they should be written to be worth imitating.

## Out of Scope

- **Loja Virtual reports** (20 rows). The document is used as a structural reference for
  the TOC mechanism only. It is a genuinely different report type with its own section
  grammar — different Etapas, an Entregáveis section, product listings — and would need
  its own Master and its own grammar. Six rows are currently actionable, so this is the
  most likely next increment, but it is not this spec.
- **Marketing themes** (separate sheet, different schema).
- **Restructuring the control spreadsheet.** The overloaded Link column is worked around
  by splitting Capture Origin from Domínio Publicado rather than by changing the sheet.
  Splitting it into two columns, as the Marketing sheet already does, remains the right
  long-term fix and is recommended separately.
- **Producing the final PDF.** The consultant exports and signs from Word.
- **Headless-office rendering as a delivery dependency.** It stays optional, for QA
  previews and page-count checks only, and is not installed as part of the core setup.
- **Any authenticated capture.** The nine gated images exist precisely because they sit
  behind logins, and the drop folder is the answer.
- **Automated visual judgement.** Failed captures are detected by measurable heuristics.
  Sampled human review of pages carrying new captures remains optional and manual.
- **Batch orchestration and scheduling.** The entry point handles one engagement.

## Further Notes

**Two rulings are still open and belong in the Master sign-off.** Neither blocks
implementation; both should be resolved before the Master is approved:

1. Whether the orphaned summary entry `2.10 Indicadores` should be dropped from the
   summary or given a real body section.
2. Whether the agreement errors in the passage citing the Ficha Técnica SEBRAETEC are
   faithful to that source. If they are, the passage must stay exactly as written; if they
   are not, it should be corrected with the other textual fixes. The build leaves it
   untouched and flags it either way.

**On the provenance of the source document.** The approved report in the repository is a
re-save by a headless office suite, not the original Word file: revision identifiers are
stripped, several parts are absent, and its styles were rewritten. Its Word-native sibling
retains the heading styles and live summary field that this one has lost, and a single
orphaned bookmark is all that remains of the destroyed field. If a clean pre-client master
authored by the original template owner is ever located, it is a strictly better build
source and the build should be re-pointed at it — the transformation itself would largely
survive.

**On sequencing.** The Master is on the critical path and is the only step containing human
review latency, so it should be started first; the spreadsheet reader has no dependencies
and can be built alongside while the Master is in review. The milestone that proves the
concept is opening the built Master in Word and seeing a correct summary, correct
typography, and no trace of the source client.

**On the output budget.** It is deliberately left as configuration rather than fixed here.
Set it from measured usage across the real sites, not from the figure in the superseded
architecture brief — that figure was derived before the model landscape and the prose scope
were settled, and it is roughly twice the approved model's actual length with no headroom
for a client with a richer story.

**Reference material.** The superseded architecture brief remains useful for the
document-internals reconnaissance it captured — the relationship map, slot inventory, and
page setup are accurate and should not be re-derived. Three of its claims did not survive
verification and are corrected in this spec: the uniform three-paragraph Block anatomy, the
requirement that the generated page-list paragraph follow navigation order, and the
instruction to reproduce the summary as-is.
