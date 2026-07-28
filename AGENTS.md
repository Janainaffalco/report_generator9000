# report_generator9000

Pipeline that generates the `RELATÓRIO TÉCNICO FINAL` SEBRAETEC delivers at the close of a
consultancy engagement. See `CONTEXT.md` for the domain glossary.

## Delivery surface

**This ships as a local app, not a CLI.** The code currently reads CLI-shaped — module
entry points, argument parsing, subprocess-driven gate tests — and that is an artefact of
how the pipeline was built, not the product. Do not design features around a terminal
operator, and do not add flags as a way of exposing behaviour to a consultant.

The approved flow is: drop the control spreadsheet in, pick an engagement row, generation
runs **unattended to completion**, review the rendered preview, download `.docx` and `.pdf`.
There are no interactive steps inside generation — no prompts, no confirmations, no
consultant-in-the-loop cropping or selection. Anything a consultant might want to adjust is
adjusted in Word afterwards, during review, which is where they are already working.

It is **VPS-deployed**, not local. Finished runs are retained for **7 days**, to enable
caching and reruns rather than as an archive — treat anything older as gone and
re-derivable from the spreadsheet and the site.

The consequence for design decisions: when a step is ambiguous, the pipeline must **decide
or stop**, never ask. A Stop Condition, a Placeholder with its class, or a Pendência are the
three honest outcomes; a question to a human at generation time is not one of them.

The approved UI mockup lives in Claude Design as `Report generator UI mockup`, project
`2d8d4cf1-ca15-4fa3-b409-a6d7a87ed76c`, file `Relatorios Pinterest.dc.html`. Treat it as a
north star, not a specification — its boxes are schematic and its dimensions are not
commitments.

## Agent skills

### Issue tracker

GitHub Issues via the `gh` CLI, on `seriouslyvictor/report_generator9000`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` and one `docs/adr/` at the repo root. See `docs/agents/domain.md`.
