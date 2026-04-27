# `synth_pages` prompt

Used by `shop_gen.data_synth.pages.SynthPagesStep` to draft the
``pages.json`` payload — the storefront's content pages (about,
contact, FAQ, shipping info, etc.). Conditioned on the merged
capabilities (which surfaces the page list the manual promises) and the
synthesized identity (so the prose voice matches).

The whole file body is the `str.format()` template; documentation
(this paragraph and the heading above) lives outside it because the
loader returns everything below the first `---` divider.

---

You are drafting the storefront's content pages.

The brand identity is fixed:

```json
{identity}
```

The merged capabilities document — ground truth for what pages the
manual promises — is:

```json
{capabilities}
```

Output one JSON array. Each element is an object with exactly these
fields and nothing else:

- `handle`: URL-safe slug (lowercase ASCII, hyphens between words).
  Conventional handles include ``"about"``, ``"contact"``, ``"faq"``,
  ``"shipping"``. Reuse the manual's named pages where possible.
- `title`: short display title (2-6 words).
- `body_html`: HTML body. Use semantic tags
  (``<p>``, ``<h2>``, ``<ul>``, ``<li>``). 1-4 short paragraphs per
  page. No inline scripts, no inline styles, no real-world brands.

Rules:

- Emit between 3 and 6 pages. Always include an ``"about"`` page
  written in the identity's voice.
- Handles must be unique within the array.
- Do NOT mention any real-world company, product, or trademark.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.

{brand_safety}
