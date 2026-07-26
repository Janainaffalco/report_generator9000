# HANDOFF — Deterministic Report Pipeline (SEBRAETEC)
### Architecture brief for prototyping in Claude Code
**Date:** 2026-07-25 · **Scope:** `Inserção digital – Desenvolvimento de WebSite` (Ficha 46003-4)
**Supersedes:** `SPEC-geracao-relatorios-sebraetec.md` v1.0 (agent-execution spec — now reference material only)

---

## 1. What changed and why

v1.0 treated report generation as an **agent task**: an LLM reads a spec, browses, captures, edits XML, self-verifies. A full pilot run against **OMINIRA ENERGIA LTDA** proved the output is achievable but showed the shape is wrong.

Findings from the pilot:

- The pilot's value was **discovering the base document's internals**, not producing the report. That discovery is now done and is captured in §4 below. It does not need repeating per client.
- ~85% of the work is mechanical: string substitution, file swaps, zip/unzip, assertions. Deterministic code does this faster, cheaper, and — critically — **without drift between runs**.
- Self-verification by an LLM is the weakest link. Anti-contamination checks must be assertions, not judgement.
- Section-count variability, which looked like judgement, is deterministic once you **generate blocks from the site nav** instead of diffing against ARGEL (§6.3).

**Target architecture:** a Python CLI. One LLM call per report, for prose only. Everything else is code.

```
gerar_relatorio.py --linha 115-2026 [--gated ./gated/115-2026] [--no-llm]
```

---

## 2. Verified environment facts

All confirmed by execution, not assumption:

| Fact | Status |
|---|---|
| Playwright + Chromium launch, render, screenshot @1600×900 | ✅ works |
| `openpyxl`, `Pillow`, LibreOffice 24.2.7.2, `pdftoppm`, `pdftotext` | ✅ available |
| `merge_runs.py` merged 8 fragmented runs in the base doc | ✅ **mandatory** |
| `validate.py out.docx --original base.docx` | ✅ works |
| Montserrat static TTFs from `google/fonts/.../static/` | ❌ 404 |
| Montserrat variable: `github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf` | ✅ works |
| Base `.docx` in `/mnt/project/` | ❌ flattened to text — useless. Use the binary |

**Montserrat caveat:** only the variable font installs. Light vs Medium may not render distinctly in QA PDFs. Cosmetic — affects verification renders only, never the `.docx` itself.

---

## 3. Pipeline

```
 [1] read row ─────────────► openpyxl          code
 [2] stop conditions ──────► type checks       code
 [3] crawl nav ────────────► Playwright        code
 [4] extract page text ────► Playwright        code
 [5] capture screenshots ──► Playwright        code
 [6] derive prose ─────────► LLM  ◄── ONLY MODEL CALL
 [7] clone base ───────────► unzip+merge_runs  code
 [8] substitute text ──────► assertions        code
 [9] rewrite rels ─────────► assertions        code
[10] build blocks from nav ► stamp+loop        code
[11] fill gated inputs ───► file copy         code
[12] placeholders ────────► Pillow            code
[13] repackage ───────────► zip + validate    code
[14] residue checks ──────► SHA-256 + grep    code   ◄── HARD GATE
[15] render + auto-QA ────► pdf + heuristics  code
[16] gap report ──────────► from manifest     code
[17] sampled visual review► LLM (optional)
```

**Budget per report:** ~2k tokens in / ~250 out. 34 rows ≈ one afternoon of compute, near-zero cost.

---

## 4. Ground truth — the base document

Everything in this section was extracted from the real binary. **Do not re-derive it.**

### 4.1 Page setup
- A4, 210 × 297 mm
- Margins: 3 cm left/right, 2.5 cm top/bottom
- **Text column: exactly 5.91 in** — the dominant image width
- `<w:titlePg/>` set → cover has its own header
- 3 headers + 3 footers (first/default/even); footers carry live `PAGE` fields
- Cover's red bar is an **anchored shape** (`srgbClr C00000`, 0.39 × 9.84 in), not an image

