---
status: accepted
---

# The Loja Virtual purchase path is classified from public evidence

A Loja Virtual report must say how a visitor actually proceeds from a product page,
and nothing more. A WooCommerce installation, a product catalogue or an add-to-cart
signature does not show that the site completes sales, and a WhatsApp button is not a
checkout. Before this, `{{EVIDENCIA_CHECKOUT}}` always carried a TOOL_BLOCKED marker —
a defect by definition — and the `SEÇÃO CARRINHO` and `SEÇÃO CHECKOUT` Blocks were
always TOOL_BLOCKED placeholders, even on a store whose cart was public.

`purchase_path.classify_purchase_path` observes the one published product that
storefront discovery already confirmed (ADR 0006) and returns one of:

- **Indicação por WhatsApp** — a visible action with a purchase label leads to a phone
  number on `wa.me` or `whatsapp.com`.
- **Indicação externa** — a visible purchase action in the product area leads to another
  host.
- **Rota no próprio site** — a same-origin add-to-cart submit is visible *and* the
  store's declared cart page renders with WooCommerce cart markup.
- **Inconclusivo** — none of the above can be shown, or the product page answers 4xx.
  The sentence is replaced by an INCONCLUSIVO Pendência; nothing is guessed from
  WooCommerce markup alone.
- **Falha** — a navigation failed, got no response or HTTP 5xx, or the observation hit an
  unexpected error. A TOOL_BLOCKED Pendência; a technical failure never becomes
  INCONCLUSIVO.

An action counts only by the text a visitor can read: an icon with an `aria-label` has no
visible label, and the pipeline never invents one. A share link ("Compartilhar no
WhatsApp", or any WhatsApp link without a phone number), a chat bubble without a purchase
label, a quantity button, or a purchase button with no link or form behind it is not a
purchase action.

Each sentence states only the visible label and where the action points — a WhatsApp
conversation, an address outside the site, or the site's own cart whose empty page was
opened. None says what happens after the visitor presses it: the report does not press
it, and records no order, payment or transaction.

## Cart and checkout are prints of existing pages

The `SEÇÃO CARRINHO` and `SEÇÃO CHECKOUT` Blocks stay in the Loja grammar and carry only
a Capture of the public page, as the page renders with nothing in it. Their addresses
come from what the store declares — `wc_add_to_cart_params.cart_url`,
`wcSettings.storePages`, or a rendered same-origin link — and each is opened with one GET
navigation. A page that answers 4xx, leaves the store's host, lacks WooCommerce markup,
or (for the checkout) falls back to the cart because the cart is empty gets an
INCONCLUSIVO placeholder, never the cart's print under the checkout heading. A navigation
that fails, gets no response or answers HTTP 5xx is TOOL_BLOCKED: the site failed, it did
not answer. Neither page is named in the Briefing prose.

This amends ADR 0006, which refused every cart and checkout navigation. Viewing an empty
cart or checkout is read-only as long as the browser sends nothing else:
`capture.read_only_purchase_route` aborts every non-GET request and every request that
carries a cart-update, coupon, order, payment or `wc-ajax` parameter, or targets an
account, order, payment or admin path. It guards the observation and the Capture alike.
No item is added, no order is created, nothing is paid.

## INCONCLUSIVO is its own Pendência class

GATED means private evidence a human must supply; TOOL_BLOCKED means the automation
failed; REVIEW means present content awaiting approval; UNDECLARED is about the palette.
None describes public evidence that was read without error and settles nothing, so
`INCONCLUSIVO` joins them. Like every Pendência it keeps the Run a draft.

## Consequences

The `loja-purchase-claims` gate rejects affirmative sentences asserting completed
transactions, online payment processing, configured payment, shipping or stock, a
"secure purchase", or a tested checkout. Negated sentences — the report's own "não
registra pedidos, pagamentos ou transações concluídas" — are exempt, so the gate reads
the report's honest wording as intended. Like `loja-handover-claims` it is a ratchet
against known overclaims, not a proof of honesty.

Every Capture that answers HTTP 4xx/5xx is now a failed Capture for both Temas, because
an error page carries enough colour to pass the blank-Capture check and would otherwise
be photographed as evidence of the page.
