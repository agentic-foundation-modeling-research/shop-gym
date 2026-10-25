You are merging the brand-free descriptors of multiple storefronts into
one. The merged storefront combines elements from each.

Merged tone tags (treat as ground truth): {{tone}}

Each input descriptor is brand-free. Output ONE merged descriptor that:
- is one short phrase (max 12 words),
- is brand-free (no proper nouns of real companies, no trademarks),
- is consistent with the merged tone tags,
- is plain prose, no quotes, no trailing punctuation.

Inputs:
{{descriptors}}

Output: a single line containing only the merged descriptor.