### 4.2 Typography
Montserrat: Light (285 runs), Medium (113), Regular (89), ExtraLight (9), Black (2).
`styles.xml` default says Calibri — every run overrides it with direct formatting.
Palette: `C00000`, `767171`, `D43242`.

### 4.3 Structure
Only two paragraph styles exist: `Normal`, `ListParagraph`. **No Heading styles.**
Consequence: the SUMÁRIO is hand-typed with hand-typed page numbers — not a TOC field. Auto-numbering runs out at 2.9; "2.10" and "2.11" are literal text. `2.10 Indicadores` is orphaned (no body section). **Reproduce as-is.**

### 4.4 Block anatomy
A screenshot block is a **3-paragraph triple** (verified):

```
+0  heading paragraph   (text, e.g. "CABEÇALHO")
+1  spacer paragraph    (empty)
+2  image paragraph     (<w:drawing> with r:embed="rIdNN")
```

Insert or delete in triples. Never leave a heading without an image.

### 4.5 Variable map — **CORRECTED**

⚠️ Four entries in v1.0 §5 were wrong. These are the fixed values.

| ID | Search string | Occurrences | Source |
|---|---|---|---|
| V1 | `010028/2025` | 1 | col A |
| V2 | `ARGEL RESISTENCIAS ELETRICAS LTDA` | 2 | col E |
| V3 | `64.525.744/0001-02` | 2 | col D |
| V4 | `Christian Albuquerque Alonso` | 1 | col F |
| V5 | *Sobre a Empresa* paragraph | 1 | **LLM** |
| V6 | *Briefing* ¶1 | 1 | **LLM** |
| V7 | *Briefing* ¶2 | 1 | **LLM** |
| V8 | `22/07/2026` | 1 | GATED |
| V9 | `PLANO SINGLE` | 1 | GATED |
| **V10** | `argelresistencia.com.br` | **2 — NOT 1** | col H |
| V11 | `argelresistencias@hotmail.com` | 1 | GATED |
| V12 | `05/02/2026` | 1 | col G |
| V13 | `25/06/2026` | 1 | GATED |
| **V14** | wp-admin link | **two `<w:hyperlink>` elements**, not one string | derived |
| V15–V18 | 4 Drive URLs | 1 each, **text + rels** | GATED |
| **V19** | "links para download" | **rels only (`rId2`) — no text match** | GATED |

**V10** covers both the domain bullet *and* the wp-admin link text — an `expected=1` assertion halts; no assertion leaks ARGEL's domain.
**V14** is `rId25` (stray text `https://on`) followed by `rId26` (the rest). The v1.0 literal search string matches nothing.
**V19** exists only as a relationship target. Text-only substitution leaves a **live link to ARGEL's credentials folder**.

### 4.6 Relationship map

| rIds | Target | Action |
|---|---|---|
| `rId2` | Drive — links para download | → placeholder |
| `rId4` | w3techs | **keep** |
| `rId5`–`rId14` | 10 plugin URLs | **keep** |
| `rId25` | `https://ondviajar.com.br/wp-admin/` | ⚠️ **cross-client leak** — see §8 |
| `rId26` | ARGEL wp-admin | → client wp-admin |
| `rId33`, `rId35`, `rId36`, `rId37` | Drive folders | → placeholder |

Images: `rId3`→image1, `rId15`→image2, `rId16`→image3, `rId17`→image4, `rId18`→image5, `rId19`→image6, `rId20`→image7, `rId21`→image8, `rId22`→image9, `rId23`→image10, `rId24`→image11, `rId27`→image12, `rId28`→image13, `rId29`→image14, `rId30`→image15, `rId31`→image16, `rId32`→image17, `rId34`→image18, `rId38`→image19, `rId39`→image20.

When deleting a block, **also delete its Relationship entry and its `word/media/` file** — orphans survive otherwise and trip check 14.2.

### 4.7 Slot inventory

