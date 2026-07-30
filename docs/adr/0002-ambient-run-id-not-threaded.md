---
status: accepted
---

# The Run id reaches events through an ambient ContextVar, not through signatures

Every event the backend emits must name the Run it belongs to, and the code that emits
the most interesting events sits four or five calls below the only place that knows the
Run id. `RunService._execute` receives `run_id` at `runs.py:226`; the Gemini call whose
model choice we most need recorded happens inside `GeminiProseProvider.generate`, which
is reached through `assemble_output_package` → `generate_report` → the prose drafting
seam. Threading `run_id` down that path means widening every signature along it,
including one that is deliberately narrow: `prose.py:87-94` declares `ProseProvider`
"the single replaceable boundary around model execution" with a two-argument `generate`,
and the whole value of that boundary is that a fake can satisfy it in four lines — which
the fakes in `test_gemini_provider.py` and `test_web_app.py` do. **We therefore set the
Run id once, in a module-private `ContextVar` in `events.py`, exposed only as a
`run_scope(run_id)` context manager wrapped around the body of `_execute`, and no
function signature anywhere changes.**

The honest cost is that this is the only ambient global in a codebase that otherwise
threads its cross-cutting concern explicitly: `progress` is passed as a callback from
`RunService` through `assemble_output_package` into every stage boundary, which is the
same shape of problem solved the opposite way. That inconsistency is real and was
accepted rather than overlooked. The two differ in what breaks when they are wrong. A
missing `progress` call fails a Run — `runs.py:284` rejects any Run whose
`stage_history != STAGES` — so the explicit parameter is buying enforcement of a
contract. A missing `run_id` costs one unattributed line in a log. Paying for the
second with the same widening that the first justifies would mean spending the
replaceability of the model boundary on diagnostics.

## Consequences

`run_scope` is the only supported way to set the id, and it must reset its token on
exit including on the exception path, because the `ThreadPoolExecutor` at
`runs.py:197` reuses its two workers across Runs; a leaked token would attribute one
consultant's Run to another's log. `ContextVar` gives each thread its own value, so
the two concurrent Runs cannot collide, and Playwright's synchronous API in
`capture.py` runs on the calling thread, so the id survives into the capture path —
asserted by a test rather than assumed.

Events emitted with no Run in scope carry `run_id=None`, and that is correct rather
than a gap: the CLI entry points have no Run at all. It also means the per-Run sink
silently drops them, so anything worth seeing from a CLI invocation has to be legible
on the stdlib-logger line alone.

The boundary that matters most is what this record is not. **The Run log is not
Provenance.** `CONTEXT.md` defines Provenance as the record of where each artifact in
a finished report came from, with `_Avoid_: audit trail`, and locates it in the run
context and its sidecars — the artefacts the correctness gates read. The Run log is
operational telemetry with a seven-day life, written for whoever is diagnosing a
failure. Nothing in the report may ever be traced to it, no gate may read it, and no
question about what a delivered document contains may be answered from it. Two
competing records of the same truth behind a document a client's legal representative
signs is the failure this separation exists to prevent, and the cheapest way to
stumble into it is to let a log line become the only place some fact was written
down. Where the log surfaces a fact that the report genuinely needs — the fallback
model actually used for a report's prose is the live example — the fix is to record
it in the run context, not to cite the log.
