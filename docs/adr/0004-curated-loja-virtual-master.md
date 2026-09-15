---
status: proposed
---

# Loja Virtual uses its own curated, versioned Master

`Implantação de Loja Virtual` has a separate Master at
`report_generator9000/assets/MASTER-LOJA-VIRTUAL.docx`. It is curated from the
client-neutral WebSite Master by `scripts/build_loja_master.py`, which preserves
the SEBRAETEC cover, fonts, live TOC and Slot geometry while replacing the
section grammar and unsafe WebSite assertions. The filled Loja Virtual report
in `referencias/` is a design reference only; it is never a build input.

This first Loja Virtual Run is a draft. Public page Blocks and the site's visual
identity use the existing capture path. Private WooCommerce configuration and
administrative images remain GATED unless supplied. Freeform private WooCommerce
configuration is left for Word review instead of automatic insertion. The pipeline does not yet
verify the public cart and checkout flow, so that evidence is explicitly
TOOL_BLOCKED. Standard WordPress, WooCommerce and plugin descriptions are
Boilerplate and do not assert which features or plugins this client uses.

No credential disclosure or old schedule is carried into the Master. Loja
Virtual has a report gate that rejects credential-bearing text, including text
supplied through a Gated Input. The WebSite Master and report gates stay on
their existing contract. Both Masters are shipped with the application; the
emergency `REPORT_MASTER_PATH` override remains scoped to WebSite.