| File | Size (in) | Class |
|---|---|---|
| `image1.png` | 1.07 × 1.07 | BOILERPLATE — keep |
| `image2.png` | 1.39 × 1.49 | CAPTURE (logo) |
| `image3.png` | 5.09 × 1.04 | GATED (paleta) |
| `image4.png` | 5.91 × 3.37 | CAPTURE |
| `image5.png` | 5.91 × 3.37 | CAPTURE |
| `image6.png` | 5.83 × 3.33 | CAPTURE |
| `image7.png` | 5.91 × 3.37 | CAPTURE |
| `image8.png` | 5.91 × 3.37 | CAPTURE |
| `image9.png` | 5.91 × 3.28 | CAPTURE |
| `image10.png` | 7.09 × 0.60 | CAPTURE (cabeçalho — bleeds into margins) |
| `image11.png` | 5.91 × 1.88 | CAPTURE (rodapé) |
| `image12.png` | 5.31 × 0.45 | GATED |
| `image13.png` | 5.91 × 3.15 | GATED |
| `image14.png` | 5.91 × 3.59 | GATED |
| `image15/16/17.png` | 3.29×5.34, 3.94×2.68, 4.12×1.95 | GATED — **all three in ONE paragraph** |
| `image18.png` | 5.85 × 2.01 | GATED |
| `image19.jpeg` | 3.93 × 3.30 | GATED |
| `image20.png` | 5.47 × 2.78 | GATED |
| `image21.png` | header | BOILERPLATE — keep |

---

## 5. Input: the spreadsheet

Sheet **`LV e Site`**, header row 1, data from row 2, 54 rows.

| Col | Field | Use |
|---|---|---|
| A | Título | demanda |
| B | nº da pasta | output folder |
| C | Tema Contrato SENAI | **filter: `Inserção digital - Desenvolvimento de WebSite`** |
| D | CNPJ | cover + termo |
| E | Razão Social | cover + termo |
| F | Consultor responsável | especialista |
| G | Kick off | datetime → `dd/mm/yyyy` |
| H | `Link ` | **overloaded** |
| I | `Relatório  pronto?` | skip row if non-empty |

Header strings contain irregular whitespace (`'Link '`, `'Relatório  pronto?'`) — match by position or normalize.

**Column H holds a URL *or* a datetime.** Type-check every cell:
- `datetime` → delivery date, no URL → **stop**
- `str` with `http` → site URL. Reject if a second domain is concatenated after the path
- `None` → **stop**

Addressable today: **8 rows** with a live URL and no report.

---

## 6. Deterministic section generation

### 6.1 The inversion
Don't diff against ARGEL. **Stamp blocks from the nav.**

```
nav = crawl(home)
for item in nav:
    if off-domain or different subdomain: skip
    if item is home:  emit block("PÁGINA HOME")
    else:             emit block("SEÇÃO " + upper(label))
emit block("CABEÇALHO"); emit block("RODAPÉ")
```

Validated against Ominira: nav = Home / Artigos e Materiais / Sobre / Contato, plus "Portal do Cliente" on `hub.ominiraenergia.com.br` — a different host, correctly dropped. Result matches the manual pilot exactly. **Order = nav order, free.**

### 6.2 Implementation
Keep one block triple as a **stamp**. For each nav item, clone it, set the heading text, register a new Relationship + media file. Delete unused ARGEL blocks with their rels and media.

### 6.3 Failure mode
Odd shapes — one-page sites with anchor nav, hamburger-only menus, 12-item navs. **Fail loudly into the stop-condition path.** Do not guess. Revisit after ~5 real runs; add LLM triage only if it proves common.

---

## 7. Gated content — invert it into an input

9 of 19 client slots are unfillable by any automation. Rather than always shipping a holed document, accept a **drop folder**:

```
gated/115-2026/
  paleta.png      login.png       painel.png
  yoast-a.png     yoast-b.png     yoast-c.png
  drive.png       kickoff.jpg     entrega.png
  dados.yaml      # plano_hospedagem, email_cliente, data_entrega,
                  # data_backup, links_drive[4]
```

Pipeline consumes what's present, placeholders only what's missing. This flips the deliverable from *"report with holes"* to *"drop 9 files → finished report."* **That is the actual product.**

