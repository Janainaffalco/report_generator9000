---
status: accepted
---

# The signed-off Master is a versioned runtime asset

`MASTER.docx` is the client-neutral document that the pipeline actually clones.
Once reviewed and signed off, it has its own identity and quality bar. Its
historical derivation from `RELATÓRIO ARGEL.docx` does not make Argel an input,
authority, or prerequisite for either application builds or Runs.

The previous deployment shape excluded all DOCX files and required operators to
place the Master in writable runtime storage. That made a canonical,
application-versioned dependency look like mutable customer data. It also let
the healthcheck pass when the Master was absent, deferring a broken deployment
until a consultant submitted a Run.

**We therefore version the signed-off Master at
`report_generator9000/assets/MASTER.docx`, include it in the Python package and
container image, and use it as the default Master without deployment
configuration.** `REPORT_MASTER_PATH` remains only as an explicit emergency or
test override. A configured Master that is not a file prevents application
startup.

The `master-build` command remains migration and audit tooling. It can derive a
candidate client-neutral document from an explicitly supplied filled DOCX, but
it is not part of the application build and its input is not a source of truth
for the current Master.

## Consequences

- A Git commit identifies the application code and exact Master deployed
  together. Updating either requires the normal review and deployment path.
- Production and development use the same Master asset.
- `/app/data` contains mutable seven-day Run data and optional Gated Drop
  Folders, never the canonical Master.
- Coolify needs no Master upload, bind mount, or `REPORT_MASTER_PATH`.
- The image grows by the size of the signed-off Master, currently under 1 MB.
- Replacing the Master is an application change. It must pass the Master and
  report gates before it is merged.
