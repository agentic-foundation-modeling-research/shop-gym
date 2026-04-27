# `synth_policies` prompt

Used by `shop_gen.data_synth.policies.SynthPoliciesStep` to draft the
``policies.json`` payload — the storefront's privacy / shipping / terms
/ refund policies. Conditioned on the synthesized identity so the
voice matches the rest of the manual.

The whole file body is the `str.format()` template; documentation
(this paragraph and the heading above) lives outside it because the
loader returns everything below the first `---` divider.

---

You are drafting the storefront's policy pages.

The brand identity is fixed:

```json
{identity}
```

Output one JSON array. Each element is an object with exactly these
fields and nothing else:

- `handle`: one of ``"privacy-policy"``, ``"shipping-policy"``,
  ``"terms-of-service"``, ``"refund-policy"``. Each handle appears at
  most once.
- `title`: short display title (2-5 words).
- `body_html`: HTML body. Use semantic tags
  (``<p>``, ``<h2>``, ``<ul>``, ``<li>``). 2-5 short paragraphs per
  policy. No inline scripts, no inline styles, no real-world brands.

Rules:

- Emit all four policies (``privacy-policy``, ``shipping-policy``,
  ``terms-of-service``, ``refund-policy``) — every storefront ships
  the full set.
- Keep the prose plausible but generic; this is sample data, not legal
  advice.
- Do NOT mention any real-world company, product, jurisdiction, or
  trademark by name.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.

{brand_safety}
