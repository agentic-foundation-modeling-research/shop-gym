You are merging the ``## {section}`` section of multiple
brand-anonymized storefront manuals into a single coherent section.

Treat the merged capabilities below as ground truth. Drop any sentence
from a seed that contradicts them. Where seeds describe the same surface
with overlapping detail, keep the most specific phrasing once and remove
duplicates.

Brand safety:
- Do not mention any real-world company, product, or trademark.
- Do not invent a fake brand name.
- The merged storefront has no name yet; refer to it as "the
  storefront", "the shop", or via its descriptor.

Style:
- Match the seed's structural register: short prose paragraphs and
  bullet lists. Preserve any ``### Element`` H3 blocks the seeds use.
- Do not add the ``## {section}`` heading — emit the section body only.
- End with a single newline.

## Merged capabilities (ground truth, JSON)

```json
{capabilities}
```

## Seed sections to merge

{seed_blocks}

Output: the merged section body for ``## {section}``. No commentary, no
H2 heading, no fenced wrappers. End with a single newline.
