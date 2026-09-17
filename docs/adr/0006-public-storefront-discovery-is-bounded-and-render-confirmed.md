---
status: accepted
---

# Public storefront discovery is bounded and render-confirmed

`Implantação de Loja Virtual` cannot rely on the main menu to find the public
storefront. Product cards, category links, filters, or a shop link may exist only in
the rendered body, and a public WooCommerce Store API can expose a published product
without exposing any administrative data.

The `storefront` module owns one interface:
`discover_storefront_pages(capture_origin, existing_pages)`. Its implementation runs a
fixed ladder: rendered same-origin links first, the same-origin read-only Store API
second, then WooCommerce markup and URL hints for classification. Candidate counts,
confirmation navigations, Store API results, and selected taxonomies all have explicit
budgets. The module performs GET and page-navigation work only; cart, checkout, order,
payment, account, login, admin, and mutation-shaped URLs are refused before navigation.

A candidate enters the Lista de Páginas only after a browser renders a non-empty page
without leaving the Capture Origin host. The selected listing becomes `SEÇÃO PRODUTOS`,
at most one representative published product is selected, and applicable categories or
filters are optional. A confirmed listing also earns a separate `VITRINE MOBILE`
Capture at a fixed narrow viewport. The mobile duplicate is evidence in the document but
does not repeat the listing in Briefing prose.

Store API absence, an unhelpful menu, unrecognised CSS classes, and absent optional
categories or filters return less evidence, not invented Blocks and not a Stop
Condition. Once selected, a later failed Capture follows the existing TOOL_BLOCKED path.
If no Capture from the site is usable, the existing run-level Stop Condition remains the
honest outcome.

Loja's final ordered Lista also contains classified required evidence gaps created by
`loja_draft_blocks`. Those entries do not enter Briefing prose. The same final Lista is
passed to prose generation, Block stamping, the Run context, and the delivered package,
so confirmed public pages cannot drift between narrative and evidence.
