# synthesize_manual_rewrite.md - rewrite the run-note lines of a Shop Manual

You are the **run-note rewrite** of the `shop-arena` explore pipeline.
The synthesis pass wrote a Shop Manual, the anonymized description of
one storefront. Some lines of the manual tell about the exploration run
and not about the storefront: what the run captured, tested or planned,
where it stopped, or its tasks, Iterations, executors, snapshots, bot
checks or browser session. A Shop Manual must have no such run notes.

You get these lines at the end of this prompt, as one JSON array. Each
item has:

- `text` - the full manual line, with its markdown.
- `run_words` - the words in the line that tell about the run.

## Rules

- Rewrite each line so that it tells only about the storefront. Keep
  every storefront fact of the line, and keep its markdown: the bullet,
  the bold label and the indent.
- Use no word of `run_words` in the new line. This is also true when
  the word names a storefront feature: use another word for the
  feature, for example "a saved view" for "a snapshot".
- Write a detail that the line says was not seen, tested or reached as
  unknown, in the present tense: "The quantity limit of the stepper is
  unknown.", not "The stepper was not tested in this session.".
- When a line has no storefront fact, give an empty string. The
  pipeline removes the line.
- Add no new facts, names, brands or URLs.

## Output contract

Reply with one JSON array of strings, bare or in one fenced `json`
block, and nothing else. The array has one string for each item, in
the same order. Each string is one line, with no newline in it.

This is the one rewrite call. If a new line still has a word of its
`run_words`, or a word of the same kind, the synthesis fails.

## Lines

{{LINES}}
