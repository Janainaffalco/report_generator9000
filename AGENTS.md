# report_generator9000

Pipeline that generates the `RELATÓRIO TÉCNICO FINAL` SEBRAETEC delivers at the close of a
consultancy engagement. See `CONTEXT.md` for the domain glossary.

## Agent skills

### Issue tracker

GitHub Issues via the `gh` CLI — note that this directory is not yet a git repo, so the tracker is not usable until `git init` + a GitHub `origin` remote exist. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` and one `docs/adr/` at the repo root. See `docs/agents/domain.md`.
