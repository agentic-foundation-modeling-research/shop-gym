# `merge_capabilities` tiebreak prompts

Used by `shop_arena.gen.manual_merge.capabilities.merge_capabilities_seeds`
when the deterministic per-leaf rules from spec §9.2 produce a genuine
tie. The file ships **two** named sub-templates, each loaded as a
Python `str.format()` body via
`shop_arena.gen.manual_merge.prompts.load_capabilities_tiebreak_templates()`.

* `descriptor` — invoked once when seeds disagree on `shop.descriptor`.
  Conditioned on the merged tone tags. Spec §9.2 calls this out as the
  only LLM-driven leaf in the table.
* `layout` — invoked when a `*_layout` / `*_style` enum has no clear
  majority. Conditioned on the merged descriptor; the LLM is asked to
  pick from the candidate set, and an out-of-set reply falls back to
  the first-seed value.

The loader splits the file on H2 headings. Body text before the first
H2 (this paragraph included) is ignored.

## descriptor

You are merging the brand-free descriptors of multiple storefronts into
one. The merged storefront combines elements from each.

Merged tone tags (treat as ground truth): {tone}

Each input descriptor is brand-free. Output ONE merged descriptor that:
- is one short phrase (max 12 words),
- is brand-free (no proper nouns of real companies, no trademarks),
- is consistent with the merged tone tags,
- is plain prose, no quotes, no trailing punctuation.

Inputs:
{descriptors}

Output: a single line containing only the merged descriptor.

## layout

You are picking one storefront layout/style enum for ``{path}``.

Candidates: {candidates}
Merged storefront descriptor (treat as ground truth): {descriptor}

Pick the candidate that is most consistent with the descriptor.

Output: a single line containing exactly one of the candidate values,
with no quotes or extra text.