Missing files are never an error — just a placeholder plus a `PENDENCIAS.md` line.

---

## 8. `rId25` — cross-client leak (decision required)

The approved ARGEL document contains a live hyperlink to **`https://ondviajar.com.br/wp-admin/`** — a *different client's* URL, left by a previous copy-paste. Visible text is the mangled `https://onhttps://argelresistencia.com.br/wp-admin/`.

"Reproduce exactly" covers formatting and wording. It does not extend to propagating a third party's URL into a new client's contractual document.

**Pilot behaviour (default):** preserve the visible text artifact; repoint the target to the client's own wp-admin; log as `DECISION-REQUIRED`.
**Needs a human ruling** before batch runs. Alternative: clean the base document once, with stakeholder sign-off, and generate from a corrected master.

---

## 9. Placeholders — two distinct classes

The pilot proved these must not be conflated:

| Class | Meaning | Example |
|---|---|---|
| `GATED` | Structurally unobtainable; expected | WP painel, Teams prints |
| `TOOL_BLOCKED` | Should have been captured; automation failed | browser crashed mid-run |

If a failed capture looks like a deliberate gap, the gap report becomes useless — a human can't tell what needs fetching versus what broke. **Distinguish in the manifest, in `PENDENCIAS.md`, and in the placeholder image caption.**

Placeholder rendering: solid `#F2F2F2`, 3px `#C00000` border, exact slot dimensions at 150 dpi, three centred lines (banner / slot name / class).

---

## 10. Playwright configuration

```python
viewport = {"width": 1600, "height": 900}
device_scale_factor = 2      # ← revised: v1.0 said 1; slots print ≥150dpi
```

**Lazy loading is the silent killer.** Elementor lazy-loads; naive `goto` + `screenshot` yields blank heroes. Required: scroll to bottom → wait for network idle → scroll back → capture.

**Cookie banners:** encode a dismissal selector list (Complianz, CookieYes, Elementor). Always decline non-essential. If undismissable without accepting, capture with banner visible and flag it.

**Post-processing:** preserve aspect ratio — hold `cx` at the slot width, recompute `cy` from the real image ratio. **Never stretch.** Downscale to ≤1600px before embedding (ARGEL carries four ~1 MB images needlessly; 6.4 MB total).

---

## 11. Validation gates

Ordered. Any ❌ = do not ship.

| # | Check | Method |
|---|---|---|
| 11.1 | Base is a real docx | 52 zip entries incl. `word/media/image4.png` |
| 11.2 | Output validates | `validate.py --original` |
| 11.3 | **No ARGEL text** | grep `argel\|64.525.744\|christian\|010028\|ondviajar` → 0 |
| 11.4 | **No ARGEL media** | SHA-256 per file; only `image1`/`image21` may match |
| 11.5 | **No ARGEL rels** | no ARGEL `drive.google.com`, no `ondviajar` |
| 11.6 | No orphan rels/media | every rel resolves; every media file referenced |
| 11.7 | Blocks well-formed | heading ↔ image paired |
| 11.8 | Renders | soffice → pdf → pdftoppm |
| 11.9 | Page count 15–19 | `pdfinfo` |
| 11.10 | Gap report ↔ reality | every placeholder in manifest and vice versa |

**11.3–11.5 are the anti-contamination gate** — the only thing standing between this pipeline and shipping one client's admin panel to another. **Assertions, never LLM judgement.**

### Automated visual QA (replaces most of the eyeball pass)
- **Blank/failed lazy-load** → color-count threshold. Measured: blank capture ≈ 736 colors; real rendered page ≈ 3255. Cleanly separable.
- **Stretched image** → assert capture ratio vs slot `cx/cy`
- **Overflow / drift** → `pdftotext` greps + page count

Leaves visual review as a **sampled** pass — pages with new captures only (3–4 images), not 17. Optional if all gates pass.

---

## 12. Outputs

