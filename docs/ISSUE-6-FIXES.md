# Issue #6 — human review defects and fix plan

Source: [#6 comment of 2026-07-28](https://github.com/seriouslyvictor/report_generator9000/issues/6#issuecomment-5107419626)
(six screenshots of `MASTER.docx` opened in desktop Word).

Nothing in this document has been fixed. Every finding below was reproduced against a
Master built from `RELATÓRIO ARGEL.docx` at HEAD (`1312087`), not against the stale
`review-artifacts/current-master-2026-07-27/MASTER.docx`. The `master-build` gate passes
on that build, so each finding is also a gate blind spot.

## What the reviewer saw, mapped to a cause

| # | Screenshot | Cause | Section |
|---|---|---|---|
| 1 | "Word found unreadable content in MASTER.docx" | `word/numbering.xml` violates the OOXML element sequence | [A](#a-schema-order-violations) |
| 2 | "This document contains fields that may refer to other files" | `w:updateFields` is a global setting and always prompts | [D1](#d-toc-field-and-the-update-prompt) |
| 3 | Show Repairs → a list of `Lists 1 … Lists N` | same as 1 — Word discards and rebuilds every list definition | [A1](#a1-abstractnum-900-is-appended-after-every-num) |
| 4 | Stray `Ficha Técnica SEBRAETEC 4.0 – Pág. 3` on page 3 | literal hand-typed text inherited from the source | [E1](#e1-stray-hand-typed-page-reference) |
| 5 | `CABEÇALHO` block bleeding past the right margin | the block image is 7.09 in wide in a 5.91 in column | [E2](#e2-cabeçalho-block-image-overflows-the-text-column) |
| 6 | `3……………T / ERMO DE CESSÃO DE DIREITOS` | numbering tab lands on a leftover dot-leader tab stop | [C4](#c4-the-numbering-tab-lands-on-a-leftover-dot-leader-tab-stop) |

Screenshot 6 also exposes the numbering being wrong at all (`3`, not `4`) — see [C1](#c1-direct-wnumpr-on-the-headings-overrides-the-style)/[C2](#c2-consequence-the-heading-1-sequence-skips-declaração).

---

## A. Schema-order violations

**Root cause, common to all of A.** `master.py` builds XML with
`ElementTree.SubElement`, which always *appends*. Every OOXML complex type in play is an
ordered `xsd:sequence`, so appending to an existing element usually produces invalid XML.
Word's response is to repair (dropping the offending content) or to refuse the part.

The fix for A1–A5 individually is to insert at the schema position; the durable fix is a
single helper.

### A6. Add an ordered-insert helper (do this first)

```python
def _ordered_child(parent, tag, order):
    """Return parent's `tag` child, inserting it at its schema position if absent."""
```

`order` is the local-name sequence for the parent's complex type. Route every current
`SubElement`-on-an-existing-parent call in `master.py` through it. Then A1–A5 become
mechanical. Sequences needed (ECMA-376 Part 1, §17):

- `CT_Numbering`: `numPicBullet*, abstractNum*, num*, numIdMacAtCleanup?`
- `CT_Lvl`: `start?, numFmt?, lvlRestart?, pStyle?, isLgl?, suff?, lvlText?, lvlPicBulletId?, legacy?, lvlJc?, pPr?, rPr?`
- `CT_PPrBase` (+ `rPr?`, `sectPr?`, `pPrChange?` last): `pStyle, keepNext, keepLines, pageBreakBefore, framePr, widowControl, numPr, suppressLineNumbers, pBdr, shd, tabs, suppressAutoHyphens, kinsoku, wordWrap, overflowPunct, topLinePunct, autoSpaceDE, autoSpaceDN, bidi, adjustRightInd, snapToGrid, spacing, ind, contextualSpacing, mirrorIndents, suppressOverlap, jc, textDirection, textAlignment, textboxTightWrap, outlineLvl, divId, cnfStyle`
- `CT_Style`: `name, aliases, basedOn, next, link, autoRedefine, hidden, uiPriority, semiHidden, unhideWhenUsed, qFormat, locked, personal, personalCompose, personalReply, rsid, pPr, rPr, tblPr, trPr, tcPr, tblStylePr*`
- `CT_Settings`: `updateFields` sits between `alwaysMergeEmptyNamespace` and `hdrShapeDefaults`, i.e. **before** `footnotePr`, `endnotePr`, `compat`, `rsids`, `themeFontLang`

### A1. `abstractNum` 900 is appended after every `num`

`master.py:531` — `_ensure_numbering` does `SubElement(numbering, w:abstractNum)` on a
`numbering.xml` that already carries 12 `abstractNum` and 12 `num` elements. Observed root
child order in the built Master:

```
abstractNum ×12, num ×12, abstractNum(900), num(900)
```

`CT_Numbering` requires all `abstractNum` before all `num`. **This is the confirmed cause
of screenshots 1 and 3** — the Show Repairs list contains only `Lists N` entries, which is
Word discarding and regenerating the whole numbering part.

**Fix.** Insert `abstractNum` 900 immediately after the last existing `abstractNum`;
append `num` 900 after the last existing `num`.

### A2. `pStyle` emitted after `lvlText` inside `w:lvl`

`master.py:537-546` emits `start, numFmt, lvlText, pStyle`. `CT_Lvl` requires `pStyle`
*before* `lvlText`. Both levels are affected.

**Fix.** Emit `start, numFmt, pStyle, suff, lvlText, lvlJc, pPr` — see [C3](#c3-abstractnum-900-is-missing-suff-lvljc-and-indentation) for the added children.

### A3. `w:numPr` appended after `w:outlineLvl` in the heading styles

`master.py:702-712`. Observed `w:pPr` child order:

- `Heading1`: `keepNext, keepLines, widowControl, suppressAutoHyphens, bidi, spacing, ind, jc, outlineLvl, numPr`
- `Heading2`: `keepNext, keepLines, spacing, outlineLvl, numPr`

`numPr` must precede `spacing`, `ind`, `jc` and `outlineLvl`.

**Fix.** Insert `numPr` at its `CT_PPrBase` position. Note `_add_signoff_structure` also
appends `outlineLvl` (`master.py:690-693`) and `w:name` (`master.py:683-686`) when absent —
same treatment.

### A4. `w:keepNext` appended after `w:rPr` on the eight Block headings

`master.py:313-316` in `_canonicalize_blocks`. Observed on all eight:

```
pStyle, tabs, spacing, ind, jc, rPr, keepNext
```

`w:rPr` must be the last `CT_PPrBase` child. `keepNext` must be second, right after
`pStyle`.

**Fix.** Ordered insert. Same applies to `_set_spacing` (`master.py:230-238`) and
`_set_heading` (`master.py:222-227`) whenever the element is absent — currently latent
because `pStyle`/`spacing` happen to already exist on the paragraphs touched.

### A5. `w:updateFields` appended at the end of `settings.xml`

`master.py:662-667`. Observed order: `zoom, defaultTabStop, autoHyphenation,
hyphenationZone, compat, themeFontLang, updateFields`. Invalid — `updateFields` belongs
before `compat`. Word currently tolerates it (the prompt does fire), but it is invalid and
will not survive a stricter consumer. Superseded in part by [D1](#d-toc-field-and-the-update-prompt).

### A7. Add a schema-order check to the gate

`gates/master.py` validates content but never structure. Add a `_check_sequence(part,
complex_type)` assertion over `numbering.xml`, `styles.xml`, `settings.xml` and every
`w:pPr` in `document.xml`. Ideally validate against the ECMA-376 transitional `.xsd`
outright; a hand-written sequence checker for the five types above is the cheap version
and catches everything in section A.

---

## B. Embedded fonts

### B1. `Montserrat-wght.ttf` is a variable font whose default instance is *Thin*

`report_generator9000/assets/Montserrat-wght.ttf` (745 KB) contains `fvar`, `gvar`,
`avar`, `cvar`, `HVAR`, `MVAR`, `STAT` — it is a variable font. Its `name` table reads:

| name ID | value |
|---|---|
| 1 (family) | `Montserrat Thin` |
| 2 (subfamily) | `Regular` |
| 4 (full name) | `Montserrat Thin` |
| 16 (typographic family) | `Montserrat` |
| 17 (typographic subfamily) | `Thin` |

Two problems. Word does not consume variable fonts as embedded fonts (it expects a static
face per `embedRegular`/`embedBold`/`embedItalic`/`embedBoldItalic`). And the face's
internal family name is `Montserrat Thin`, which matches none of the five `w:font w:name`
values declared in `fontTable.xml`. A colleague without Montserrat installed will get
either a fallback face or the Thin default instance — the "renders correctly on a machine
without the fonts" criterion is not met, and this is a candidate co-cause of screenshot 1
independent of section A.

**Fix.** Ship static instances. At minimum `Montserrat-Regular.ttf` and
`Montserrat-Medium.ttf` (the document's headings ask for `Montserrat Medium` by direct run
formatting), plus Bold if any run uses it. Instance them from the variable font with
`fonttools varLib.instancer` at build time, or vendor the static releases from the upstream
repo, and update `assets/FONT-SOURCE.md` and the provenance SHA-256 accordingly.

### B2. Five identical copies of the same bytes

`master.py:736-757` writes the same `obfuscated` buffer to five parts
(`montserrat-0..4.odttf`), one per declared face, each as `embedRegular`. That is ~3.7 MB
of duplicate payload before compression, and it makes `Montserrat Black`,
`Montserrat Light` etc. resolve to whatever `Montserrat-wght.ttf`'s default instance is.

**Fix.** One part per real face; drop faces the document never uses. Verify by collecting
the distinct `w:rFonts/@w:ascii` values actually present in `document.xml`, the headers and
the footers, and embedding exactly those.

### B3. `Heading2` names Montserrat *and* a theme font — the theme wins

`master.py:697-701` sets `w:ascii="Montserrat"` on the existing `w:rFonts`, but the stock
`Heading2` already carries `w:asciiTheme="majorHAnsi"`, `w:hAnsiTheme`, `w:eastAsiaTheme`,
`w:cstheme`. Per §17.3.2.26 the theme attributes take precedence, so `Heading2` does **not**
resolve to Montserrat. `Heading1` has no theme attributes and is fine.

The gate (`gates/master.py`, `heading-style-not-linked`) only asserts
`fonts.get(w:ascii) == "Montserrat"`, so it passes on a style that renders in a different
typeface. This is the exact failure mode the issue body warned about.

**Fix.** Remove the four `*Theme` attributes when setting the family, and tighten the gate
to assert their absence.

### B4. `Heading2` still carries Word's stock blue

`Heading2` keeps `<w:color w:themeColor="accent1" w:themeShade="bf" w:val="2F5496"/>` from
the built-in style. Every heading in the approved source renders `404040` grey by direct
run formatting, so this is masked today — but it will surface on any heading whose direct
formatting is dropped.

**Fix.** Set the heading style colour to the document's `404040`, and stop relying on
direct run formatting to hide it.

---

## C. Heading numbering

### C1. Direct `w:numPr` on the headings overrides the style

`_add_signoff_structure` (`master.py:646-659`) resets `pStyle` to `Normal`, then assigns
`Heading1`/`Heading2` to the canonical paragraphs — but it never strips the **direct**
`w:numPr` those paragraphs inherit from the source. Direct paragraph properties beat style
properties, so `numId 900` never applies to them. Measured on the HEAD build:

| Heading | style | direct `numId` | dot-leader tab |
|---|---|---|---|
| BRIEFING INICIAL PARA DEFINIÇÃO DO ESCOPO | Heading1 | — | no |
| SOBRE A EMPRESA | Heading2 | **1** | yes |
| BRIEFING | Heading2 | **1** | yes |
| DESENVOLVIMENTO DE WEBSITE | Heading1 | — | no |
| OBJETIVO … ORIENTAÇÕES AO CLIENTE (10×) | Heading2 | **3** | yes |
| DECLARAÇÃO DE RECEBIMENTO E FINALIZAÇÃO | Heading1 | **3** (ilvl 1) | yes |
| TERMO DE CESSÃO DE DIREITOS | Heading1 | — | yes |
| REUNIÕES | Heading1 | — | no |

12 of 17 canonical headings are on the wrong list. The "auto-numbering follows from the
styles" acceptance criterion is structurally satisfied and functionally not.

**Fix.** In the loop at `master.py:650`, remove `w:pPr/w:numPr` from each canonical
heading after setting `pStyle`, and add a gate assertion that no `Heading1`/`Heading2`
paragraph carries a direct `w:numPr`.

### C2. Consequence: the Heading 1 sequence skips DECLARAÇÃO

Only the four Heading 1s without a direct `numPr` draw from list 900, so Word numbers:

```
1  BRIEFING INICIAL…      2  DESENVOLVIMENTO…
   DECLARAÇÃO…  ← on list 3, outside the sequence
3  TERMO DE CESSÃO…       4  REUNIÕES
```

That is the `3` in screenshot 6. Fixing C1 makes it `1, 2, 3 DECLARAÇÃO, 4 TERMO,
5 REUNIÕES`. **This changes the numbering the owner ruled on in the #6 comment thread**
(the 2.10-vs-2.11 decision was made against the current, broken sequence) — re-confirm the
intended Heading 1 range before shipping, and update `docs/adr/0001` and `MASTER-DIFF.md`
to match.

### C3. `abstractNum` 900 is missing `suff`, `lvlJc` and indentation

`master.py:537-546` emits only `start`, `numFmt`, `lvlText`, `pStyle`. Absent `w:suff`,
the default is `tab` — Word inserts a tab character between the number and the heading
text. There is also no `w:lvlJc` and no `w:pPr/w:ind`, so the number has no reserved
indent. `Heading1`'s own `w:ind w:start="370" w:hanging="10"` reserves 10 twips, which
cannot hold a number.

**Fix.** Per level, emit `suff` (`space` is the safe choice here — see C4), `lvlJc val="left"`,
and a `w:pPr/w:ind` with a hanging indent wide enough for `%1.%2` (≈ 432 twips at level 0,
≈ 576 at level 1). Give `Heading1`'s style `w:ind` a matching hanging value.

### C4. The numbering tab lands on a leftover dot-leader tab stop

`TERMO DE CESSÃO DE DIREITOS` carries, from the source:

```xml
<w:tabs>
  <w:tab w:val="clear" w:pos="709"/>
  <w:tab w:val="right" w:pos="8504" w:leader="dot"/>
</w:tabs>
```

A right tab at 8504 twips with a **dot leader** — a relic of the hand-typed summary
formatting that the source pasted onto its headings. Combined with C3's implicit
`suff="tab"`, Word renders `3`, then a tab that runs dots all the way to 8504, then the
heading text, which no longer fits and wraps after `T`. That is screenshot 6 exactly.

Thirteen headings carry the same dot-leader tab stop (see the C1 table); only TERMO shows
the artefact today because the others' direct `numPr` happens to suppress it.

**Fix.** Two independent changes, both worth making:

1. Strip dot-leader tab stops from every paragraph the builder styles as a heading — the
   summary they belonged to no longer exists.
2. Set `w:suff w:val="space"` on both levels of `abstractNum` 900, so no tab is emitted at
   all and no future stray tab stop can reproduce this.

Add a gate assertion: no `Heading1`/`Heading2` paragraph may carry a `w:tab` with
`w:leader`.

---

## D. TOC field and the update prompt

### D1. `updateFields` prompts on every open, by design

Screenshot 2 — "This document contains fields that may refer to other files" — is Word's
unconditional response to `<w:updateFields w:val="true"/>`. It cannot be suppressed while
that setting is present. The consultant sees it on every report, and answering *No* leaves
the document with no summary at all (see D2).

**Fix.** Drop the global setting and mark the TOC field itself dirty:

```xml
<w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>
```

Word updates a dirty field silently on open, with no prompt. This is the standard way
Word itself writes a to-be-refreshed TOC.

Requires changing the `field-update-disabled` assertion in `gates/master.py:352-360`,
which currently *hard-requires* `updateFields == "true"`, plus the corresponding assertion
in `tests/test_master_build.py`, `docs/adr/0001` ("A real `TOC` field with `updateFields`
recomputes it…"), and the `MASTER-DIFF.md` wording.

### D2. The TOC field has no cached result

`_toc_paragraph` (`master.py:473-495`) writes a single result run reading
`"Atualize o sumário no Word."`. If the field is not updated — the user declines the
prompt, or opens the file in a viewer that does not compute fields — the document's entire
summary is that one sentence. With D1 applied, Word will always update it; but the
fallback is still worth improving.

**Fix (optional, after D1).** Either accept the placeholder as the documented fallback, or
generate cached `TOC1`/`TOC2` result paragraphs from the known heading list with a
right-aligned dot-leader tab (the legitimate use of one) and a `PAGEREF` per entry, so an
un-updated open still shows a structurally correct summary with stale page numbers.

---

## E. Layout defects inherited from the source

The reviewer's own note applies here: these originate in the poorly formatted "gold
standard", but the Master is where they get fixed.

### E1. Stray hand-typed page reference

Body paragraph 33 is the literal text `Ficha Técnica SEBRAETEC 4.0 – Pág. 3`, right-aligned
and italic — a hand-typed page reference, not a field. It is not a page counter and does
not track pagination, so it is wrong for essentially every client, for the same reason the
hand-typed summary was (`docs/adr/0001`). `_source_replacement` has no rule for it, so it
passes straight through.

**Fix.** Decide whether this is a source citation ("Ficha Técnica SEBRAETEC 4.0, p. 3",
referring to the *SEBRAETEC spec*, not to this document) or a stray leftover.

- If a citation: keep the text but drop the `– Pág. 3` if it was meant to point at this
  document; it currently reads as a page counter and confuses reviewers.
- If a leftover: add a `_source_replacement` rule removing the paragraph, and add
  `Pág. \d+` to a gate assertion forbidding literal page references in the body.

Confirm with the owner which it is — this is the one item here that needs a ruling rather
than a fix.

### E2. `CABEÇALHO` block image overflows the text column

Page width 11906 twips, left/right margins 1701 each → text column **5.91 in**. Measured
`wp:extent/@cx` for the eight Block images:

| Block | width |
|---|---|
| PÁGINA HOME, SEÇÃO PRODUTOS, VÍDEOS, CONTATO, SOBRE, POLÍTICAS, RODAPÉ | 5.91 in |
| **CABEÇALHO** | **7.09 in** ← 1.19 in past the right margin |

The header mock-up is a wide, short strip (7.09 × 0.60 in) that was never scaled to the
column when the source was assembled.

**Fix.** Scale any Block image whose `cx` exceeds the column to fit, preserving aspect
ratio — set both `wp:extent` and the sibling `a:ext` on the `pic:spPr/a:xfrm`. Do it in
`_canonicalize_blocks`, which already normalises Block geometry, and add a gate assertion
that no `wp:extent/@cx` in the body exceeds the section's text column width. This also
protects the per-client Blocks cloned from `MASTER_BLOCK_STAMP`, which inherit the stamp's
extent (`clone_block_stamp`, `master.py:372`).

### E3. Media neutralisation makes overflow visible

`_png_stamp` (`master.py:169`) fills the image's full extent with `F2F2F2` grey and a
`C00000` border. The source logo presumably had white or transparent bleed, so E2 was
invisible in the gold standard and is glaring in the Master. Not a defect in itself — it is
the neutraliser doing its job — but it means **every** oversized extent in the source now
shows. E2's gate assertion should be run over all media, not just the Blocks.

---

## F. Gate blind spots

`gates/master.py` passes on all of the above. Consolidating the assertions proposed in this
document:

| Assertion | Covers |
|---|---|
| Element-sequence validation of `numbering.xml`, `styles.xml`, `settings.xml`, every `w:pPr` | A1–A5 |
| Embedded font's internal `name` ID 1/16 matches its `fontTable.xml` `w:font w:name` | B1 |
| No `fvar` table in any embedded font part | B1 |
| Every `w:rFonts` in a heading style is free of `*Theme` attributes | B3 |
| No `Heading1`/`Heading2` paragraph carries a direct `w:numPr` | C1 |
| `abstractNum` 900 declares `suff`, `lvlJc` and `pPr/ind` per level | C3 |
| No `Heading1`/`Heading2` paragraph carries a `w:tab` with `w:leader` | C4 |
| TOC `begin` `fldChar` carries `w:dirty="true"` (replacing the `updateFields` assertion) | D1 |
| No body text matches `Pág\.\s*\d+` | E1 |
| No `wp:extent/@cx` exceeds the section text column width | E2, E3 |

Two things automation still cannot prove, and which must stay on the human checklist:
Word actually recomputing the summary on open, and rendering on a machine without
Montserrat installed. B1 means the second one is currently expected to fail.

---

## Suggested order

1. **A6** — the ordered-insert helper. Everything in A follows from it, and it prevents the
   class of bug recurring.
2. **A1, A2** — kills the repair dialog and the `Lists` errors (screenshots 1 and 3).
3. **C1, C3, C4** — makes numbering real and fixes the malformed heading (screenshot 6).
   Get the owner's ruling on the resulting Heading 1 range first (C2).
4. **D1** — kills the field prompt (screenshot 2). Touches the gate, tests and ADR.
5. **B1, B2, B3** — static font instances; the only path to the "renders without the fonts
   installed" criterion.
6. **E2** — image scaling (screenshot 5).
7. **E1** — needs an owner ruling (screenshot 4).
8. **A3, A4, A5, B4, D2, F** — correctness and regression cover.

## Note

`.gitignore:18` is a blanket `*` inside a block commented `# .graphifyignore`, which
ignores `docs/`. This file needs `git add -f`, or that block needs scoping — `docs/adr/`
is only tracked because it predates the rule.
