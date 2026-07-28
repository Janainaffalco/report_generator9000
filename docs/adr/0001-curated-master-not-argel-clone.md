---
status: accepted
---

# Reports are generated from a curated Master, not by cloning RELATÓRIO ARGEL.docx

The prior architecture brief made "clone the ARGEL binary and substitute strings" a
non-negotiable, on the reasoning that rebuilding the document would lose its Montserrat
runs, cover shape, and header/footer pairs. Inspecting the binary showed the premise was
sound but the chosen source was not: the ARGEL file in the repository is a LibreOffice
re-save (`Application: LibreOffice/24.2.7.2`, all 1195 rsids stripped, `footnotes`/
`endnotes`/`webSettings` parts dropped) whose Word-native sibling still carries the
`Título1`/`Título2` styles and live `TOC` field that ARGEL has lost — ARGEL retains one
orphaned `_Toc59035` bookmark as the only trace. **We therefore build `MASTER.docx` once
from ARGEL via a scripted, reviewable transformation, obtain sign-off on it once, and
clone that Master for every report.** Clone-and-substitute still holds; only the source
changes, from a damaged filled instance to a client-neutral base.

## Consequences

The decisive argument is not fidelity but correctness. Section blocks are generated per
client from the site's Lista de Páginas, and the accepted page-count range is 15–19 — so a
summary carrying ARGEL's hand-typed page numbers (`Objetivo 3`, `REUNIÕES 16`, with
hand-typed dot leaders and zero tab stops) is **wrong for essentially every client**. The
summary is the one region that cannot be cloned, because its content is a function of
pagination, which is a function of content we generate. A real `TOC` field marked
`w:dirty="true"` recomputes it silently when the consultant opens the file in Word,
without the "this document contains fields that may refer to other files" prompt a
document-wide `updateFields` setting forces on every open.

Three further things follow from owning the Master, none of which were available while
cloning a filled instance:

- Client values become `{{TOKEN}}`s in single runs, so `merge_runs.py` drops to a
  build-time tool and the per-variable occurrence assertions disappear along with the
  bugs they were built to catch.
- Anti-contamination stops being keyword detection and becomes Provenance: the Master
  contains no client data by construction, so every artifact in an output must trace to
  Boilerplate, this run's Captures, or this run's Gated Inputs.
- `rId25`, a live hyperlink to a third party's `wp-admin`, is removed at source rather
  than being re-decided on every run.

The cost is that the Master is not byte-identical to the approved artifact: it also
carries six typo corrections and a repaired login URL. That diff is generated as
`MASTER-DIFF.md` for a single human review. The owner ruled that the orphaned hand-typed
`2.10 Indicadores` entry is removed with the literal summary because it has no body
section; the live Heading 2 range therefore ends at `2.10 ORIENTAÇÕES AO CLIENTE`.
The passage whose agreement errors appear to quote the Ficha Técnica SEBRAETEC 4.0
verbatim remains escalated, because silently correcting it would misquote a normative
source.