```
outputs/<pasta>_<RAZAO_SLUG>/
  RELATORIO_<RAZAO_SLUG>.docx
  PENDENCIAS.md          # human-readable, GATED vs TOOL_BLOCKED
  pendencias.json        # {slot, name, page, class, reason, action_required}
  preview/page-NN.jpg
  capturas/              # raw screenshots, native resolution
```

**Never describe an output with placeholders as "complete" or "ready to send."**

---

## 13. LLM call — the one model dependency

**Input:** script-extracted page text (Sobre/Quem Somos, Home hero, product/service listing) — never raw HTML.
**Output:** V5, V6, V7. ~2k in / ~250 out.

Constraints:
- Ground every claim in extracted text. No embellishment, no superlatives the client didn't write about itself.
- **No outside research** — no LinkedIn, news, CNPJ registries. Unverifiable and out of scope.
- V7 must list the pages found in §6.1, in nav order.
- No Sobre content on the site → placeholder. Never invent a company description.

**This is the only hallucination surface in a document the client legally signs.** Mark it in `PENDENCIAS.md` as *texto gerado — conferir* so the consultant reviews deliberately rather than skimming past.

`--no-llm` should emit `[TEXTO A REDIGIR]` placeholders and skip the call entirely.

---

## 14. Non-negotiables

1. **Clone-and-substitute — never regenerate.** "Deterministic" means scripted XML editing of the ARGEL binary. It does **not** mean building with `python-docx`/`docx-js`. Rebuilding loses Montserrat runs, the cover shape, and the three header/footer pairs. If someone later reads "make it deterministic" as "generate it," fidelity is gone.
2. **`merge_runs.py` before any substitution.** Word fragments text across runs; skipping it makes substitutions silently no-op — producing a report still bearing ARGEL's name while reporting success.
3. **Never authenticate.** No WordPress, Hostinger, Google, Teams. No credentials from any source.
4. **Never reuse another client's screenshot**, and never synthesize, mock, or AI-generate a substitute.
5. **Never infer** a gated value from "what it usually is."
6. **Anti-contamination checks are assertions.**

---

## 15. Out of scope

- **Loja Virtual** (20 rows) — no approved model exists
- **Marketing themes** (53 rows, separate sheet, different schema) — same
- **Spreadsheet data quality** — col H overloading, temp `*.hostingersite.com` URLs, one row with two concatenated domains, empty `Quem está executando`, mixed `ok`/`Ok`. Recommend splitting H into `Link` + `Encerramento` as the Marketing sheet already does.
- **Fixing the base document's defects** (`https://on` artifact, "A portal web", "envoi", orphaned 2.10). Reproduce as approved unless §8 is ruled otherwise.

---

## 16. Open decisions

1. **`rId25`** — repoint (pilot default), leave untouched, or clean the master with sign-off?
2. **Gated drop-folder** — adopt §7, or accept always-partial output?
3. **Client e-mail (V11)** — Ominira publishes `contato@…` on its site. Pilot left the placeholder: the field is the credentials-handoff recipient, not the public address. Confirm this reading.
4. **Base document** — `docProps` shows created 2023-09-28 by **Tatiana Dias Valsechi**, rev 31. If a clean pre-ARGEL master exists, it is a better clone source than a filled instance.
5. **Suggested first target** — the 8 website rows with live URLs. Ominira (`115-2026`) already has a full manual reference run to diff against.

---

## 17. Prototype order

1. `sheet.py` — read + filter + stop conditions *(no deps, testable immediately)*
2. `docx_edit.py` — clone, merge_runs, substitute, rels, repackage, validate *(deterministic, testable against the pilot output)*
3. `checks.py` — gates 11.1–11.10 *(write before capture; it's the safety net)*
4. `capture.py` — Playwright *(needs a live domain; run on your machine, not the sandbox)*
5. `blocks.py` — nav-driven stamping *(the genuinely new logic)*
6. `prose.py` — the single LLM call *(last; `--no-llm` works without it)*

Steps 1–3 reproduce the Ominira pilot with zero LLM involvement and no network. **That's the milestone that proves the concept.**
