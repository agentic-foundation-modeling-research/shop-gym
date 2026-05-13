You are merging the ``## {section}`` section of multiple
brand-anonymized storefront manuals into a single coherent section.

Treat the merged capabilities below as ground truth. Drop any sentence
from a seed that contradicts them.

Detail preservation (read carefully — this is the primary rule):

- Preserve every distinct fact, structural detail, UX rule, copy
  style, layout description, behavioral note, and accessibility
  guideline that any seed contributes. Distinct seeds typically
  describe distinct shops; their differences are the signal.
- Collapse only sentence-level duplicates that say the same thing in
  different words. If two seeds disagree on a detail, keep both
  observations as separate bullets / sentences and attribute neither
  — the downstream consumer needs to see the variance.
- When seeds use ``### Element`` subheadings or bullet lists,
  preserve those structural cues. Do not flatten bullet lists into
  paragraphs and do not collapse multiple ``### Element`` blocks
  into one.
- The merged section should contain at least as much specific
  information as the most detailed seed. If you find yourself
  shortening the result, you are removing detail — stop.

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
