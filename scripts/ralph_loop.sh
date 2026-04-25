#!/usr/bin/env bash
set -euo pipefail

PROMPT='Study @docs/specs/shop_arena/shop_explore.md; Pick the most important task from @docs/impl/shop_explore_implementation.md,
do it end-to-end (edit code, run tests), then mark it "- [x]" in @docs/impl/shop_explore_implementation.md
and commit with a short message. If no unchecked tasks remain, print
exactly "ALL TASKS ARE DONE" and stop.'

for i in {1..50}; do
    echo "=== Ralph iteration $i ==="
    out=$(pi -p "$PROMPT" 2>&1 | tee /dev/tty)
    if grep -q "ALL TASKS ARE DONE" <<< "$out"; then
    echo "✅ task list drained"; break
    fi
    # safety: stop if no checkbox progress was made
    if ! git diff --quiet docs/impl/shop_explore_implementation.md; then git add docs/impl/shop_explore_implementation.md; fi
done
